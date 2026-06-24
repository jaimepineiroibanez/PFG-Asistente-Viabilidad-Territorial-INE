import json
import os
import re
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from tqdm import tqdm


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_JSONL = "./datos/validados/datos_tablas_href_ine_validos.jsonl"

OUTPUT_JSONL = "./datos/normalizados/dataset_ine_normalizado_href.jsonl"
OUTPUT_RESUMEN = "./datos/normalizados/resumen_normalizacion_href.json"
OUTPUT_ERRORES = "./datos/normalizados/errores_normalizacion_href.jsonl"


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


def append_jsonl(path, data):
    asegurar_carpeta(path)
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False) + "\n")


def guardar_json(path, data):
    asegurar_carpeta(path)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def calcular_hilos_trabajo():
    cpu_total = os.cpu_count() or 1
    restantes = max(cpu_total - 1, 0)
    num_hilos_trabajo = (restantes // 2) + 1
    return cpu_total, num_hilos_trabajo


# ============================================================
# CONVERSIONES
# ============================================================

def convertir_a_string(valor):
    if valor is None:
        return None

    if isinstance(valor, (dict, list)):
        return json.dumps(valor, ensure_ascii=False, sort_keys=True)

    texto = str(valor).strip()
    return texto if texto else None


def limpiar_numero_texto(texto):
    texto = str(texto).strip()
    if not texto:
        return ""

    # Valores habituales del INE para dato no disponible, secreto estadístico, etc.
    if texto in {"..", ".", "-", "--", "…", "", " ", "nan", "NaN", "None", "null"}:
        return ""

    texto = texto.replace("\u00a0", "").replace(" ", "")

    # Si aparecen separadores europeos: 1.234,56 -> 1234.56
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")

    return texto


def convertir_a_float(valor):
    if valor is None or isinstance(valor, bool):
        return None, False

    if isinstance(valor, (int, float)):
        return float(valor), True

    texto = limpiar_numero_texto(valor)
    if not texto:
        return None, False

    try:
        return float(texto), True
    except ValueError:
        return None, False


def convertir_a_int(valor):
    if valor is None or isinstance(valor, bool):
        return None, False

    if isinstance(valor, int):
        return valor, True

    if isinstance(valor, float) and valor.is_integer():
        return int(valor), True

    texto = limpiar_numero_texto(valor)
    if not texto:
        return None, False

    try:
        return int(float(texto)), True
    except ValueError:
        return None, False


def normalizar_clave(clave):
    texto = convertir_a_string(clave) or ""
    texto = texto.lower().strip()
    reemplazos = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"
    }
    for origen, destino in reemplazos.items():
        texto = texto.replace(origen, destino)
    texto = re.sub(r"\s+", " ", texto)
    return texto


# ============================================================
# DETECCIÓN DE CAMPOS EN CSV INE
# ============================================================

CLAVES_PERIODO = {
    "periodo", "periodos", "fecha", "fechas", "ano", "año", "anyo", "year", "time", "mes", "trimestre"
}

CLAVES_UNIDAD = {
    "unidad", "unidades", "unidad de medida", "medida"
}

CLAVES_VALOR = {
    "valor", "value", "total", "dato", "datos", "indice", "índice", "porcentaje", "tasa"
}


def es_columna_periodo(columna):
    c = normalizar_clave(columna)
    return c in CLAVES_PERIODO or "periodo" in c or c.startswith("ano") or c.startswith("año")


def es_columna_unidad(columna):
    c = normalizar_clave(columna)
    return c in CLAVES_UNIDAD or "unidad" in c


def extraer_anyo_desde_texto(valor):
    texto = convertir_a_string(valor)
    if not texto:
        return None, None

    anyo, ok = convertir_a_int(texto)
    if ok and 1800 <= anyo <= 2200:
        return anyo, "directo"

    match = re.search(r"(18|19|20|21)\d{2}", texto)
    if match:
        anyo, ok = convertir_a_int(match.group(0))
        if ok:
            return anyo, "regex"

    return None, None


