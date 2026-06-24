import json
import os
import argparse
from collections import Counter
from urllib.parse import urlparse


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_JSONL = "./datos/originales/datos_tablas_href_ine.jsonl"
OUTPUT_RESUMEN = "./datos/validados/resumen_validacion_href_ine.json"
OUTPUT_VALIDOS = "./datos/validados/datos_tablas_href_ine_validos.jsonl"
OUTPUT_INVALIDOS = "./datos/validados/datos_tablas_href_ine_invalidos.jsonl"


# ============================================================
# UTILIDADES DE FICHEROS
# ============================================================

def asegurar_carpeta(path):
    carpeta = os.path.dirname(path)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)


def guardar_json(path, data):
    asegurar_carpeta(path)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def append_jsonl(path, data):
    asegurar_carpeta(path)
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False) + "\n")


def borrar_si_existe(path):
    if os.path.exists(path):
        os.remove(path)


# ============================================================
# VALIDACIÓN DE ESTRUCTURA CSV DESCARGADA DESDE HREF_TABLA
# ============================================================

def es_url_ine(url):
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and parsed.netloc.endswith("ine.es")
    except Exception:
        return False


def detectar_tipo_datos_csv(datos_csv):
    if datos_csv is None:
        return "null"

    if isinstance(datos_csv, list):
        if len(datos_csv) == 0:
            return "lista_vacia"

        primer = datos_csv[0]

        if isinstance(primer, dict):
            return "lista_filas_diccionario"

        if isinstance(primer, list):
            return "lista_filas_lista"

        return "lista_valores"

    if isinstance(datos_csv, dict):
        if len(datos_csv) == 0:
            return "dict_vacio"
        return "dict_otro"

    return type(datos_csv).__name__


def contar_filas(datos_csv):
    if isinstance(datos_csv, list):
        return len(datos_csv)
    return 0


def extraer_claves_filas(datos_csv, limite=20):
    claves = Counter()

    if isinstance(datos_csv, list):
        for fila in datos_csv[:limite]:
            if isinstance(fila, dict):
                claves.update(fila.keys())

    return dict(claves)


def contar_filas_vacias(datos_csv):
    if not isinstance(datos_csv, list):
        return 0

    total = 0
    for fila in datos_csv:
        if not isinstance(fila, dict):
            continue

        valores = [valor for valor in fila.values() if valor not in (None, "")]
        if not valores:
            total += 1

    return total


def contar_columnas_vacias(datos_csv, columnas):
    if not isinstance(datos_csv, list) or not columnas:
        return {}

    contador = Counter()
    total_filas = len(datos_csv)

    for columna in columnas:
        for fila in datos_csv:
            if not isinstance(fila, dict):
                continue
            valor = fila.get(columna)
            if valor in (None, ""):
                contador[columna] += 1

    return {
        columna: {
            "vacios": vacios,
            "porcentaje_vacios": round((vacios / total_filas) * 100, 2) if total_filas else 0
        }
        for columna, vacios in contador.items()
    }


def detectar_columnas_inconsistentes(datos_csv, columnas):
    """
    Detecta filas con claves diferentes a las columnas declaradas.
    No siempre invalida la tabla, pero es útil para localizar CSV mal parseados.
    """
    if not isinstance(datos_csv, list) or not columnas:
        return 0

    columnas_set = set(columnas)
    inconsistentes = 0

    for fila in datos_csv:
        if not isinstance(fila, dict):
            inconsistentes += 1
            continue

        if set(fila.keys()) != columnas_set:
            inconsistentes += 1

    return inconsistentes


