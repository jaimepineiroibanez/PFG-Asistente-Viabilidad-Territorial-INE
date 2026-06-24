# ============================================================
# telegram_bot_estudio_mercado.py
# ============================================================
#
# Bot de Telegram para el asistente de estudios preliminares
# de mercado basado en datos del INE.
#
# Este bot NO usa el pipeline antiguo de preguntas abiertas.
# Usa el nuevo pipeline guiado:
#
#   texto usuario -> negocio + territorio -> pilares -> consultas
#   -> FAISS + DuckDB -> informe final
#
# ============================================================

import os
import re
import tempfile
import traceback

from telegram import Update, InputFile
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from configuracion.config_ine import (
    INPUT_INDEX,
    INPUT_METADATA,
    INPUT_DUCKDB,
    NOMBRE_TABLA_DUCKDB,
    MODELO_EMBEDDINGS,
    MODELO_LLM,
    TOP_K_FINAL,
    LIMITE_POR_CANDIDATO,
    SCORE_FINAL_MINIMO,
)

from codigo.respuesta.faiss_retriever_ine import (
    cargar_indice_faiss,
    cargar_metadata_faiss,
    cargar_modelo_embeddings,
)

from codigo.respuesta.duckdb_retriever_ine import conectar_duckdb

from codigo.respuesta.pipeline_estudio_mercado import ejecutar_estudio_mercado
from codigo.respuesta.interpretar_estudio_mercado import interpretar_estudio_mercado

from codigo.utilidades.telegram_logger_ine import (
    crear_fichero_log_telegram,
    escribir_log_telegram,
    crear_fichero_resultados_telegram,
    escribir_log_resultados_telegram,
)

# ============================================================
# ESTADO GLOBAL DEL BOT
# ============================================================

index = None
metadata = None
modelo_embeddings = None
con_duckdb = None
path_log_telegram = None
path_resultados_telegram = None

# ============================================================
# UTILIDADES
# ============================================================

def dividir_mensaje(texto, limite=3900):
    """
    Telegram tiene un límite de longitud por mensaje.
    Esta función divide el informe final en bloques seguros.
    """
    if texto is None:
        return ["No se ha generado ningún informe."]

    texto = str(texto)

    if len(texto) <= limite:
        return [texto]

    partes = []
    actual = ""

    for linea in texto.splitlines():
        if len(actual) + len(linea) + 1 > limite:
            if actual:
                partes.append(actual)
            actual = linea
        else:
            actual += ("\n" if actual else "") + linea

    if actual:
        partes.append(actual)

    return partes


def obtener_resumen_interpretacion(resultado):
    """
    Genera un pequeño resumen inicial con el negocio y territorio detectados.
    Es útil para que el usuario sepa qué ha entendido el sistema.
    """
    negocio = resultado.get("negocio")
    territorio = resultado.get("territorio")
    pilares = resultado.get("pilares", [])

    if not negocio or not territorio:
        return None

    lineas = [
        "Interpretación detectada:",
        f"- Negocio: {negocio}",
        f"- Territorio: {territorio}",
    ]

    if pilares:
        lineas.append(f"- Pilares analizados: {', '.join(pilares)}")

    return "\n".join(lineas)

def limpiar_nombre_archivo(texto):
    texto = str(texto).lower()
    texto = re.sub(r"[^a-z0-9áéíóúñü]+", "_", texto)
    texto = texto.strip("_")
    return texto or "informe"

def ajustar_lineas_txt(texto, ancho=100):
    """
    Ajusta líneas largas del TXT sin romper palabras.
    Mantiene títulos, separadores y líneas vacías.
    También ajusta listas respetando la sangría.
    """
    if not texto:
        return ""

    lineas_finales = []

    for linea in str(texto).splitlines():
        linea_original = linea.rstrip()

        if not linea_original.strip():
            lineas_finales.append("")
            continue

        # No tocar títulos ni separadores
        if (
            linea_original.startswith("#")
            or set(linea_original.strip()) <= {"=", "-"}
            or len(linea_original) <= ancho
        ):
            lineas_finales.append(linea_original)
            continue

        # Detectar viñetas/listas
        prefijo = ""
        contenido = linea_original

        if linea_original.startswith("- "):
            prefijo = "- "
            contenido = linea_original[2:].strip()
        elif linea_original.startswith("* "):
            prefijo = "* "
            contenido = linea_original[2:].strip()

        ancho_contenido = ancho - len(prefijo)
        palabras = contenido.split()
        linea_actual = prefijo

        for palabra in palabras:
            extra = 0 if linea_actual.endswith(" ") else 1

            if len(linea_actual) + len(palabra) + extra <= ancho:
                if linea_actual == prefijo:
                    linea_actual += palabra
                else:
                    linea_actual += " " + palabra
            else:
                lineas_finales.append(linea_actual)
                linea_actual = " " * len(prefijo) + palabra

        if linea_actual.strip():
            lineas_finales.append(linea_actual)

    return "\n".join(lineas_finales)