def obtener_periodo_y_anyo(fila_csv):
    # Primero se buscan columnas temporales explícitas
    for columna, valor in fila_csv.items():
        if es_columna_periodo(columna):
            periodo = convertir_a_string(valor)
            anyo, origen = extraer_anyo_desde_texto(valor)
            return periodo, None, periodo, anyo, f"csv_{normalizar_clave(columna)}_{origen}" if origen else None

    # Si no existe columna temporal explícita, se busca un año en cualquier dimensión
    for columna, valor in fila_csv.items():
        anyo, origen = extraer_anyo_desde_texto(valor)
        if anyo is not None:
            periodo = convertir_a_string(valor)
            return periodo, None, periodo, anyo, f"csv_{normalizar_clave(columna)}_{origen}"

    return None, None, None, None, None


def obtener_unidad(fila_csv):
    for columna, valor in fila_csv.items():
        if es_columna_unidad(columna):
            unidad = convertir_a_string(valor)
            return unidad, unidad, None, None
    return None, None, None, None


def detectar_columnas_valor(filas_csv, columnas):
    """
    Detecta columnas que pueden convertirse a float.

    La salida normalizada del API genera una fila por observación. En CSV, una
    observación puede venir en columnas anchas. Por eso, cada columna numérica
    detectada se convierte en una observación normalizada independiente.
    """
    columnas_valor = []

    for columna in columnas:
        if es_columna_periodo(columna) or es_columna_unidad(columna):
            continue

        total_no_vacios = 0
        total_convertibles = 0

        for fila in filas_csv[:200]:
            valor = fila.get(columna)
            if convertir_a_string(valor) is None:
                continue
            total_no_vacios += 1
            _, ok = convertir_a_float(valor)
            if ok:
                total_convertibles += 1

        if total_no_vacios == 0:
            continue

        ratio = total_convertibles / total_no_vacios
        nombre = normalizar_clave(columna)

        # Se acepta si la mayoría de valores son numéricos o si la columna tiene nombre claro de valor.
        if ratio >= 0.70 or (nombre in CLAVES_VALOR and total_convertibles > 0):
            columnas_valor.append(columna)

    return columnas_valor


def construir_nombre_serie(fila_csv, columna_valor, columnas_valor):
    dimensiones = []

    for columna, valor in fila_csv.items():
        if columna in columnas_valor:
            continue
        if es_columna_periodo(columna) or es_columna_unidad(columna):
            continue

        valor_txt = convertir_a_string(valor)
        if valor_txt:
            dimensiones.append(valor_txt)

    titulo_indicador = convertir_a_string(columna_valor)

    if dimensiones and titulo_indicador:
        return ". ".join(dimensiones + [titulo_indicador])

    if dimensiones:
        return ". ".join(dimensiones)

    return titulo_indicador


def metadata_csv_sin_valor(fila_csv, columnas_valor):
    return {
        clave: valor
        for clave, valor in fila_csv.items()
        if clave not in columnas_valor
    }


# ============================================================
# NORMALIZACIÓN DE REGISTRO HREF CSV
# ============================================================