def validar_registro(registro, numero_linea):
    errores = []
    avisos = []

    id_tabla = registro.get("id_tabla")
    estado = registro.get("estado")
    href_tabla = registro.get("href_tabla")
    url_export = registro.get("url_export")
    url_csv = registro.get("url_csv")
    fuente_descarga = registro.get("fuente_descarga")
    datos_csv = registro.get("datos_csv")
    columnas = registro.get("columnas") or []
    num_filas_declarado = registro.get("num_filas")
    delimitador = registro.get("delimitador")
    encoding = registro.get("encoding")

    if not id_tabla:
        errores.append("Falta id_tabla")

    if estado != "OK":
        errores.append(f"Estado no OK: {estado}")

    if fuente_descarga != "href_tabla_csv":
        avisos.append(f"fuente_descarga inesperada: {fuente_descarga}")

    if not href_tabla:
        errores.append("Falta href_tabla")
    elif not es_url_ine(href_tabla):
        errores.append("href_tabla no pertenece al dominio ine.es")

    if not url_csv:
        errores.append("Falta url_csv")
    elif not es_url_ine(url_csv):
        errores.append("url_csv no pertenece al dominio ine.es")

    if not url_export:
        avisos.append("Falta url_export")

    if not encoding:
        avisos.append("Falta encoding")

    if not delimitador:
        avisos.append("Falta delimitador")
    elif delimitador not in [";", "\t", ","]:
        avisos.append(f"Delimitador poco habitual: {repr(delimitador)}")

    if datos_csv is None:
        errores.append("datos_csv es null")

    tipo_estructura = detectar_tipo_datos_csv(datos_csv)
    num_filas_reales = contar_filas(datos_csv)
    claves_filas = extraer_claves_filas(datos_csv)
    num_columnas = len(columnas)
    filas_vacias = contar_filas_vacias(datos_csv)
    columnas_vacias = contar_columnas_vacias(datos_csv, columnas)
    filas_inconsistentes = detectar_columnas_inconsistentes(datos_csv, columnas)

    if tipo_estructura in ["null", "lista_vacia", "dict_vacio"]:
        errores.append(f"Respuesta vacia: {tipo_estructura}")

    if tipo_estructura != "lista_filas_diccionario":
        errores.append(f"Estructura CSV no esperada: {tipo_estructura}")

    if num_filas_reales == 0:
        errores.append("No se han detectado filas CSV")

    if num_columnas == 0:
        errores.append("No se han detectado columnas CSV")

    if isinstance(num_filas_declarado, int) and num_filas_declarado != num_filas_reales:
        errores.append(
            f"num_filas no coincide: declarado={num_filas_declarado}, real={num_filas_reales}"
        )

    if filas_vacias > 0:
        avisos.append(f"Existen filas completamente vacias: {filas_vacias}")

    if filas_inconsistentes > 0:
        avisos.append(f"Existen filas con columnas inconsistentes: {filas_inconsistentes}")

    if columnas and claves_filas:
        columnas_no_en_filas = sorted(set(columnas) - set(claves_filas.keys()))
        claves_no_declaradas = sorted(set(claves_filas.keys()) - set(columnas))

        if columnas_no_en_filas:
            avisos.append(f"Columnas declaradas no presentes en las filas: {columnas_no_en_filas[:10]}")

        if claves_no_declaradas:
            avisos.append(f"Claves en filas no declaradas en columnas: {claves_no_declaradas[:10]}")

    es_valido = len(errores) == 0

    detalle = {
        "numero_linea": numero_linea,
        "id_tabla": id_tabla,
        "Dato": registro.get("Dato"),
        "titulo_tabla": registro.get("titulo_tabla"),
        "href_tabla": href_tabla,
        "url_export": url_export,
        "url_csv": url_csv,
        "estado": estado,
        "fuente_descarga": fuente_descarga,
        "valido": es_valido,
        "errores": errores,
        "avisos": avisos,
        "tipo_estructura": tipo_estructura,
        "num_filas_declarado": num_filas_declarado,
        "num_filas_reales": num_filas_reales,
        "num_columnas": num_columnas,
        "columnas": columnas,
        "claves_filas": claves_filas,
        "filas_vacias": filas_vacias,
        "filas_inconsistentes": filas_inconsistentes,
        "columnas_vacias": columnas_vacias,
        "delimitador": delimitador,
        "encoding": encoding,
        "content_type": registro.get("content_type"),
        "url_api_original": registro.get("url_api_original"),
        "error_api_original": registro.get("error_api_original")
    }

    return es_valido, detalle


# ============================================================
# PROCESO PRINCIPAL
# ============================================================