def formatear_informe_telegram(informe):
    if not informe:
        return "No se ha podido generar el informe."

    texto = informe

    texto = texto.replace("# INFORME PRELIMINAR DE VIABILIDAD TERRITORIAL", "📄 INFORME PRELIMINAR DE VIABILIDAD TERRITORIAL")
    texto = texto.replace("# # INFORME PRELIMINAR DE VIABILIDAD TERRITORIAL", "📄 INFORME PRELIMINAR DE VIABILIDAD TERRITORIAL")

    reemplazos = {
        "## Negocio analizado": "🏢 Negocio analizado",
        "## Territorio analizado": "📍 Territorio analizado",
        "## 1. Contexto poblacional": "👥 1. Contexto poblacional",
        "## 2. Perfil demográfico": "📈 2. Perfil demográfico",
        "## 3. Situación económica": "💰 3. Situación económica",
        "## 4. Situación laboral": "💼 4. Situación laboral",
        "## 5. Tejido empresarial": "🏢 5. Tejido empresarial",
        "## 6. Actividad empresarial": "📊 6. Actividad empresarial",
        "## 7. Sector específico del negocio": "🏪 7. Sector específico del negocio",
        "## 8. Turismo": "🏖️ 8. Turismo",
        "## 9. Limitaciones del análisis": "⚠️ 9. Limitaciones del análisis",
        "## 10. Valoración territorial preliminar": "🧭 10. Valoración territorial preliminar",
    }

    for original, nuevo in reemplazos.items():
        texto = texto.replace(original, nuevo)

    texto = texto.replace("---", "━━━━━━━━━━━━━━")

    return texto

def extraer_seccion(informe, numero):
    patron = rf"## {numero}\..*?(?=## {numero + 1}\.|## 8\.|## 9\.|$)"
    match = re.search(patron, informe, flags=re.DOTALL | re.IGNORECASE)
    return match.group(0) if match else ""


def seccion_tiene_datos_utiles(seccion):
    if not seccion.strip():
        return False

    texto = seccion.lower()

    frases_negativas = [
        "no se dispone de datos específicos",
        "no se dispone de información directa",
        "no hay datos específicos",
        "no hay datos directos",
        "no se han encontrado datos específicos",
        "no se cuenta con datos específicos",
        "no es posible estimar",
        "no es posible analizar",
        "no se puede realizar un análisis",
        "no existen datos",
        "no se encontró información",
        "no están disponibles",
        "no puede considerarse representativo",
        "no son representativos",
        "no se debe usar como representativo",
    ]

    negativas = sum(1 for frase in frases_negativas if frase in texto)

    # Si la sección está dominada por ausencia de datos, no cuenta.
    if negativas >= 1:
        # Permitimos secciones mixtas solo si aportan cifras claras del territorio.
        tiene_cifras = bool(re.search(r"\d+[.,]?\d*", texto))
        menciona_dato_util = any(palabra in texto for palabra in [
            "población total",
            "renta neta media",
            "coste laboral",
            "número total de empresas",
            "locales",
            "tasa de paro",
            "edad media",
            "porcentaje",
            "empresas registradas",
        ])

        if not (tiene_cifras and menciona_dato_util and negativas <= 1):
            return False

    return True


