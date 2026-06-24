import json
import os
import argparse
from collections import  Counter
from tqdm import tqdm
import re
import unicodedata


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_JSONL_API = "./datos/normalizados/dataset_ine_normalizado_api.jsonl"
INPUT_JSONL_HREF = "./datos/normalizados/dataset_ine_normalizado_href.jsonl"

OUTPUT_JSONL = "./datos/semanticos/dataset_ine_semantico_por_tabla.jsonl"
OUTPUT_RESUMEN = "./datos/semanticos/resumen_dataset_semantico_por_tabla.json"
OUTPUT_ERRORES = "./datos/semanticos/errores_dataset_semantico_por_tabla.jsonl"
MAX_SERIES_EN_TEXTO = 200
MAX_UNIDADES_EN_TEXTO = 20
MAX_PERIODOS_EN_TEXTO = 30


# ============================================================
# UTILIDADES
# ============================================================

def asegurar_carpeta(path):
    carpeta = os.path.dirname(path)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)


def borrar_si_existe(path):
    if os.path.exists(path):
        os.remove(path)


def guardar_json(path, data):
    asegurar_carpeta(path)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def append_jsonl(path, data):
    asegurar_carpeta(path)
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False) + "\n")


def limpiar_texto(valor):
    if valor is None:
        return None

    texto = str(valor).strip()
    texto = " ".join(texto.split())
    return texto if texto else None


def convertir_a_int(valor):
    if valor is None:
        return None

    try:
        return int(valor)
    except Exception:
        return None


def limitar_lista_valores(valores, max_items):
    valores_limpios = []

    for valor in valores:
        valor_limpio = limpiar_texto(valor)
        if valor_limpio and valor_limpio not in valores_limpios:
            valores_limpios.append(valor_limpio)

        if len(valores_limpios) >= max_items:
            break

    return valores_limpios


def actualizar_min_max(actual_min, actual_max, valor):
    valor_int = convertir_a_int(valor)

    if valor_int is None:
        return actual_min, actual_max

    if actual_min is None or valor_int < actual_min:
        actual_min = valor_int

    if actual_max is None or valor_int > actual_max:
        actual_max = valor_int

    return actual_min, actual_max


# ============================================================
# EXTRACCIÓN DE POSIBLES DIMENSIONES DESDE NOMBRE_SERIE
# ============================================================

def normalizar_texto_para_vocabulario(texto):
    if texto is None:
        return ""

    texto = str(texto).lower().strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9ñáéíóúü\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


STOPWORDS_VOCABULARIO = {
    "total", "nacional", "dato", "datos", "tabla", "serie", "periodo",
    "ano", "anos", "año", "años", "por", "para", "con", "sin", "segun",
    "según", "del", "de", "la", "el", "los", "las", "una", "uno", "un",
    "y", "o", "en", "al", "lo", "su", "sus", "es", "son", "tipo",
    "numero", "número", "valor", "base"
}


def extraer_tokens_vocabulario(texto):
    texto_norm = normalizar_texto_para_vocabulario(texto)

    tokens = []

    for token in texto_norm.split():
        if len(token) <= 3:
            continue
        if token in STOPWORDS_VOCABULARIO:
            continue
        if token.isdigit():
            continue

        tokens.append(token)

    return tokens

def detectar_palabras_clave_series(nombre_serie):
    """
    Extrae términos útiles para enriquecer el texto semántico:
    territorios, sexo, edad, total nacional, etc.
    No pretende ser perfecto, solo añadir señales al documento FAISS.
    """
    nombre = limpiar_texto(nombre_serie)
    if not nombre:
        return []

    nombre_lower = nombre.lower()
    claves = []

    territorios = [
        "total nacional", "andalucía", "aragon", "aragón", "asturias",
        "balears", "baleares", "canarias", "cantabria", "castilla y león",
        "castilla-la mancha", "castilla la mancha", "cataluña", "cataluna",
        "comunitat valenciana", "valencia", "extremadura", "galicia",
        "madrid", "murcia", "navarra", "país vasco", "pais vasco",
        "rioja", "ceuta", "melilla"
    ]

    for territorio in territorios:
        if territorio in nombre_lower:
            claves.append(territorio)

    if "hombres" in nombre_lower or "varones" in nombre_lower:
        claves.append("hombres")

    if "mujeres" in nombre_lower:
        claves.append("mujeres")

    if "edad" in nombre_lower or "años" in nombre_lower or "anos" in nombre_lower:
        claves.append("edad")
        claves.append("grupos de edad")

    if "nacimiento" in nombre_lower or "nacimientos" in nombre_lower:
        claves.append("nacimientos")

    if "defuncion" in nombre_lower or "defunción" in nombre_lower or "defunciones" in nombre_lower:
        claves.append("defunciones")

    if "matrimonio" in nombre_lower or "matrimonios" in nombre_lower:
        claves.append("matrimonios")

    return claves


