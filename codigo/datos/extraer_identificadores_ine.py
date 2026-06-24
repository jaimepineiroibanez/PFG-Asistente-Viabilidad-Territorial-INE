import json
import os
import argparse
import requests

from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_JSON = "./datos/originales/resultado_indice_url.json"
OUTPUT_JSON = "./datos/originales/resultado_indice_identificadores.json"

DOMINIO_URL = "https://www.ine.es"

HEADERS = {
    "User-Agent": "PFG-Scraper-INE"
}

TIMEOUT = 15


# ============================================================
# UTILIDADES DE FICHEROS
# ============================================================

def cargar_json(path):
    """Carga un fichero JSON."""
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def guardar_json(data, path):
    """Guarda un fichero JSON creando la carpeta si no existe."""
    carpeta = os.path.dirname(path)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


# ============================================================
# UTILIDADES DE URL / HTML
# ============================================================

def get_html(url):
    """Descarga una página HTML y devuelve su contenido."""
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return response.text


def extraer_parametros_url(url):
    """
    Extrae parámetros útiles directamente desde la URL del INEbase.

    Ejemplo:
    https://www.ine.es/dyngs/INEbase/operacion.htm?c=Estadistica_C&cid=1254736176802&idp=1254735976607
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    return {
        clave: valores[0]
        for clave, valores in params.items()
        if valores
    }


def normalizar_url(href, base_url=DOMINIO_URL):
    """Convierte un href relativo en URL absoluta."""
    return urljoin(base_url, href)


# ============================================================
# EXTRACCIÓN DE IDENTIFICADORES
# ============================================================

def extraer_id_tabla_desde_url(url):
    """
    Intenta extraer el identificador de tabla desde una URL.

    Casos habituales:
    - ?t=12345
    - ?tpx=12345
    - ?file=12345.px
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    if "t" in params:
        return params["t"][0]

    if "tpx" in params:
        return params["tpx"][0]

    if "file" in params:
        file_value = params["file"][0]
        if file_value.endswith(".px"):
            return file_value.replace(".px", "")

    return None


def extraer_identificadores_enlaces(html):
    """
    Busca enlaces dentro de la página y extrae posibles identificadores
    de tablas INE/Tempus/PC-Axis.
    """
    soup = BeautifulSoup(html, "html.parser")
    tablas = []

    for enlace in soup.find_all("a", href=True):
        href = normalizar_url(enlace["href"])
        texto = enlace.get_text(" ", strip=True)

        id_tabla = extraer_id_tabla_desde_url(href)

        if id_tabla:
            tablas.append({
                "titulo_tabla": texto,
                "href": href,
                "id_tabla": id_tabla
            })

    return tablas


def procesar_operacion(item):
    """
    Procesa una operación del resultado_indice_url.json.

    Devuelve:
    {
        "Dato": "...",
        "href": "...",
        "parametros_url": {...},
        "tablas_encontradas": [...],
        "estado": "OK" / "ERROR",
        "error": null / "..."
    }
    """
    dato = item.get("Dato")
    href = item.get("href")

    salida = {
        "Dato": dato,
        "href": href,
        "parametros_url": extraer_parametros_url(href) if href else {},
        "tablas_encontradas": [],
        "estado": "OK",
        "error": None
    }

    if not href:
        salida["estado"] = "ERROR"
        salida["error"] = "No existe href"
        return salida

    try:
        html = get_html(href)
        salida["tablas_encontradas"] = extraer_identificadores_enlaces(html)

    except requests.exceptions.HTTPError as e:
        salida["estado"] = "ERROR"
        salida["error"] = f"Error HTTP: {e}"

    except requests.exceptions.ConnectionError:
        salida["estado"] = "ERROR"
        salida["error"] = "Error de conexión"

    except requests.exceptions.Timeout:
        salida["estado"] = "ERROR"
        salida["error"] = "Timeout"

    except requests.exceptions.RequestException as e:
        salida["estado"] = "ERROR"
        salida["error"] = f"Error requests: {e}"

    except Exception as e:
        salida["estado"] = "ERROR"
        salida["error"] = f"Error inesperado: {e}"

    return salida


# ============================================================
# HILOS
# ============================================================