def calcular_cobertura(resultado):
    informe = resultado.get("informe", "")

    pilares = {
        "mercado": 1,
        "demografia": 2,
        "economia": 3,
        "laboral": 4,
        "empresas": 5,
        "actividad_empresarial": 6,
    }

    if "sector_negocio" in resultado.get("pilares", []):
        pilares["sector_negocio"] = 7

    if "turismo" in resultado.get("pilares", []):
        pilares["turismo"] = 8 if "sector_negocio" in resultado.get("pilares", []) else 7

    detalle = {}
    puntuacion_total = 0
    puntuacion_maxima = len(pilares) * 2

    for pilar, numero in pilares.items():
        seccion = extraer_seccion(informe, numero)
        puntuacion = puntuar_seccion(seccion)

        detalle[pilar] = puntuacion
        puntuacion_total += puntuacion

    porcentaje = round((puntuacion_total / puntuacion_maxima) * 100, 2) if puntuacion_maxima else 0

    if porcentaje >= 80:
        nivel = "ALTO"
    elif porcentaje >= 50:
        nivel = "MEDIO"
    else:
        nivel = "BAJO"

    return {
        "porcentaje": porcentaje,
        "nivel": nivel,
        "puntuacion_total": puntuacion_total,
        "puntuacion_maxima": puntuacion_maxima,
        "detalle_pilares": detalle,
    }
    
def generar_alerta_cobertura(cobertura):
    porcentaje = cobertura.get("porcentaje", 0)

    if porcentaje < 15:
        return (
            "🚨 Cobertura estadística muy baja\n\n"
            "No se dispone de información suficiente para generar un informe territorial "
            "representativo con los datos recuperados del INE.\n\n"
            "El resultado debe interpretarse únicamente como una salida preliminar con "
            "fuertes limitaciones."
        )

    if porcentaje < 30:
        return (
            "⚠️ Cobertura estadística baja\n\n"
            "El territorio solicitado presenta poca información útil en los datos recuperados. "
            "El informe puede contener apartados incompletos o basados en datos generales."
        )

    if porcentaje < 50:
        return (
            "⚠️ Cobertura estadística limitada\n\n"
            "Se han recuperado algunos datos útiles, pero la caracterización territorial "
            "no es suficientemente completa para extraer conclusiones sólidas."
        )

    return None

def puntuar_seccion(seccion):
    """
    Devuelve:
    2 = datos útiles y específicos del territorio
    1 = datos parciales, generales o relacionados
    0 = sin datos útiles o sin datos específicos del territorio
    """

    if not seccion.strip():
        return 0

    texto = seccion.lower()

    frases_fuertes_sin_datos = [
        "no se dispone de datos específicos",
        "no hay datos específicos",
        "no se cuenta con datos específicos",
        "no se encontraron datos específicos",
        "no existen datos específicos",
        "no se dispone de datos concretos",
        "no se dispone de información específica",
        "no se dispone de información directa",
        "no existen datos",
        "no se cuenta con datos",
        "no es posible ofrecer un análisis",
        "no es posible caracterizar",
        "no es posible evaluar",
        "no se puede evaluar",
        "no se puede estimar",
        "no se puede identificar",
        "no es posible extraer conclusiones sólidas",
        "no permiten caracterizar",
    ]

    frases_otro_territorio = [
        "otras provincias",
        "otros municipios",
        "otros territorios",
        "municipios distintos",
        "provincias distintas",
        "territorios distintos",
        "no representan",
        "no representa",
        "no representativo",
        "no debe extrapolarse",
        "no deben extrapolarse",
        "no deben considerarse representativos",
        "no puede considerarse representativo",
        "corresponden a otras localidades",
        "corresponde a otras localidades",
        "corresponden a otros territorios",
        "corresponde a otros territorios",
        "corresponden a niveles nacional",
        "corresponden a nivel nacional",
        "a nivel nacional",
        "promedios nacionales",
        "total nacional",
        "datos nacionales",
    ]

    frases_parciales = [
        "datos generales",
        "información parcial",
        "información disponible es parcial",
        "datos parciales",
        "no suficientemente detallados",
        "no suficientemente desagregados",
        "sin desglose",
        "sin desagregación",
        "no permite precisar",
        "no permite estimar",
        "limitado",
        "limitada",
        "debe interpretarse con cautela",
        "deben interpretarse con cautela",
    ]

    indicadores_utiles = [
        "población total",
        "habitantes",
        "censo",
        "edad media",
        "menor de 18",
        "menores de 18",
        "mayor de 65",
        "mayores de 65",
        "hogares unipersonales",
        "tamaño medio del hogar",
        "renta neta media",
        "renta media",
        "renta neta media por hogar",
        "renta neta media por persona",
        "coste laboral",
        "coste salarial",
        "tasa de paro",
        "desempleo",
        "paro",
        "empleo",
        "número total de empresas",
        "total de empresas",
        "empresas registradas",
        "sociedades mercantiles",
        "sociedades de responsabilidad limitada",
        "sociedades anónimas",
        "sociedades anonimas",
        "locales",
        "sector servicios",
        "cifra de negocio",
        "personal ocupado",
        "viajeros",
        "pernoctaciones",
        "ocupación hotelera",
        "plazas hoteleras",
        "establecimientos hoteleros",
    ]

    num_frases_sin_datos = sum(
        1 for frase in frases_fuertes_sin_datos if frase in texto
    )

    num_otro_territorio = sum(
        1 for frase in frases_otro_territorio if frase in texto
    )

    num_parciales = sum(
        1 for frase in frases_parciales if frase in texto
    )

    tiene_numeros = bool(re.search(r"\d+[.,]?\d*", texto))
    tiene_indicador = any(palabra in texto for palabra in indicadores_utiles)

    # Caso claro: la sección dice explícitamente que no hay datos del territorio.
    if num_frases_sin_datos >= 2:
        return 0

    # Caso claro: hay datos, pero son de otro territorio o nivel nacional.
    if num_otro_territorio >= 1:
        if num_frases_sin_datos >= 1:
            return 0
        return 1

    # Caso mixto: menciona ausencia de datos, aunque haya algún indicador suelto.
    if num_frases_sin_datos == 1:
        return 1 if tiene_numeros and tiene_indicador else 0

    # Caso parcial: datos generales o poco desagregados.
    if num_parciales >= 1:
        return 1 if tiene_numeros and tiene_indicador else 0

    # Caso positivo: hay cifras e indicadores útiles.
    if tiene_numeros and tiene_indicador:
        return 2

    return 0