# ============================================================
# ACUMULACIÓN POR TABLA
# ============================================================

def crear_registro_tabla(fila, fuente_datos):
    return {
        "id_tabla": limpiar_texto(fila.get("id_tabla")),
        "dato_operacion": limpiar_texto(fila.get("dato_operacion")),
        "titulo_tabla": limpiar_texto(fila.get("titulo_tabla")),
        "href_tabla": limpiar_texto(fila.get("href_tabla")),
        "url_api": limpiar_texto(fila.get("url_api")),
        "fuentes_datos": set([fuente_datos]),
        "total_observaciones": 0,
        "anyo_min": None,
        "anyo_max": None,
        "series_counter": Counter(),
        "unidades_counter": Counter(),
        "periodos_counter": Counter(),
        "palabras_clave_counter": Counter(),
        "vocabulario_counter": Counter()
    }


def actualizar_registro_tabla(registro, fila, fuente_datos):
    registro["fuentes_datos"].add(fuente_datos)
    registro["total_observaciones"] += 1

    anyo = fila.get("anyo")
    registro["anyo_min"], registro["anyo_max"] = actualizar_min_max(
        registro["anyo_min"],
        registro["anyo_max"],
        anyo
    )

    nombre_serie = limpiar_texto(fila.get("nombre_serie"))
    textos_vocabulario = [
        fila.get("dato_operacion"),
        fila.get("titulo_tabla"),
        fila.get("nombre_serie"),
        fila.get("unidad"),
        fila.get("periodo")
    ]

    for texto in textos_vocabulario:
        for token in extraer_tokens_vocabulario(texto):
            registro["vocabulario_counter"][token] += 1
    if nombre_serie:
        registro["series_counter"][nombre_serie] += 1

        for clave in detectar_palabras_clave_series(nombre_serie):
            registro["palabras_clave_counter"][clave] += 1

    unidad = limpiar_texto(fila.get("unidad"))
    if unidad:
        registro["unidades_counter"][unidad] += 1

    periodo = limpiar_texto(fila.get("periodo"))
    if periodo:
        registro["periodos_counter"][periodo] += 1

    dato_operacion = limpiar_texto(fila.get("dato_operacion"))
    titulo_tabla = limpiar_texto(fila.get("titulo_tabla"))

    for texto in [dato_operacion, titulo_tabla]:
        if texto:
            for clave in detectar_palabras_clave_series(texto):
                registro["palabras_clave_counter"][clave] += 1


def procesar_jsonl(path, fuente_datos, acumulador, output_errores=None):
    if not os.path.exists(path):
        raise FileNotFoundError(f"No existe el fichero: {path}")

    total_lineas = 0
    total_errores = 0

    with open(path, "r", encoding="utf-8") as file:
        for numero_linea, line in enumerate(tqdm(file, desc=f"LEYENDO {fuente_datos.upper()}"), start=1):
            line = line.strip()

            if not line:
                continue

            try:
                fila = json.loads(line)
            except json.JSONDecodeError as e:
                total_errores += 1
                if output_errores:
                    append_jsonl(output_errores, {
                        "fuente_datos": fuente_datos,
                        "numero_linea": numero_linea,
                        "error": f"JSON mal formado: {e}"
                    })
                continue

            id_tabla = limpiar_texto(fila.get("id_tabla"))

            if not id_tabla:
                total_errores += 1
                if output_errores:
                    append_jsonl(output_errores, {
                        "fuente_datos": fuente_datos,
                        "numero_linea": numero_linea,
                        "error": "Falta id_tabla"
                    })
                continue

            if id_tabla not in acumulador:
                acumulador[id_tabla] = crear_registro_tabla(fila, fuente_datos)

            actualizar_registro_tabla(acumulador[id_tabla], fila, fuente_datos)
            total_lineas += 1

    return total_lineas, total_errores


