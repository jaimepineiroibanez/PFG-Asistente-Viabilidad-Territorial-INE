import os
import json
import re

from configuracion.config_ine import MODELO_LLM
from codigo.utilidades.utils_ine import normalizar_texto


# ============================================================
# INTERPRETACIÓN DE CONSULTAS DEL USUARIO
# ============================================================

TERRITORIOS_CONOCIDOS = [
    # Comunidades autónomas
    "Andalucía",
    "Aragón",
    "Asturias",
    "Illes Balears",
    "Baleares",
    "Canarias",
    "Cantabria",
    "Castilla y León",
    "Castilla-La Mancha",
    "Cataluña",
    "Comunitat Valenciana",
    "Comunidad Valenciana",
    "Extremadura",
    "Galicia",
    "Comunidad de Madrid",
    "Madrid",
    "Región de Murcia",
    "Murcia",
    "Navarra",
    "País Vasco",
    "La Rioja",
    "Ceuta",
    "Melilla",

    # Provincias / ciudades usadas en pruebas
    "Málaga",
    "Sevilla",
    "Granada",
    "Valencia",
    "Tarragona",
    "Toledo",
    "Cádiz",
    "Teruel",
    "Cuenca",
    "Ciudad Real",
    "Benavente",
    "Alcalá de Henares",
    "Leganés",
    "Fuenlabrada",
]


NEGOCIOS_CONOCIDOS = [
    "gimnasio",
    "cafetería",
    "cafeteria",
    "restaurante",
    "bar",
    "hotel",
    "alojamiento turístico",
    "alojamiento turistico",
    "academia",
    "academia de formación",
    "academia de formacion",
    "guardería",
    "guarderia",
    "centro infantil",
    "tienda",
    "comercio",
    "supermercado",
    "clínica",
    "clinica",
    "consultoría",
    "consultoria",
    "despacho",
    "residencia de estudiantes",
    "negocio turístico",
    "negocio turistico",
]


def construir_prompt_interpretacion_estudio(texto_usuario):
    return f"""
Eres un interpretador para un sistema inteligente de generación automática de informes preliminares de viabilidad territorial utilizando datos oficiales del Instituto Nacional de Estadística (INE).

Tu tarea NO es responder al usuario.
Tu tarea NO es analizar la viabilidad del negocio.
Tu tarea NO es decidir si el negocio tendrá éxito.
Tu tarea NO es realizar un estudio de mercado.

Tu única función consiste en identificar:

1. El tipo de actividad económica o negocio.
2. El territorio sobre el que se desea generar el informe preliminar.

El informe posterior describirá el contexto territorial utilizando indicadores demográficos, económicos, laborales, empresariales y turísticos disponibles en el INE.

Devuelve exclusivamente un objeto JSON válido.
No uses Markdown.
No uses bloques de código.
No escribas explicaciones antes ni después del JSON.
La primera letra de tu respuesta debe ser {{ y la última debe ser }}.

Reglas:
- Mantén el idioma español.
- El campo "negocio" debe ser breve: por ejemplo "gimnasio", "cafetería", "hotel", "academia".
- El campo "territorio" debe contener el municipio, provincia o comunidad autónoma mencionada.
- No inventes territorio si no aparece en la frase.
- No inventes negocio si no aparece en la frase.
- Si falta el negocio o falta el territorio, marca "necesita_aclaracion" como true.
- Si falta el negocio, pregunta qué tipo de negocio desea analizar.
- Si falta el territorio, pregunta en qué municipio, provincia o comunidad autónoma desea realizar el estudio.
- Si aparecen varios territorios, usa el territorio principal asociado al negocio.
- Si aparecen varios negocios, usa el primero mencionado.
- No incluyas datos del INE, cifras, años ni conclusiones.

Formato obligatorio:
{{
  "texto_original": "...",
  "negocio": null,
  "territorio": null,
  "necesita_aclaracion": false,
  "pregunta_aclaracion": null,
  "confianza": 0.0
}}

Ejemplos:

Usuario: Quiero abrir un gimnasio en Madrid
Respuesta:
{{
  "texto_original": "Quiero abrir un gimnasio en Madrid",
  "negocio": "gimnasio",
  "territorio": "Madrid",
  "necesita_aclaracion": false,
  "pregunta_aclaracion": null,
  "confianza": 0.95
}}

Usuario: Hazme un estudio preliminar para una cafetería en Toledo
Respuesta:
{{
  "texto_original": "Hazme un estudio preliminar para una cafetería en Toledo",
  "negocio": "cafetería",
  "territorio": "Toledo",
  "necesita_aclaracion": false,
  "pregunta_aclaracion": null,
  "confianza": 0.95
}}

Usuario: Quiero hacer un informe preliminar de viabilidad territorial en Murcia
Respuesta:
{{
  "texto_original": "Quiero hacer un informe preliminar de viabilidad territorial en Murcia",
  "negocio": null,
  "territorio": "Murcia",
  "necesita_aclaracion": true,
  "pregunta_aclaracion": "¿Qué tipo de negocio desea analizar?",
  "confianza": 0.65
}}

Usuario: Quiero abrir una academia
Respuesta:
{{
  "texto_original": "Quiero abrir una academia",
  "negocio": "academia",
  "territorio": null,
  "necesita_aclaracion": true,
  "pregunta_aclaracion": "¿En qué municipio, provincia o comunidad autónoma desea realizar el estudio?",
  "confianza": 0.65
}}

Frase del usuario:
{texto_usuario}
""".strip()