def extraer_fuentes(resultado):
    fuentes = []
    vistos = set()

    resultados = resultado.get("resultados_por_pilar", {})

    for pilar, contenido in resultados.items():
        if isinstance(contenido, dict):
            contenidos = [contenido]
        elif isinstance(contenido, list):
            contenidos = contenido
        else:
            contenidos = []

        for item in contenidos:
            contexto_llm = item.get("contexto_llm", {})
            datos = contexto_llm.get("datos_recuperados", [])

            for bloque in datos:
                id_tabla = bloque.get("id_tabla")
                operacion = bloque.get("operacion")
                fuente = bloque.get("fuente")

                clave = (id_tabla, fuente)

                if clave in vistos:
                    continue

                vistos.add(clave)

                fuentes.append({
                    "pilar": pilar,
                    "id_tabla": id_tabla,
                    "operacion": operacion,
                    "fuente": fuente,
                })

    return fuentes


def construir_txt_informe(resultado, cobertura):
    informe = resultado.get("informe", "")

    lineas = []

    lineas.append("INFORME PRELIMINAR DE VIABILIDAD TERRITORIAL")
    lineas.append("=" * 80)
    lineas.append("")
    lineas.append(f"Negocio: {resultado.get('negocio')}")
    lineas.append(f"Territorio: {resultado.get('territorio')}")
    lineas.append(f"Cobertura: {cobertura['porcentaje']}%")
    lineas.append(f"Nivel de fiabilidad: {cobertura['nivel']}")
    
    alerta = generar_alerta_cobertura(cobertura)

    if alerta:
        lineas.append("")
        lineas.append("ALERTA DE COBERTURA")
        lineas.append("-" * 80)
        lineas.append(alerta.replace("🚨 ", "").replace("⚠️ ", ""))
    
    lineas.append(
        f"Puntuación de datos: {cobertura['puntuacion_total']}/"
        f"{cobertura['puntuacion_maxima']}"
    )
        
    lineas.append("")
    lineas.append("Detalle por pilares:")

    for pilar, puntos in cobertura.get("detalle_pilares", {}).items():
        lineas.append(f"- {pilar}: {puntos}/2")
    lineas.append("")
    lineas.append("=" * 80)
    lineas.append("INFORME")
    lineas.append("=" * 80)
    lineas.append("")
    lineas.append(informe)
    lineas.append("")
    lineas.append("=" * 80)
    lineas.append("FUENTES Y TABLAS RECUPERADAS POR EL SISTEMA")
    lineas.append("=" * 80)
    lineas.append("")
    lineas.append(
        "Nota: las tablas listadas son las recuperadas durante el proceso de búsqueda. "
        "Algunas pueden corresponder a ámbitos nacionales, autonómicos o territorios distintos, "
        "por lo que deben interpretarse junto con las limitaciones indicadas en el informe."
    )
    lineas.append("")

    fuentes = extraer_fuentes(resultado)

    if not fuentes:
        lineas.append("No se han encontrado fuentes asociadas.")

    for fuente in fuentes:
        lineas.append("")
        lineas.append(f"Pilar: {fuente.get('pilar')}")
        lineas.append(f"ID tabla: {fuente.get('id_tabla')}")
        lineas.append(f"Operación: {fuente.get('operacion')}")
        lineas.append(f"URL operación INE: {fuente.get('fuente')}")

    return ajustar_lineas_txt("\n".join(lineas), ancho=100)