# ============================================================
# CONSTRUCCIÓN DEL TEXTO SEMÁNTICO
# ============================================================

def construir_texto_documento(registro):
    id_tabla = registro.get("id_tabla")
    dato_operacion = registro.get("dato_operacion")
    titulo_tabla = registro.get("titulo_tabla")
    anyo_min = registro.get("anyo_min")
    anyo_max = registro.get("anyo_max")
    total_observaciones = registro.get("total_observaciones")

    series_principales = [
        serie for serie, _ in registro["series_counter"].most_common(MAX_SERIES_EN_TEXTO)
    ]

    unidades = [
        unidad for unidad, _ in registro["unidades_counter"].most_common(MAX_UNIDADES_EN_TEXTO)
    ]

    periodos = [
        periodo for periodo, _ in registro["periodos_counter"].most_common(MAX_PERIODOS_EN_TEXTO)
    ]

    palabras_clave = [
        palabra for palabra, _ in registro["palabras_clave_counter"].most_common(60)
    ]
    
    vocabulario = [
        palabra for palabra, _ in registro["vocabulario_counter"].most_common(200)
    ]

    fuentes = sorted(list(registro["fuentes_datos"]))

    partes = []

    if dato_operacion:
        partes.append(f"Operación estadística: {dato_operacion}.")

    if titulo_tabla:
        partes.append(f"Tabla: {titulo_tabla}.")

    if id_tabla:
        partes.append(f"Identificador de tabla: {id_tabla}.")

    if palabras_clave:
        partes.append("Temas y dimensiones detectadas: " + ", ".join(palabras_clave) + ".")

    if vocabulario:
        partes.append("Vocabulario relevante de la tabla: " + ", ".join(vocabulario) + ".")
    
    if series_principales:
        partes.append("Series principales de la tabla: " + "; ".join(series_principales) + ".")

    if unidades:
        partes.append("Unidades disponibles: " + ", ".join(unidades) + ".")

    if anyo_min is not None and anyo_max is not None:
        if anyo_min == anyo_max:
            partes.append(f"Año disponible: {anyo_min}.")
        else:
            partes.append(f"Años disponibles: desde {anyo_min} hasta {anyo_max}.")

    if periodos:
        partes.append("Periodos disponibles: " + ", ".join(periodos) + ".")

    partes.append(f"Número de observaciones de la tabla: {total_observaciones}.")

    if fuentes:
        partes.append("Fuentes de datos utilizadas: " + ", ".join(fuentes) + ".")

    texto = " ".join(partes)
    texto = " ".join(texto.split())
    return texto


def construir_metadata(registro):
    series_principales = [
        serie for serie, _ in registro["series_counter"].most_common(30)
    ]

    unidades = [
        unidad for unidad, _ in registro["unidades_counter"].most_common(20)
    ]

    palabras_clave = [
        palabra for palabra, _ in registro["palabras_clave_counter"].most_common(50)
    ]
    
    vocabulario = [
        palabra for palabra, _ in registro["vocabulario_counter"].most_common(200)
    ]

    return {
        "id_tabla": registro.get("id_tabla"),
        "dato_operacion": registro.get("dato_operacion"),
        "titulo_tabla": registro.get("titulo_tabla"),
        "href_tabla": registro.get("href_tabla"),
        "url_api": registro.get("url_api"),
        "fuentes_datos": sorted(list(registro["fuentes_datos"])),
        "anyo_min": registro.get("anyo_min"),
        "anyo_max": registro.get("anyo_max"),
        "total_observaciones": registro.get("total_observaciones"),
        "num_series": len(registro["series_counter"]),
        "series_principales": series_principales,
        "unidades": unidades,
        "palabras_clave": palabras_clave,
        "vocabulario":vocabulario
    }


# ============================================================
# GENERACIÓN DATASET
# ============================================================