def interpretar_estudio_mercado_con_llm(texto_usuario, modelo_llm=MODELO_LLM):
    """
    Interpreta la petición del usuario usando un LLM.

    Devuelve un diccionario con:
    - texto_original
    - negocio
    - territorio
    - necesita_aclaracion
    - pregunta_aclaracion
    - confianza
    """
    try:
        from openai import OpenAI
    except ImportError:
        return interpretar_estudio_mercado_reglas(texto_usuario)

    api_key = os.getenv("API_KEY_INE_CHATBOT") or os.getenv("OPENAI_API_KEY")

    if not api_key:
        return interpretar_estudio_mercado_reglas(texto_usuario)

    client = OpenAI(api_key=api_key)
    prompt = construir_prompt_interpretacion_estudio(texto_usuario)

    try:
        response = client.responses.create(
            model=modelo_llm,
            input=prompt
        )

        texto = response.output_text.strip()
        interpretacion = json.loads(texto)

    except Exception as e:
        interpretacion = interpretar_estudio_mercado_reglas(texto_usuario)
        interpretacion["error_llm"] = str(e)
        return interpretacion

    return validar_interpretacion_estudio(texto_usuario, interpretacion)


def interpretar_estudio_mercado_reglas(texto_usuario):
    """
    Interpretador de respaldo sin LLM.

    Es menos flexible que el LLM, pero permite que el sistema siga funcionando
    si no hay API key o si falla la llamada a OpenAI.
    """
    texto_norm = normalizar_texto(texto_usuario)

    negocio = extraer_negocio_por_reglas(texto_norm)
    territorio = extraer_territorio_por_reglas(texto_norm)

    interpretacion = {
        "texto_original": texto_usuario,
        "negocio": negocio,
        "territorio": territorio,
        "necesita_aclaracion": False,
        "pregunta_aclaracion": None,
        "confianza": 0.75 if negocio and territorio else 0.45
    }

    return validar_interpretacion_estudio(texto_usuario, interpretacion)


def extraer_negocio_por_reglas(texto_norm):
    for negocio in sorted(NEGOCIOS_CONOCIDOS, key=len, reverse=True):
        negocio_norm = normalizar_texto(negocio)
        if negocio_norm in texto_norm:
            return negocio

    patrones = [
        r"abrir\s+(?:un|una)\s+([a-záéíóúñü\s]+?)\s+en\s+",
        r"montar\s+(?:un|una)\s+([a-záéíóúñü\s]+?)\s+en\s+",
        r"crear\s+(?:un|una)\s+([a-záéíóúñü\s]+?)\s+en\s+",
        r"para\s+(?:un|una)\s+([a-záéíóúñü\s]+?)\s+en\s+",
    ]

    for patron in patrones:
        match = re.search(patron, texto_norm)
        if match:
            candidato = match.group(1).strip()
            candidato = limpiar_candidato_negocio(candidato)
            if candidato:
                return candidato

    return None