def guardar_informe_txt_temporal(resultado, cobertura):
    negocio = limpiar_nombre_archivo(resultado.get("negocio", "negocio"))
    territorio = limpiar_nombre_archivo(resultado.get("territorio", "territorio"))

    nombre_archivo = f"informe_{negocio}_{territorio}.txt"
    ruta = os.path.join(tempfile.gettempdir(), nombre_archivo)

    contenido = construir_txt_informe(resultado, cobertura)

    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write(contenido)

    return ruta

# ============================================================
# HANDLERS TELEGRAM
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = (
        "Hola!! Soy el asistente de generación automática de informes preliminares de viabilidad territorial basado en datos del INE.\n\n"
        "Indica un negocio y un territorio para generar un informe basado en datos oficiales del Instituto Nacional de Estadística (INE).\n\n"
        "Ejemplos:\n"
        "- Quiero abrir un gimnasio en Madrid\n"
        "- Hazme un estudio preliminar para una cafetería en Toledo\n"
        "- Estoy pensando en montar un hotel en Málaga\n"
        "- Quiero abrir una academia en Murcia\n\n"
        "El informe puede incluir:\n"
        "       - Población\n"
        "       - Demografía\n"
        "       - Economía\n"
        "       - Mercado Laboral\n"
        "       - Empresas\n"
        "       - Turismo (si aplica)\n"
        "\n\nTodas las respuestas se generan exclusivamente a partir de datos recuperados del INE. El sistema no inventa datos ni realiza estimaciones cuando la información no está disponible.\n"
        "⚠️ No analiza competencia, demanda, precios ni rentabilidad"
    )

    await update.message.reply_text(mensaje)


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = (
        "Comandos disponibles:\n\n"
        "/start - Iniciar el bot\n"
        "/help - Mostrar ayuda\n\n"
        "Formato recomendado:\n"
        "- Quiero abrir un [negocio] en [territorio]\n"
        "- Hazme un estudio preliminar para una [actividad] en [territorio]\n\n"
        "Ejemplos:\n"
        "- Quiero abrir un gimnasio en Madrid\n"
        "- Hazme un estudio preliminar para una cafetería en Toledo\n"
        "- Estoy pensando en montar un hotel en Málaga\n\n"
        "El bot no decide si el negocio será rentable. Genera una aproximación preliminar "
        "basada únicamente en datos estadísticos recuperados del INE."
    )

    await update.message.reply_text(mensaje)

def interpretar_puntuacion_pilar(puntos):
    if puntos == 2:
        return "✅ 2/2 datos útiles"
    if puntos == 1:
        return "⚠️ 1/2 datos parciales o relacionados"
    return "❌ 0/2 sin datos suficientes"

NOMBRES_PILARES = {
    "mercado": "Contexto poblacional",
    "demografia": "Perfil demográfico",
    "economia": "Situación económica",
    "laboral": "Situación laboral",
    "empresas": "Tejido empresarial",
    "actividad_empresarial": "Actividad empresarial",
    "sector_negocio": "Sector específico del negocio",
    "turismo": "Turismo",
}


def valoracion_pilar(puntos):
    if puntos == 2:
        return "🟢 Favorable"
    if puntos == 1:
        return "🟡 Intermedio"
    return "🔴 Limitado"