def normalizar_registro(registro):
    filas_normalizadas = []
    errores = []

    datos_csv = registro.get("datos_csv")

    if not isinstance(datos_csv, list):
        return [], [{
            "id_tabla": registro.get("id_tabla"),
            "error": f"datos_csv no soportado: {type(datos_csv).__name__}"
        }]

    if not datos_csv:
        return [], [{
            "id_tabla": registro.get("id_tabla"),
            "error": "datos_csv vacío"
        }]

    columnas = registro.get("columnas")
    if not isinstance(columnas, list) or not columnas:
        # Plan B: deducir columnas a partir de las primeras filas
        columnas = []
        for fila in datos_csv[:20]:
            if isinstance(fila, dict):
                for clave in fila.keys():
                    if clave not in columnas:
                        columnas.append(clave)

    columnas_valor = detectar_columnas_valor(datos_csv, columnas)

    if not columnas_valor:
        return [], [{
            "id_tabla": registro.get("id_tabla"),
            "error": "No se han detectado columnas numéricas de valor",
            "columnas": columnas
        }]

    parametros_url = registro.get("parametros_url") or {}

    for indice_fila_csv, fila_csv in enumerate(datos_csv):
        if not isinstance(fila_csv, dict):
            errores.append({
                "id_tabla": registro.get("id_tabla"),
                "error": "fila CSV no es diccionario",
                "indice_fila_csv": indice_fila_csv
            })
            continue

        periodo, periodo_codigo, periodo_nombre, anyo, origen_anyo = obtener_periodo_y_anyo(fila_csv)
        fecha = periodo if periodo and re.search(r"(18|19|20|21)\d{2}[-/]\d{1,2}[-/]\d{1,2}", periodo) else None
        unidad, unidad_nombre, unidad_codigo, unidad_abrev = obtener_unidad(fila_csv)

        metadata_serie_raw = json.dumps({
            "fuente_descarga": registro.get("fuente_descarga"),
            "url_export": registro.get("url_export"),
            "url_csv": registro.get("url_csv"),
            "content_type": registro.get("content_type"),
            "encoding": registro.get("encoding"),
            "delimitador": registro.get("delimitador"),
            "columnas_csv": columnas,
            "columnas_valor_detectadas": columnas_valor,
            "dimensiones_csv": metadata_csv_sin_valor(fila_csv, columnas_valor)
        }, ensure_ascii=False, sort_keys=True)

        for columna_valor in columnas_valor:
            valor_raw = fila_csv.get(columna_valor)
            valor, valor_ok = convertir_a_float(valor_raw)

            if not valor_ok:
                # Igual que en el normalizador de API, no se genera fila si el valor no es float.
                # Se guarda como error para trazabilidad.
                if convertir_a_string(valor_raw) is not None:
                    errores.append({
                        "id_tabla": registro.get("id_tabla"),
                        "error": "valor CSV no convertible a float",
                        "indice_fila_csv": indice_fila_csv,
                        "columna_valor": columna_valor,
                        "valor_raw": valor_raw,
                        "fila_csv": fila_csv
                    })
                continue

            nombre_serie = construir_nombre_serie(fila_csv, columna_valor, columnas_valor)

            punto_raw = {
                "columna_valor": columna_valor,
                "valor_raw": valor_raw,
                "fila_csv": fila_csv
            }

            fila = {
                "letra": convertir_a_string(registro.get("Letra")),
                "dato_operacion": convertir_a_string(registro.get("Dato")),
                "href_operacion": convertir_a_string(registro.get("href_operacion")),

                "c": convertir_a_string(parametros_url.get("c")),
                "cid": convertir_a_string(parametros_url.get("cid")),
                "idp": convertir_a_string(parametros_url.get("idp")),

                "id_tabla": convertir_a_string(registro.get("id_tabla")),
                "titulo_tabla": convertir_a_string(registro.get("titulo_tabla")),
                "href_tabla": convertir_a_string(registro.get("href_tabla")),
                "url_api": convertir_a_string(registro.get("url_api_original")),

                "nombre_serie": convertir_a_string(nombre_serie),
                "codigo_serie": None,

                "unidad": convertir_a_string(unidad),
                "unidad_nombre": convertir_a_string(unidad_nombre),
                "unidad_codigo": convertir_a_string(unidad_codigo),
                "unidad_abrev": convertir_a_string(unidad_abrev),

                "periodo": convertir_a_string(periodo),
                "periodo_codigo": convertir_a_string(periodo_codigo),
                "periodo_nombre": convertir_a_string(periodo_nombre),

                "anyo": anyo,
                "fecha": convertir_a_string(fecha),
                "valor": valor,

                "origen_anyo": convertir_a_string(origen_anyo),
                "datos_periodo_raw": json.dumps(punto_raw, ensure_ascii=False, sort_keys=True),
                "metadata_serie_raw": metadata_serie_raw
            }

            filas_normalizadas.append(fila)

    return filas_normalizadas, errores


# ============================================================
# HILOS
# ============================================================

def procesar_linea(numero_linea, line):
    line = line.strip()

    if not line:
        return {
            "numero_linea": numero_linea,
            "filas": [],
            "errores": [],
            "linea_vacia": True
        }

    try:
        registro = json.loads(line)
    except json.JSONDecodeError as e:
        return {
            "numero_linea": numero_linea,
            "filas": [],
            "errores": [{
                "numero_linea": numero_linea,
                "error": f"JSON mal formado: {e}"
            }],
            "linea_vacia": False
        }

    filas, errores = normalizar_registro(registro)

    for error in errores:
        error["numero_linea"] = numero_linea

    return {
        "numero_linea": numero_linea,
        "filas": filas,
        "errores": errores,
        "linea_vacia": False
    }