def generar_dataset_semantico_por_tabla(
    input_api=INPUT_JSONL_API,
    input_href=INPUT_JSONL_HREF,
    output_jsonl=OUTPUT_JSONL,
    output_resumen=OUTPUT_RESUMEN,
    output_errores=OUTPUT_ERRORES,
    sobrescribir=True
):
    asegurar_carpeta(output_jsonl)
    asegurar_carpeta(output_resumen)
    asegurar_carpeta(output_errores)

    if sobrescribir:
        borrar_si_existe(output_jsonl)
        borrar_si_existe(output_resumen)
        borrar_si_existe(output_errores)

    acumulador = {}

    print("==============================================")
    print(" DATASET SEMÁNTICO POR TABLA")
    print("==============================================")
    print(f"[INFO] Entrada API:  {input_api}")
    print(f"[INFO] Entrada HREF: {input_href}")
    print(f"[INFO] Salida:       {output_jsonl}")

    total_api, errores_api = procesar_jsonl(
        path=input_api,
        fuente_datos="api",
        acumulador=acumulador,
        output_errores=output_errores
    )

    total_href, errores_href = procesar_jsonl(
        path=input_href,
        fuente_datos="href",
        acumulador=acumulador,
        output_errores=output_errores
    )

    total_documentos = 0
    ejemplos = []

    with open(output_jsonl, "w", encoding="utf-8") as out:
        for id_tabla, registro in tqdm(acumulador.items(), desc="ESCRIBIENDO DOCUMENTOS"):
            texto = construir_texto_documento(registro)

            documento = {
                "id_documento": f"tabla_{id_tabla}",
                "texto": texto,
                "metadata": construir_metadata(registro)
            }

            out.write(json.dumps(documento, ensure_ascii=False) + "\n")
            total_documentos += 1

            if len(ejemplos) < 10:
                ejemplos.append(documento)

    top_tablas_observaciones = sorted(
        [
            {
                "id_tabla": registro.get("id_tabla"),
                "dato_operacion": registro.get("dato_operacion"),
                "titulo_tabla": registro.get("titulo_tabla"),
                "total_observaciones": registro.get("total_observaciones"),
                "num_series": len(registro["series_counter"]),
                "anyo_min": registro.get("anyo_min"),
                "anyo_max": registro.get("anyo_max")
            }
            for registro in acumulador.values()
        ],
        key=lambda x: x["total_observaciones"],
        reverse=True
    )[:20]

    resumen = {
        "input_api": input_api,
        "input_href": input_href,
        "output_jsonl": output_jsonl,
        "output_errores": output_errores,
        "total_lineas_api": total_api,
        "total_lineas_href": total_href,
        "errores_api": errores_api,
        "errores_href": errores_href,
        "total_documentos_semanticos": total_documentos,
        "criterio_agrupacion": "1 documento por id_tabla",
        "max_series_en_texto": MAX_SERIES_EN_TEXTO,
        "top_20_tablas_mas_observaciones": top_tablas_observaciones,
        "ejemplos_documentos": ejemplos
    }

    guardar_json(output_resumen, resumen)

    print("==============================================")
    print("[OK] Dataset semántico por tabla generado")
    print(f"[INFO] Documentos generados: {total_documentos}")
    print(f"[INFO] Líneas API procesadas: {total_api}")
    print(f"[INFO] Líneas HREF procesadas: {total_href}")
    print(f"[INFO] Errores API: {errores_api}")
    print(f"[INFO] Errores HREF: {errores_href}")
    print(f"[INFO] JSONL salida: {output_jsonl}")
    print(f"[INFO] Resumen: {output_resumen}")
    print("==============================================")

    return resumen


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Genera dataset semántico resumido por tabla para FAISS."
    )

    parser.add_argument("--input-api", default=INPUT_JSONL_API)
    parser.add_argument("--input-href", default=INPUT_JSONL_HREF)
    parser.add_argument("--output", default=OUTPUT_JSONL)
    parser.add_argument("--resumen", default=OUTPUT_RESUMEN)
    parser.add_argument("--errores", default=OUTPUT_ERRORES)

    args = parser.parse_args()

    ejecutar(
        input_api=args.input_api,
        input_href=args.input_href,
        output_jsonl=args.output,
        output_resumen=args.resumen,
        output_errores=args.errores
    )


# ============================================================
# EJECUCIÓN DESDE OTROS MÓDULOS
# ============================================================

def ejecutar(
        input_api=INPUT_JSONL_API,
        input_href=INPUT_JSONL_HREF,
        output_jsonl=OUTPUT_JSONL,
        output_resumen=OUTPUT_RESUMEN,
        output_errores=OUTPUT_ERRORES,
        sobrescribir=True):

    return generar_dataset_semantico_por_tabla(
        input_api=input_api,
        input_href=input_href,
        output_jsonl=output_jsonl,
        output_resumen=output_resumen,
        output_errores=output_errores,
        sobrescribir=sobrescribir
    )


if __name__ == "__main__":
    main()