def justificacion_pilar(pilar, puntos):
    justificaciones = {
        "mercado": {
            2: "Existe información suficiente sobre población y tamaño general del territorio.",
            1: "La información poblacional es parcial o no permite caracterizar completamente el mercado territorial.",
            0: "No se han recuperado datos suficientes sobre población o contexto territorial."
        },
        "demografia": {
            2: "La estructura de edad, hogares y composición demográfica está bien caracterizada.",
            1: "Existen indicadores demográficos útiles, aunque no permiten segmentar con precisión el público objetivo.",
            0: "No se han recuperado datos demográficos suficientes."
        },
        "economia": {
            2: "La renta y capacidad económica del territorio están correctamente representadas.",
            1: "La información económica es parcial o no está suficientemente desagregada.",
            0: "No se han recuperado indicadores económicos suficientes."
        },
        "laboral": {
            2: "Se dispone de información sobre empleo, paro o costes laborales del territorio.",
            1: "Los indicadores laborales son parciales o generales.",
            0: "No se han recuperado indicadores laborales suficientes."
        },
        "empresas": {
            2: "El volumen y estructura empresarial del territorio están correctamente caracterizados.",
            1: "La información empresarial es parcial o poco específica.",
            0: "No se han recuperado datos suficientes sobre tejido empresarial."
        },
        "actividad_empresarial": {
            2: "Se identifican sectores y actividad económica predominante del territorio.",
            1: "Existen indicadores de actividad económica relacionados, pero incompletos.",
            0: "No se han recuperado indicadores suficientes sobre actividad empresarial."
        },
        "turismo": {
            2: "Se dispone de indicadores turísticos relevantes para el territorio.",
            1: "La información turística recuperada es parcial.",
            0: "No se han recuperado datos turísticos suficientes."
        }
    }

    return justificaciones.get(pilar, {}).get(
        puntos,
        "No hay información suficiente para valorar este pilar."
    )

def construir_tabla_valoracion(cobertura):
    detalle = cobertura.get("detalle_pilares", {})

    lineas = []
    lineas.append("## Valoración territorial por pilares")
    lineas.append("")
    lineas.append("| Pilar | Valoración | Puntuación | Justificación |")
    lineas.append("|---|---|---:|---|")

    for pilar, puntos in detalle.items():
        nombre = NOMBRES_PILARES.get(pilar, pilar)
        valoracion = valoracion_pilar(puntos)
        justificacion = justificacion_pilar(pilar, puntos)

        lineas.append(
            f"| {nombre} | {valoracion} | {puntos}/2 | {justificacion} |"
        )

    lineas.append("")
    lineas.append(
        f"**Índice territorial global:** "
        f"{cobertura['puntuacion_total']}/{cobertura['puntuacion_maxima']} "
        f"({cobertura['porcentaje']}%)"
    )
    lineas.append("")
    lineas.append(f"**Nivel de fiabilidad:** {cobertura['nivel']}")

    return "\n".join(lineas)

def es_conversacion_no_valida(texto):
    texto = texto.lower().strip()

    mensajes_no_validos = [
        "hola",
        "buenas",
        "buenos dias",
        "buenos días",
        "buenas tardes",
        "buenas noches",
        "que tal",
        "qué tal",
        "gracias",
        "ok",
        "vale",
        "adios",
        "adiós",
    ]

    return texto in mensajes_no_validos