def cargar_lineas(input_jsonl, max_lineas=None):
    tareas = []

    with open(input_jsonl, "r", encoding="utf-8") as file:
        for numero_linea, line in enumerate(file, start=1):
            if max_lineas is not None and len(tareas) >= max_lineas:
                break

            if not line.strip():
                continue

            tareas.append((numero_linea, line))

    return tareas


def escribir_resultados_y_resumen(resultados, input_jsonl, output_jsonl, output_resumen, output_errores):
    total_lineas = 0
    total_filas = 0
    total_errores = 0
    registros_sin_filas = 0

    nulos = {
        "titulo_tabla": 0,
        "periodo": 0,
        "periodo_codigo": 0,
        "periodo_nombre": 0,
        "anyo": 0,
        "fecha": 0,
        "unidad": 0,
        "unidad_nombre": 0,
        "nombre_serie": 0,
        "codigo_serie": 0
    }

    tipos_valor = Counter()
    origen_anyo_counter = Counter()
    ejemplos_filas = []
    ejemplos_errores = []

    resultados.sort(key=lambda x: x["numero_linea"])

    for resultado in resultados:
        if resultado.get("linea_vacia"):
            continue

        total_lineas += 1
        filas = resultado.get("filas", [])
        errores = resultado.get("errores", [])

        if not filas:
            registros_sin_filas += 1

        for fila in filas:
            append_jsonl(output_jsonl, fila)
            total_filas += 1

            for campo in nulos:
                if fila.get(campo) is None:
                    nulos[campo] += 1

            tipos_valor[type(fila["valor"]).__name__] += 1
            origen_anyo_counter[fila.get("origen_anyo") or "null"] += 1

            if len(ejemplos_filas) < 5:
                ejemplos_filas.append(fila)

        for error in errores:
            append_jsonl(output_errores, error)
            total_errores += 1

            if len(ejemplos_errores) < 10:
                ejemplos_errores.append(error)

    campos_salida = {
        "letra": "string",
        "dato_operacion": "string",
        "href_operacion": "string",
        "c": "string",
        "cid": "string",
        "idp": "string",
        "id_tabla": "string",
        "titulo_tabla": "string",
        "href_tabla": "string",
        "url_api": "string",
        "nombre_serie": "string",
        "codigo_serie": "string",
        "unidad": "string",
        "unidad_nombre": "string",
        "unidad_codigo": "string",
        "unidad_abrev": "string",
        "periodo": "string",
        "periodo_codigo": "string",
        "periodo_nombre": "string",
        "anyo": "int",
        "fecha": "string",
        "valor": "float",
        "origen_anyo": "string",
        "datos_periodo_raw": "string_json",
        "metadata_serie_raw": "string_json"
    }

    completitud = {}
    for campo, num_nulos in nulos.items():
        completitud[campo] = round(((total_filas - num_nulos) / total_filas) * 100, 2) if total_filas else 0

    completitud["valor"] = 100.0 if total_filas else 0

    resumen = {
        "fecha_ejecucion": datetime.now().isoformat(timespec="seconds"),
        "input_jsonl": input_jsonl,
        "output_jsonl": output_jsonl,
        "output_errores": output_errores,
        "total_lineas_entrada": total_lineas,
        "total_filas_normalizadas": total_filas,
        "total_errores_normalizacion": total_errores,
        "registros_sin_filas": registros_sin_filas,
        "campos_salida": campos_salida,
        "tipos_valor": dict(tipos_valor),
        "nulos": nulos,
        "porcentaje_completitud": completitud,
        "origen_anyo": dict(origen_anyo_counter),
        "ejemplos_filas": ejemplos_filas,
        "ejemplos_errores": ejemplos_errores
    }

    guardar_json(output_resumen, resumen)
    return resumen