def calcular_hilos_trabajo():
    """
    Calcula el número de hilos con la fórmula indicada:

    cpu_total = os.cpu_count() or 1
    restantes = max(cpu_total - 1, 0)
    num_hilos_trabajo = (restantes // 2) + 1
    """
    cpu_total = os.cpu_count() or 1
    restantes = max(cpu_total - 1, 0)
    num_hilos_trabajo = (restantes // 2) + 1

    return cpu_total, num_hilos_trabajo


def preparar_tareas(datos, max_operaciones=None):
    """
    Convierte la estructura por letras en una lista plana de tareas.

    Cada tarea contiene:
    - indice_bloque
    - indice_operacion
    - item
    """
    tareas = []

    for indice_bloque, bloque in enumerate(datos):
        operaciones = bloque.get("resultado_indice", [])

        for indice_operacion, item in enumerate(operaciones):
            tareas.append({
                "indice_bloque": indice_bloque,
                "indice_operacion": indice_operacion,
                "item": item
            })

            if max_operaciones is not None and len(tareas) >= max_operaciones:
                return tareas

    return tareas


def crear_estructura_salida(datos, tareas):
    """
    Crea la estructura de salida manteniendo las letras originales,
    pero solo con las operaciones que se van a procesar.
    """
    indices_por_bloque = {}

    for tarea in tareas:
        indice_bloque = tarea["indice_bloque"]
        indice_operacion = tarea["indice_operacion"]

        indices_por_bloque.setdefault(indice_bloque, set()).add(indice_operacion)

    salida = []

    for indice_bloque, bloque in enumerate(datos):
        if indice_bloque not in indices_por_bloque:
            continue

        salida.append({
            "Letra": bloque.get("Letra"),
            "resultado_indice": [None] * len(indices_por_bloque[indice_bloque]),
            "_mapa_indices": {
                indice_original: indice_salida
                for indice_salida, indice_original in enumerate(
                    sorted(indices_por_bloque[indice_bloque])
                )
            },
            "_indice_bloque_original": indice_bloque
        })

    mapa_bloques = {
        bloque_salida["_indice_bloque_original"]: indice_salida
        for indice_salida, bloque_salida in enumerate(salida)
    }

    return salida, mapa_bloques


def limpiar_campos_internos(resultado):
    """Elimina campos internos auxiliares antes de guardar el JSON."""
    for bloque in resultado:
        bloque.pop("_mapa_indices", None)
        bloque.pop("_indice_bloque_original", None)


# ============================================================
# RECORRIDO CONCURRENTE DEL JSON DE ÍNDICE
# ============================================================

def recorrer_resultado_indice(input_json, max_operaciones=None, num_hilos=None, console_output=None):
    """
    Recorre el JSON generado por el scraper del índice A-Z usando hilos.

    Mantiene la estructura final por letras:
    [
        {
            "Letra": "A",
            "resultado_indice": [...]
        }
    ]
    """
    datos = cargar_json(input_json)
    tareas = preparar_tareas(datos, max_operaciones=max_operaciones)

    if not tareas:
        print("[ERROR] No hay tareas para procesar")
        return []

    cpu_total, hilos_calculados = calcular_hilos_trabajo()

    if num_hilos is None:
        num_hilos = hilos_calculados

    if num_hilos < 1:
        num_hilos = 1

    print(f"[INFO] CPU lógicas detectadas: {cpu_total}")
    print(f"[INFO] Hilos de trabajo calculados: {hilos_calculados}")
    print(f"[INFO] Hilos de trabajo usados: {num_hilos}")
    print(f"[INFO] Total operaciones a procesar: {len(tareas)}")

    resultado, mapa_bloques = crear_estructura_salida(datos, tareas)

    with ThreadPoolExecutor(max_workers=num_hilos) as executor:
        futuros = {
            executor.submit(procesar_operacion, tarea["item"]): tarea
            for tarea in tareas
        }

        with tqdm(total=len(futuros), desc="EXTRAYENDO IDENTIFICADORES", file=console_output) as pbar:
            for futuro in as_completed(futuros):
                tarea = futuros[futuro]

                try:
                    resultado_operacion = futuro.result()
                except Exception as e:
                    item = tarea["item"]
                    resultado_operacion = {
                        "Dato": item.get("Dato"),
                        "href": item.get("href"),
                        "parametros_url": extraer_parametros_url(item.get("href")) if item.get("href") else {},
                        "tablas_encontradas": [],
                        "estado": "ERROR",
                        "error": f"Error no controlado en hilo: {e}"
                    }

                indice_bloque_original = tarea["indice_bloque"]
                indice_operacion_original = tarea["indice_operacion"]

                indice_bloque_salida = mapa_bloques[indice_bloque_original]
                bloque_salida = resultado[indice_bloque_salida]

                indice_operacion_salida = bloque_salida["_mapa_indices"][indice_operacion_original]
                bloque_salida["resultado_indice"][indice_operacion_salida] = resultado_operacion

                pbar.update(1)

    limpiar_campos_internos(resultado)
    return resultado


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Recorre resultado_indice_url.json y extrae identificadores de operación y tablas con hilos."
    )

    parser.add_argument(
        "--input",
        default=INPUT_JSON,
        help=f"Ruta del JSON de entrada. Por defecto: {INPUT_JSON}"
    )

    parser.add_argument(
        "--output",
        default=OUTPUT_JSON,
        help=f"Ruta del JSON de salida. Por defecto: {OUTPUT_JSON}"
    )

    parser.add_argument(
        "--max-operaciones",
        type=int,
        default=None,
        help="Número máximo de operaciones a procesar. Útil para pruebas."
    )

    parser.add_argument(
        "--num-hilos",
        type=int,
        default=None,
        help="Número de hilos manual. Si no se indica, se usa el cálculo automático."
    )

    args = parser.parse_args()

    print("==============================================")
    print(" EXTRACCIÓN DE IDENTIFICADORES INEBASE")
    print("==============================================")
    print(f"[INFO] Entrada: {args.input}")
    print(f"[INFO] Salida:  {args.output}")

    resultado = recorrer_resultado_indice(
        input_json=args.input,
        max_operaciones=args.max_operaciones,
        num_hilos=args.num_hilos
    )

    guardar_json(resultado, args.output)

    total_operaciones = sum(
        len(bloque.get("resultado_indice", []))
        for bloque in resultado
    )

    total_tablas = sum(
        len(item.get("tablas_encontradas", []))
        for bloque in resultado
        for item in bloque.get("resultado_indice", [])
    )

    print("==============================================")
    print("[OK] Proceso finalizado")
    print(f"[INFO] Operaciones procesadas: {total_operaciones}")
    print(f"[INFO] Tablas candidatas encontradas: {total_tablas}")
    print(f"[INFO] JSON generado: {args.output}")
    print("==============================================")


def ejecutar(
        input_json=INPUT_JSON,
        output_json=OUTPUT_JSON,
        max_operaciones=None,
        num_hilos=None):

    resultado = recorrer_resultado_indice(
        input_json=input_json,
        max_operaciones=max_operaciones,
        num_hilos=num_hilos
    )

    guardar_json(resultado, output_json)

    return resultado

if __name__ == "__main__":
    main()