def validar_jsonl(
    input_jsonl=INPUT_JSONL,
    output_resumen=OUTPUT_RESUMEN,
    output_validos=OUTPUT_VALIDOS,
    output_invalidos=OUTPUT_INVALIDOS,
    max_lineas=None,
    guardar_separados=True
):
    if not os.path.exists(input_jsonl):
        print(f"[ERROR] No existe el fichero: {input_jsonl}")
        return None

    if guardar_separados:
        borrar_si_existe(output_validos)
        borrar_si_existe(output_invalidos)

    total_lineas = 0
    json_mal_formado = 0
    validos = 0
    invalidos = 0

    errores_counter = Counter()
    avisos_counter = Counter()
    estructuras_counter = Counter()
    columnas_counter = Counter()
    delimitadores_counter = Counter()
    encodings_counter = Counter()

    ejemplos_invalidos = []
    ejemplos_validos = []
    tablas_sin_filas = []
    filas_por_tabla = []

    print("==============================================")
    print(" VALIDACION JSONL CSV HREF INE")
    print("==============================================")
    print(f"[INFO] Entrada: {input_jsonl}")

    with open(input_jsonl, "r", encoding="utf-8") as file:
        for numero_linea, line in enumerate(file, start=1):
            if max_lineas is not None and total_lineas >= max_lineas:
                break

            line = line.strip()
            if not line:
                continue

            total_lineas += 1

            try:
                registro = json.loads(line)
            except json.JSONDecodeError as e:
                json_mal_formado += 1
                invalidos += 1

                detalle_error = {
                    "numero_linea": numero_linea,
                    "valido": False,
                    "errores": [f"JSON mal formado: {e}"],
                    "contenido_linea": line[:500]
                }

                if len(ejemplos_invalidos) < 10:
                    ejemplos_invalidos.append(detalle_error)

                if guardar_separados:
                    append_jsonl(output_invalidos, detalle_error)

                continue

            es_valido, detalle = validar_registro(registro, numero_linea)

            estructuras_counter[detalle["tipo_estructura"]] += 1
            columnas_counter.update(detalle["columnas"])
            delimitadores_counter[str(detalle["delimitador"])] += 1
            encodings_counter[str(detalle["encoding"])] += 1

            for error in detalle["errores"]:
                errores_counter[error] += 1

            for aviso in detalle["avisos"]:
                avisos_counter[aviso] += 1

            filas_por_tabla.append({
                "id_tabla": detalle["id_tabla"],
                "Dato": detalle["Dato"],
                "titulo_tabla": detalle["titulo_tabla"],
                "num_columnas": detalle["num_columnas"],
                "num_filas_reales": detalle["num_filas_reales"],
                "url_csv": detalle["url_csv"]
            })

            if detalle["num_filas_reales"] == 0:
                tablas_sin_filas.append(detalle)

            if es_valido:
                validos += 1

                if len(ejemplos_validos) < 5:
                    ejemplos_validos.append(detalle)

                if guardar_separados:
                    append_jsonl(output_validos, registro)
            else:
                invalidos += 1

                if len(ejemplos_invalidos) < 10:
                    ejemplos_invalidos.append(detalle)

                if guardar_separados:
                    append_jsonl(output_invalidos, {
                        "detalle_validacion": detalle,
                        "registro_original": registro
                    })

    filas_ordenadas = sorted(
        filas_por_tabla,
        key=lambda item: item["num_filas_reales"],
        reverse=True
    )

    resumen = {
        "input_jsonl": input_jsonl,
        "total_lineas_procesadas": total_lineas,
        "json_mal_formado": json_mal_formado,
        "validos": validos,
        "invalidos": invalidos,
        "porcentaje_validos": round((validos / total_lineas) * 100, 2) if total_lineas else 0,
        "estructuras_detectadas": dict(estructuras_counter),
        "errores_mas_frecuentes": dict(errores_counter.most_common()),
        "avisos_mas_frecuentes": dict(avisos_counter.most_common()),
        "columnas_mas_frecuentes": dict(columnas_counter.most_common(50)),
        "delimitadores_detectados": dict(delimitadores_counter.most_common()),
        "encodings_detectados": dict(encodings_counter.most_common()),
        "top_10_tablas_mas_filas": filas_ordenadas[:10],
        "top_10_tablas_menos_filas": filas_ordenadas[-10:] if filas_ordenadas else [],
        "num_tablas_sin_filas": len(tablas_sin_filas),
        "ejemplos_validos": ejemplos_validos,
        "ejemplos_invalidos": ejemplos_invalidos,
        "output_validos": output_validos if guardar_separados else None,
        "output_invalidos": output_invalidos if guardar_separados else None
    }

    guardar_json(output_resumen, resumen)

    print("==============================================")
    print("[OK] Validacion finalizada")
    print(f"[INFO] Lineas procesadas: {total_lineas}")
    print(f"[INFO] Registros validos: {validos}")
    print(f"[INFO] Registros invalidos: {invalidos}")
    print(f"[INFO] JSON mal formado: {json_mal_formado}")
    print(f"[INFO] Porcentaje validos: {resumen['porcentaje_validos']}%")
    print(f"[INFO] Resumen: {output_resumen}")

    if guardar_separados:
        print(f"[INFO] Validos: {output_validos}")
        print(f"[INFO] Invalidos: {output_invalidos}")

    print("==============================================")

    return resumen


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Valida el JSONL descargado desde href_tabla CSV del INE."
    )

    parser.add_argument("--input", default=INPUT_JSONL)
    parser.add_argument("--resumen", default=OUTPUT_RESUMEN)
    parser.add_argument("--validos", default=OUTPUT_VALIDOS)
    parser.add_argument("--invalidos", default=OUTPUT_INVALIDOS)

    parser.add_argument(
        "--max-lineas",
        type=int,
        default=None,
        help="Numero maximo de lineas a validar."
    )

    parser.add_argument(
        "--no-separar",
        action="store_true",
        help="No genera JSONL separado de validos e invalidos."
    )

    args = parser.parse_args()

    ejecutar(
    input_jsonl=args.input,
    output_resumen=args.resumen,
    output_validos=args.validos,
    output_invalidos=args.invalidos,
    max_lineas=args.max_lineas,
    guardar_separados=not args.no_separar
    )


# ============================================================
# EJECUCIÓN DESDE OTROS MÓDULOS
# ============================================================


def ejecutar(
        input_jsonl=INPUT_JSONL,
        output_resumen=OUTPUT_RESUMEN,
        output_validos=OUTPUT_VALIDOS,
        output_invalidos=OUTPUT_INVALIDOS,
        max_lineas=None,
        guardar_separados=True):

    return validar_jsonl(
        input_jsonl=input_jsonl,
        output_resumen=output_resumen,
        output_validos=output_validos,
        output_invalidos=output_invalidos,
        max_lineas=max_lineas,
        guardar_separados=guardar_separados
    )


if __name__ == "__main__":
    main()