def normalizar_jsonl_href_mejorado(
    input_jsonl=INPUT_JSONL,
    output_jsonl=OUTPUT_JSONL,
    output_resumen=OUTPUT_RESUMEN,
    output_errores=OUTPUT_ERRORES,
    max_lineas=None,
    num_hilos=None,
    sobrescribir=True,
    console_output=None
):
    if not os.path.exists(input_jsonl):
        print(f"[ERROR] No existe el fichero de entrada: {input_jsonl}")
        return None

    if sobrescribir:
        borrar_si_existe(output_jsonl)
        borrar_si_existe(output_errores)
        borrar_si_existe(output_resumen)

    tareas = cargar_lineas(input_jsonl, max_lineas=max_lineas)

    if not tareas:
        print("[ERROR] No hay líneas para normalizar.")
        return None

    cpu_total, hilos_calculados = calcular_hilos_trabajo()

    if num_hilos is None:
        num_hilos = hilos_calculados

    if num_hilos < 1:
        num_hilos = 1

    print("==============================================")
    print(" NORMALIZACIÓN JSONL HREF INE CSV CON HILOS")
    print("==============================================")
    print(f"[INFO] Entrada: {input_jsonl}")
    print(f"[INFO] Salida:  {output_jsonl}")
    print(f"[INFO] CPU lógicas detectadas: {cpu_total}")
    print(f"[INFO] Hilos calculados: {hilos_calculados}")
    print(f"[INFO] Hilos usados: {num_hilos}")
    print(f"[INFO] Líneas a procesar: {len(tareas)}")

    resultados = []

    with ThreadPoolExecutor(max_workers=num_hilos) as executor:
        futuros = {
            executor.submit(procesar_linea, numero_linea, line): numero_linea
            for numero_linea, line in tareas
        }

        with tqdm(total=len(futuros), desc="NORMALIZANDO HREF CSV", file=console_output) as pbar:
            for futuro in as_completed(futuros):
                try:
                    resultados.append(futuro.result())
                except Exception as e:
                    numero_linea = futuros[futuro]
                    resultados.append({
                        "numero_linea": numero_linea,
                        "filas": [],
                        "errores": [{
                            "numero_linea": numero_linea,
                            "error": f"Error no controlado en hilo: {e}"
                        }],
                        "linea_vacia": False
                    })

                pbar.update(1)

    print("[INFO] Escribiendo resultados normalizados...")
    resumen = escribir_resultados_y_resumen(
        resultados=resultados,
        input_jsonl=input_jsonl,
        output_jsonl=output_jsonl,
        output_resumen=output_resumen,
        output_errores=output_errores
    )

    print("==============================================")
    print("[OK] Normalización HREF CSV finalizada")
    print(f"[INFO] Líneas de entrada: {resumen['total_lineas_entrada']}")
    print(f"[INFO] Filas normalizadas: {resumen['total_filas_normalizadas']}")
    print(f"[INFO] Errores: {resumen['total_errores_normalizacion']}")
    print(f"[INFO] Registros sin filas: {resumen['registros_sin_filas']}")
    print(f"[INFO] JSONL normalizado: {output_jsonl}")
    print(f"[INFO] Resumen: {output_resumen}")
    print(f"[INFO] Errores: {output_errores}")
    print("==============================================")

    return resumen


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Normaliza datos_tablas_href_ine_validos.jsonl para generar el mismo esquema que la normalización de API INE."
    )

    parser.add_argument("--input", default=INPUT_JSONL)
    parser.add_argument("--output", default=OUTPUT_JSONL)
    parser.add_argument("--resumen", default=OUTPUT_RESUMEN)
    parser.add_argument("--errores", default=OUTPUT_ERRORES)
    parser.add_argument("--max-lineas", type=int, default=None)
    parser.add_argument("--num-hilos", type=int, default=None)
    parser.add_argument("--append", action="store_true", help="No borra salidas anteriores antes de ejecutar.")

    args = parser.parse_args()

    ejecutar(
        input_jsonl=args.input,
        output_jsonl=args.output,
        output_resumen=args.resumen,
        output_errores=args.errores,
        max_lineas=args.max_lineas,
        num_hilos=args.num_hilos,
        sobrescribir=not args.append
    )


# ============================================================
# EJECUCIÓN DESDE OTROS MÓDULOS
# ============================================================

def ejecutar(
        input_jsonl=INPUT_JSONL,
        output_jsonl=OUTPUT_JSONL,
        output_resumen=OUTPUT_RESUMEN,
        output_errores=OUTPUT_ERRORES,
        max_lineas=None,
        num_hilos=None,
        sobrescribir=True):

    return normalizar_jsonl_href_mejorado(
        input_jsonl=input_jsonl,
        output_jsonl=output_jsonl,
        output_resumen=output_resumen,
        output_errores=output_errores,
        max_lineas=max_lineas,
        num_hilos=num_hilos,
        sobrescribir=sobrescribir
    )


if __name__ == "__main__":
    main()