async def responder_pregunta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text.strip()
    chat_id = update.effective_chat.id

    if not texto_usuario:
        return
    
    if es_conversacion_no_valida(texto_usuario):
        await update.message.reply_text(
            "👋 Este chatbot está diseñado para generar informes preliminares "
            "de viabilidad territorial.\n\n"
            "Indica un negocio y un territorio. Por ejemplo:\n"
            "🏋️ Gimnasio en Madrid\n"
            "☕ Cafetería en Cantabria\n"
            "🏕️ Camping en Extremadura"
        )
        return

    negocio_pendiente = context.user_data.get("negocio_pendiente")
    territorio_pendiente = context.user_data.get("territorio_pendiente")

    if negocio_pendiente and not territorio_pendiente:
        texto_usuario = f"{negocio_pendiente} en {texto_usuario}"
        context.user_data.pop("negocio_pendiente", None)

    elif territorio_pendiente and not negocio_pendiente:
        texto_usuario = f"{texto_usuario} en {territorio_pendiente}"
        context.user_data.pop("territorio_pendiente", None)
    
    interpretacion_previa = interpretar_estudio_mercado(
        texto_usuario=texto_usuario,
        modelo_llm=MODELO_LLM
    )

    negocio_detectado = interpretacion_previa.get("negocio")
    territorio_detectado = interpretacion_previa.get("territorio")

    if territorio_detectado and not negocio_detectado:
        context.user_data["territorio_pendiente"] = territorio_detectado

        await update.message.reply_text(
            f"📍 He detectado el territorio: {territorio_detectado}\n\n"
            "¿Qué tipo de negocio quieres analizar?\n\n"
            "Ejemplo:\n"
            "🏋️ gimnasio\n"
            "☕ cafetería\n"
            "🏥 clínica de fisioterapia"
        )
        return

    if negocio_detectado and not territorio_detectado:
        context.user_data["negocio_pendiente"] = negocio_detectado

        await update.message.reply_text(
            f"🏢 He detectado el negocio: {negocio_detectado}\n\n"
            "¿En qué territorio quieres analizarlo?\n\n"
            "Ejemplo:\n"
            "Madrid\n"
            "Cantabria\n"
            "Castilla y León"
        )
        return

    if not negocio_detectado and not territorio_detectado:
        await update.message.reply_text(
            "⚠️ No he podido detectar un negocio y un territorio.\n\n"
            "Este chatbot genera informes preliminares de viabilidad territorial.\n\n"
            "Escribe algo como:\n"
            "🏋️ Gimnasio en Madrid\n"
            "☕ Cafetería en Cantabria\n"
            "🏕️ Camping en Extremadura"
        )
        return

    await context.bot.send_chat_action(
        chat_id=chat_id,
        action=ChatAction.TYPING,
    )

    await update.message.reply_text(
        "🔎 Solicitud recibida\n\n"
        f"🏢 Negocio detectado: {negocio_detectado}\n"
        f"📍 Territorio detectado: {territorio_detectado}\n\n"
        "📊 Buscando indicadores oficiales del INE...\n"
        "El informe se generará únicamente con los datos recuperados.\n\n"
        "⏳ Esto puede tardar unos segundos."
    )
    
    try:
        resultado = ejecutar_estudio_mercado(
            texto_usuario=texto_usuario,
            index=index,
            metadata=metadata,
            modelo_embeddings=modelo_embeddings,
            con=con_duckdb,
            tabla=NOMBRE_TABLA_DUCKDB,
            usar_llm=True,
            modelo_llm=MODELO_LLM,
            top_k=TOP_K_FINAL,
            limite_por_candidato=LIMITE_POR_CANDIDATO,
            score_minimo=SCORE_FINAL_MINIMO,
        )

        if resultado.get("error"):
            interpretacion = resultado.get("interpretacion", {})
            negocio = interpretacion.get("negocio")
            territorio = interpretacion.get("territorio")

            if territorio and not negocio:
                context.user_data["territorio_pendiente"] = territorio

                await update.message.reply_text(
                    f"📍 He detectado el territorio: {territorio}\n\n"
                    "¿Qué tipo de negocio quieres analizar?\n\n"
                    "Ejemplo:\n"
                    "🏋️ gimnasio\n"
                    "☕ cafetería\n"
                    "🏥 clínica de fisioterapia"
                )
                return

            if negocio and not territorio:
                context.user_data["negocio_pendiente"] = negocio

                await update.message.reply_text(
                    f"🏢 He detectado el negocio: {negocio}\n\n"
                    "¿En qué territorio quieres analizarlo?\n\n"
                    "Ejemplo:\n"
                    "Madrid\n"
                    "Cantabria\n"
                    "Castilla y León"
                )
                return

            await update.message.reply_text(
                "⚠️ No he podido detectar un negocio y un territorio.\n\n"
                "Este chatbot solo genera informes preliminares de viabilidad territorial.\n\n"
                "Escribe algo como:\n"
                "🏋️ Gimnasio en Madrid\n"
                "☕ Cafetería en Cantabria\n"
                "🏕️ Camping en Extremadura"
            )
            return

        cobertura = calcular_cobertura(resultado)
        
        escribir_log_telegram(
            path_log=path_log_telegram,
            chat_id=chat_id,
            pregunta_usuario=texto_usuario,
            resultado=resultado,
            cobertura=cobertura
        )

        escribir_log_resultados_telegram(
            path_resultados=path_resultados_telegram,
            chat_id=chat_id,
            pregunta_usuario=texto_usuario,
            resultado=resultado,
            cobertura=cobertura
        )

        resumen_visual = (
            "📊 Informe preliminar de viabilidad territorial generado\n\n"
            f"🏢 Negocio: {resultado.get('negocio')}\n"
            f"📍 Territorio: {resultado.get('territorio')}\n"
            f"✅ Cobertura: {cobertura['porcentaje']}%\n"
            f"📌 Nivel de fiabilidad: {cobertura['nivel']}\n"
            f"📚 Puntuación de datos: {cobertura['puntuacion_total']}/{cobertura['puntuacion_maxima']}\n"
            "\nDetalle por pilares:\n"
            + "\n".join(
                f"- {pilar}: {interpretar_puntuacion_pilar(puntos)}"
                for pilar, puntos in cobertura.get("detalle_pilares", {}).items()
            )
            + "\n\n📄 A continuación se muestra el informe preliminar generado con datos oficiales del INE."
        )
        

        await update.message.reply_text(resumen_visual)

        alerta = generar_alerta_cobertura(cobertura)

        if alerta:
            await update.message.reply_text(alerta)

        informe = resultado.get("informe") or "No se ha podido generar el informe final."

        valoracion = extraer_seccion(informe, 10)

        if valoracion:
            valoracion = formatear_informe_telegram(valoracion)

            mensaje_valoracion = (
                "🧭 Valoración territorial preliminar\n\n"
                f"{valoracion}\n\n"
                "📎 Se adjunta el informe completo para consultar el detalle de los indicadores y fuentes utilizadas."
            )

            for parte in dividir_mensaje(mensaje_valoracion):
                await update.message.reply_text(parte)
        else:
            await update.message.reply_text(
                "🧭 No se ha podido extraer automáticamente la valoración territorial preliminar.\n\n"
                "📎 Se adjunta el informe completo para consultar el detalle."
            )

        ruta_txt = guardar_informe_txt_temporal(resultado, cobertura)

        with open(ruta_txt, "rb") as documento:
            await update.message.reply_document(
                document=InputFile(documento, filename=os.path.basename(ruta_txt)),
                caption="📁 Informe preliminar de viabilidad territorial (TXT)"
            )
    except Exception:
        print("[ERROR] Fallo procesando estudio de mercado:")
        traceback.print_exc()

        await update.message.reply_text(
            "Se ha producido un error al generar el estudio preliminar. "
            "Revisa la consola del sistema para ver el detalle."
        )


