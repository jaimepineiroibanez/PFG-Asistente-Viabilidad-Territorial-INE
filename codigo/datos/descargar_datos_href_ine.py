import argparse
import csv
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_ERRORES = "./datos/originales/errores_api_ine.json"
OUTPUT_JSONL = "./datos/originales/datos_tablas_href_ine.jsonl"
OUTPUT_ERRORES = "./datos/originales/errores_href_ine.json"

DOMINIO_INE = "https://www.ine.es"

HEADERS = {
    "User-Agent": "PFG-Scraper-INE/1.0 (j.pineiroi@alumnos.upm.es)"
}

TIMEOUT = 30


# ============================================================
# UTILIDADES DE FICHEROS
# ============================================================

def cargar_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


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


def calcular_hilos_trabajo():
    cpu_total = os.cpu_count() or 1
    restantes = max(cpu_total - 1, 0)
    num_hilos_trabajo = (restantes // 2) + 1
    return cpu_total, num_hilos_trabajo


# ============================================================
# PREPARACIÓN DE TAREAS
# ============================================================

def es_url_ine_jaxi(url):
    if not url:
        return False

    parsed = urlparse(url)
    dominio_valido = parsed.netloc.endswith("ine.es")
    ruta_valida = "/jaxi" in parsed.path.lower()
    return dominio_valido and ruta_valida


def preparar_tareas(input_json, max_tablas=None):
    """
    Lee errores_api_ine.json y prepara solo las entradas que tienen href_tabla
    descargable desde INE/JAXI. Se descartan enlaces externos como YouTube.
    """
    datos = cargar_json(input_json)
    tareas = []
    claves_vistas = set()

    for item in datos:
        href_tabla = item.get("href_tabla")

        if not es_url_ine_jaxi(href_tabla):
            continue

        # La clave combina href_tabla e id_tabla para evitar duplicados exactos,
        # pero permite conservar tablas con mismo id en rutas históricas distintas.
        clave = (item.get("id_tabla"), href_tabla)
        if clave in claves_vistas:
            continue

        claves_vistas.add(clave)
        tareas.append(item)

        if max_tablas is not None and len(tareas) >= max_tablas:
            return tareas

    return tareas


# ============================================================
# DESCARGA Y PARSEO CSV
# ============================================================

def get_text(url):
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text, response.url


def get_bytes(url):
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response.content, response.url, response.headers.get("content-type")


def extraer_urls_csv_desde_html(html, base_url):
    """
    Extrae enlaces CSV desde la página dlgExport.htm.
    Se prioriza CSV separado por punto y coma, porque es más cómodo
    para procesarlo como CSV estándar en España.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidatos = []

    for enlace in soup.find_all("a", href=True):
        href = urljoin(base_url, enlace["href"])
        texto = enlace.get_text(" ", strip=True).lower()
        href_lower = href.lower()

        if "csv" not in href_lower:
            continue

        prioridad = 50
        formato = "csv"

        if "csv_bdsc" in href_lower or ";" in texto or "punto y coma" in texto:
            prioridad = 10
            formato = "csv_punto_y_coma"
        elif "csv_bd" in href_lower or "tabul" in texto:
            prioridad = 20
            formato = "csv_tabulado"

        candidatos.append({
            "url": href,
            "formato": formato,
            "prioridad": prioridad,
            "texto_enlace": texto
        })

    candidatos.sort(key=lambda item: item["prioridad"])
    return candidatos


def generar_candidatos_csv_por_url(href_tabla, id_tabla):
    """
    Plan B por si la página de exportación no expone bien los enlaces.
    Cubre los patrones observados en JAXI/JAXIT3.
    """
    candidatos = []
    parsed = urlparse(href_tabla)
    path_lower = parsed.path.lower()

    if id_tabla:
        if "jaxit3" in path_lower:
            candidatos.extend([
                {"url": f"{DOMINIO_INE}/jaxiT3/files/t/es/csv/{id_tabla}.csv?nocab=1", "formato": "csv_tabulado", "prioridad": 30},
                {"url": f"{DOMINIO_INE}/jaxiT3/files/t/es/csv_bd/{id_tabla}.csv", "formato": "csv_tabulado", "prioridad": 40},
                {"url": f"{DOMINIO_INE}/jaxiT3/files/t/es/csv_bdsc/{id_tabla}.csv", "formato": "csv_punto_y_coma", "prioridad": 35},
            ])
        else:
            candidatos.extend([
                {"url": f"{DOMINIO_INE}/jaxi/files/tpx/es/csv_bdsc/{id_tabla}.csv", "formato": "csv_punto_y_coma", "prioridad": 35},
                {"url": f"{DOMINIO_INE}/jaxi/files/tpx/es/csv_bd/{id_tabla}.csv", "formato": "csv_tabulado", "prioridad": 40},
            ])

    return candidatos


def decodificar_csv(contenido_bytes):
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return contenido_bytes.decode(encoding), encoding
        except UnicodeDecodeError:
            continue

    return contenido_bytes.decode("utf-8", errors="replace"), "utf-8-replace"


def detectar_delimitador(texto_csv, formato_preferido=None):
    if formato_preferido == "csv_punto_y_coma":
        return ";"
    if formato_preferido == "csv_tabulado":
        return "\t"

    muestra = texto_csv[:5000]
    try:
        dialect = csv.Sniffer().sniff(muestra, delimiters=[";", "\t", ","])
        return dialect.delimiter
    except csv.Error:
        if ";" in muestra:
            return ";"
        if "\t" in muestra:
            return "\t"
        return ","


def parsear_csv_a_dicts(texto_csv, formato_preferido=None):
    delimitador = detectar_delimitador(texto_csv, formato_preferido)
    buffer = io.StringIO(texto_csv)
    reader = csv.DictReader(buffer, delimiter=delimitador)

    filas = []
    for fila in reader:
        fila_limpia = {
            (clave or "").strip(): (valor.strip() if isinstance(valor, str) else valor)
            for clave, valor in fila.items()
        }
        filas.append(fila_limpia)

    return filas, delimitador, reader.fieldnames or []


def descargar_csv_desde_href(href_tabla, id_tabla=None):
    """
    1. Abre la URL href_tabla de exportación.
    2. Localiza los enlaces CSV disponibles.
    3. Descarga el CSV elegido en memoria.
    4. Devuelve filas parseadas como lista de diccionarios.
    """
    html, url_export_final = get_text(href_tabla)
    candidatos = extraer_urls_csv_desde_html(html, url_export_final)
    candidatos.extend(generar_candidatos_csv_por_url(href_tabla, id_tabla))
    candidatos.sort(key=lambda item: item.get("prioridad", 99))

    errores_candidatos = []

    for candidato in candidatos:
        try:
            contenido, url_csv_final, content_type = get_bytes(candidato["url"])
            texto_csv, encoding = decodificar_csv(contenido)
            filas, delimitador, columnas = parsear_csv_a_dicts(
                texto_csv,
                formato_preferido=candidato.get("formato")
            )

            if not columnas:
                raise ValueError("El CSV no contiene cabecera")

            return {
                "url_export": url_export_final,
                "url_csv": url_csv_final,
                "content_type": content_type,
                "encoding": encoding,
                "delimitador": delimitador,
                "columnas": columnas,
                "num_filas": len(filas),
                "datos_csv": filas
            }

        except Exception as e:
            errores_candidatos.append({
                "url": candidato.get("url"),
                "formato": candidato.get("formato"),
                "error": str(e)
            })

    raise RuntimeError(f"No se pudo descargar ningún CSV válido. Intentos: {errores_candidatos}")


# ============================================================
# PROCESAMIENTO DE UNA TABLA
# ============================================================

def procesar_tabla_desde_href(tarea):
    salida_base = {
        "Letra": tarea.get("Letra"),
        "Dato": tarea.get("Dato"),
        "href_operacion": tarea.get("href_operacion"),
        "parametros_url": tarea.get("parametros_url"),
        "titulo_tabla": tarea.get("titulo_tabla"),
        "href_tabla": tarea.get("href_tabla"),
        "id_tabla": tarea.get("id_tabla"),
        "url_api_original": tarea.get("url_api"),
        "error_api_original": tarea.get("error"),
        "fuente_descarga": "href_tabla_csv"
    }

    try:
        datos_descarga = descargar_csv_desde_href(
            href_tabla=tarea.get("href_tabla"),
            id_tabla=tarea.get("id_tabla")
        )

        return {
            **salida_base,
            "estado": "OK",
            "error": None,
            **datos_descarga
        }

    except requests.exceptions.HTTPError as e:
        return {**salida_base, "estado": "ERROR", "error": f"Error HTTP: {e}", "datos_csv": None}
    except requests.exceptions.ConnectionError:
        return {**salida_base, "estado": "ERROR", "error": "Error de conexión", "datos_csv": None}
    except requests.exceptions.Timeout:
        return {**salida_base, "estado": "ERROR", "error": "Timeout", "datos_csv": None}
    except requests.exceptions.RequestException as e:
        return {**salida_base, "estado": "ERROR", "error": f"Error requests: {e}", "datos_csv": None}
    except Exception as e:
        return {**salida_base, "estado": "ERROR", "error": f"Error inesperado: {e}", "datos_csv": None}


# ============================================================
# PROCESO PRINCIPAL CON HILOS
# ============================================================

def ejecutar_descarga_href_csv(
    input_json=INPUT_ERRORES,
    output_jsonl=OUTPUT_JSONL,
    output_errores=OUTPUT_ERRORES,
    max_tablas=None,
    num_hilos=None,
    sobrescribir=True,
    console_output=None
):
    tareas = preparar_tareas(input_json, max_tablas=max_tablas)

    if not tareas:
        print("[ERROR] No se han encontrado href_tabla válidos de INE/JAXI para descargar.")
        return

    cpu_total, hilos_calculados = calcular_hilos_trabajo()

    if num_hilos is None:
        num_hilos = hilos_calculados

    if num_hilos < 1:
        num_hilos = 1

    if sobrescribir:
        if os.path.exists(output_jsonl):
            os.remove(output_jsonl)
        if os.path.exists(output_errores):
            os.remove(output_errores)

    print(f"[INFO] CPU lógicas detectadas: {cpu_total}")
    print(f"[INFO] Hilos de trabajo calculados: {hilos_calculados}")
    print(f"[INFO] Hilos de trabajo usados: {num_hilos}")
    print(f"[INFO] Tablas candidatas desde href_tabla: {len(tareas)}")
    print(f"[INFO] Salida JSONL: {output_jsonl}")

    errores = []

    with ThreadPoolExecutor(max_workers=num_hilos) as executor:
        futuros = {
            executor.submit(procesar_tabla_desde_href, tarea): tarea
            for tarea in tareas
        }

        with tqdm(total=len(futuros), desc="DESCARGANDO CSV HREF INE", file=console_output) as pbar:
            for futuro in as_completed(futuros):
                resultado = futuro.result()

                if resultado.get("estado") == "OK":
                    append_jsonl(output_jsonl, resultado)
                else:
                    errores.append(resultado)

                pbar.update(1)

    guardar_json(output_errores, errores)

    print("==============================================")
    print("[OK] Descarga CSV desde href_tabla finalizada")
    print(f"[INFO] Tablas correctas: {len(tareas) - len(errores)}")
    print(f"[INFO] Tablas con error: {len(errores)}")
    print(f"[INFO] Datos guardados en: {output_jsonl}")
    print(f"[INFO] Errores guardados en: {output_errores}")
    print("==============================================")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Descarga CSV del INE usando href_tabla desde errores_api_ine.json y genera JSONL."
    )

    parser.add_argument("--input", default=INPUT_ERRORES)
    parser.add_argument("--output", default=OUTPUT_JSONL)
    parser.add_argument("--errores", default=OUTPUT_ERRORES)
    parser.add_argument("--max-tablas", type=int, default=None)
    parser.add_argument("--num-hilos", type=int, default=None)
    parser.add_argument("--append", action="store_true", help="No borra el JSONL/errores existentes antes de ejecutar.")

    args = parser.parse_args()

    ejecutar(
    input_json=args.input,
    output_jsonl=args.output,
    output_errores=args.errores,
    max_tablas=args.max_tablas,
    num_hilos=args.num_hilos,
    sobrescribir=not args.append
)


# ============================================================
# EJECUCIÓN DESDE OTROS MÓDULOS
# ============================================================
def ejecutar(
        input_json=INPUT_ERRORES,
        output_jsonl=OUTPUT_JSONL,
        output_errores=OUTPUT_ERRORES,
        max_tablas=None,
        num_hilos=None,
        sobrescribir=True):

    ejecutar_descarga_href_csv(
        input_json=input_json,
        output_jsonl=output_jsonl,
        output_errores=output_errores,
        max_tablas=max_tablas,
        num_hilos=num_hilos,
        sobrescribir=sobrescribir
    )


if __name__ == "__main__":
    main()