def extraer_territorio_por_reglas(texto_norm):
    for territorio in sorted(TERRITORIOS_CONOCIDOS, key=len, reverse=True):
        territorio_norm = normalizar_texto(territorio)
        if territorio_norm in texto_norm:
            return territorio

    patrones = [
        r"\ben\s+([a-záéíóúñü\s]+)$",
        r"\bde\s+([a-záéíóúñü\s]+)$",
    ]

    for patron in patrones:
        match = re.search(patron, texto_norm)
        if match:
            candidato = match.group(1).strip()
            candidato = limpiar_candidato_territorio(candidato)
            if candidato:
                return formatear_territorio(candidato)

    return None


def limpiar_candidato_negocio(texto):
    palabras_ruido = [
        "negocio",
        "empresa",
        "estudio",
        "preliminar",
        "mercado",
        "analisis",
        "análisis",
    ]

    texto = texto.strip(" .,;:¿?¡!")

    for palabra in palabras_ruido:
        texto = re.sub(rf"\b{palabra}\b", "", texto, flags=re.IGNORECASE)

    texto = re.sub(r"\s+", " ", texto).strip()
    return texto or None


def limpiar_candidato_territorio(texto):
    cortes = [
        "para abrir",
        "para montar",
        "para crear",
        "sobre",
        "con datos",
    ]

    for corte in cortes:
        if corte in texto:
            texto = texto.split(corte)[0]

    texto = texto.strip(" .,;:¿?¡!")
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto or None


def formatear_territorio(texto):
    excepciones = {
        "madrid": "Madrid",
        "murcia": "Murcia",
        "valencia": "Valencia",
        "andalucia": "Andalucía",
        "aragon": "Aragón",
        "asturias": "Asturias",
        "cantabria": "Cantabria",
        "galicia": "Galicia",
        "pais vasco": "País Vasco",
        "la rioja": "La Rioja",
    }

    texto_norm = normalizar_texto(texto)
    if texto_norm in excepciones:
        return excepciones[texto_norm]

    return " ".join(p.capitalize() for p in texto.split())


def validar_interpretacion_estudio(texto_usuario, interpretacion):
    """
    Normaliza y valida la salida del LLM o del parser por reglas.
    """
    if not isinstance(interpretacion, dict):
        interpretacion = {}

    negocio = interpretacion.get("negocio")
    territorio = interpretacion.get("territorio")

    if isinstance(negocio, str):
        negocio = negocio.strip()
        if not negocio:
            negocio = None

    if isinstance(territorio, str):
        territorio = territorio.strip()
        if not territorio:
            territorio = None

    necesita_aclaracion = False
    pregunta_aclaracion = None

    if not negocio and not territorio:
        necesita_aclaracion = True
        pregunta_aclaracion = (
            "¿Qué tipo de negocio desea analizar y en qué municipio, "
            "provincia o comunidad autónoma desea realizar el estudio?"
        )
    elif not negocio:
        necesita_aclaracion = True
        pregunta_aclaracion = "¿Qué tipo de negocio desea analizar?"
    elif not territorio:
        necesita_aclaracion = True
        pregunta_aclaracion = (
            "¿En qué municipio, provincia o comunidad autónoma desea realizar el estudio?"
        )

    try:
        confianza = float(interpretacion.get("confianza", 0.0))
    except Exception:
        confianza = 0.0

    confianza = max(0.0, min(confianza, 1.0))

    return {
        "texto_original": texto_usuario,
        "negocio": negocio,
        "territorio": territorio,
        "necesita_aclaracion": necesita_aclaracion,
        "pregunta_aclaracion": pregunta_aclaracion,
        "confianza": confianza,
    }
    
def interpretar_estudio_mercado(texto_usuario, modelo_llm=MODELO_LLM):
    """
    Punto de entrada principal del interpretador.

    Primero intenta usar el LLM.
    Si no hay API key, no está instalada la librería OpenAI
    o falla la respuesta, se usa el sistema por reglas.
    """
    return interpretar_estudio_mercado_con_llm(
        texto_usuario=texto_usuario,
        modelo_llm=modelo_llm
    )