# ============================================================
# CARGA DEL SISTEMA
# ============================================================

def cargar_sistema():
    """
    Carga una única vez los recursos pesados del sistema:
    - índice FAISS
    - metadata FAISS
    - modelo de embeddings
    - conexión DuckDB
    """
    global index, metadata, modelo_embeddings, con_duckdb, path_log_telegram, path_resultados_telegram
    print("==============================================")
    print(" CARGANDO ASISTENTE DE ESTUDIOS DE MERCADO")
    print("==============================================")

    index = cargar_indice_faiss(INPUT_INDEX)
    metadata = cargar_metadata_faiss(INPUT_METADATA)
    modelo_embeddings = cargar_modelo_embeddings(MODELO_EMBEDDINGS)
    con_duckdb = conectar_duckdb(INPUT_DUCKDB)
    path_log_telegram = crear_fichero_log_telegram()
    print(f"[INFO] Log de Telegram creado en: {path_log_telegram}")
    path_resultados_telegram = crear_fichero_resultados_telegram()
    print(f"[INFO] Log resumido de resultados creado en: {path_resultados_telegram}")

    print("==============================================")
    print("[OK] Sistema cargado correctamente")
    print("==============================================")


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        raise RuntimeError(
            "No se ha encontrado TELEGRAM_BOT_TOKEN. "
            "Configúralo antes de ejecutar el bot."
        )

    cargar_sistema()

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", ayuda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder_pregunta))

    print("[INFO] Bot de Telegram del asistente de mercado iniciado con polling.")
    print("[INFO] Pulsa Ctrl+C para detenerlo.")

    app.run_polling()


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("\n[INFO] Bot detenido manualmente por el usuario.")

    finally:
        try:
            if con_duckdb:
                con_duckdb.close()
                print("[INFO] Conexión DuckDB cerrada.")
        except Exception:
            pass

        print("[INFO] Sistema finalizado correctamente.")
