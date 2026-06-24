import json
import os
import argparse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_JSON = "./datos/originales/resultado_indice_identificadores.json"
OUTPUT_JSONL = "./datos/originales/datos_tablas_api_ine.jsonl"
OUTPUT_ERRORES = "./datos/originales/errores_api_ine.json"

BASE_API_INE = "https://servicios.ine.es/wstempus/js/ES"

HEADERS = {
    "User-Agent": "PFG-Scraper-INE/1.0 (j.pineiroi@alumnos.upm.es)"
}

TIMEOUT = 30


# ============================================================
# UTILIDADES
# ============================================================

def cargar_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def asegurar_carpeta(path):
    carpeta = os.path.dirname(path)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)


def calcular_hilos_trabajo():
    cpu_total = os.cpu_count() or 1
    restantes = max(cpu_total - 1, 0)
    num_hilos_trabajo = (restantes // 2) + 1
    return cpu_total, num_hilos_trabajo


def append_jsonl(path, data):
    asegurar_carpeta(path)
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False) + "\n")


def guardar_json(path, data):
    asegurar_carpeta(path)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


# ============================================================
# EXTRAER TAREAS DESDE resultado_indice_identificadores.json
# ============================================================

def preparar_tareas(input_json, max_tablas=None):
    datos = cargar_json(input_json)
    tareas = []
    ids_vistos = set()

    for bloque in datos:
        letra = bloque.get("Letra")

        for operacion in bloque.get("resultado_indice", []):
            dato = operacion.get("Dato")
            href_operacion = operacion.get("href")
            parametros_url = operacion.get("parametros_url", {})

            for tabla in operacion.get("tablas_encontradas", []):
                id_tabla = tabla.get("id_tabla")

                if not id_tabla:
                    continue

                # Evita descargar dos veces la misma tabla
                if id_tabla in ids_vistos:
                    continue

                ids_vistos.add(id_tabla)

                tareas.append({
                    "Letra": letra,
                    "Dato": dato,
                    "href_operacion": href_operacion,
                    "parametros_url": parametros_url,
                    "titulo_tabla": tabla.get("titulo_tabla"),
                    "href_tabla": tabla.get("href"),
                    "id_tabla": id_tabla
                })

                if max_tablas is not None and len(tareas) >= max_tablas:
                    return tareas

    return tareas


# ============================================================
# API INE
# ============================================================

def descargar_datos_tabla(id_tabla, nult=None, det=2, tip="AM"):
    """
    Llama al endpoint:
    /DATOS_TABLA/{id_tabla}

    Parámetros útiles:
    - nult: últimos N periodos
    - det: nivel de detalle
    - tip: formato/tipo de respuesta
    """
    url = f"{BASE_API_INE}/DATOS_TABLA/{id_tabla}"

    params = {
        "det": det,
        "tip": tip
    }

    if nult is not None:
        params["nult"] = nult

    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=TIMEOUT
    )

    response.raise_for_status()
    return response.url, response.json()


def procesar_tabla(tarea, nult=None, det=2, tip="AM"):
    id_tabla = tarea["id_tabla"]

    salida_base = {
        "Letra": tarea.get("Letra"),
        "Dato": tarea.get("Dato"),
        "href_operacion": tarea.get("href_operacion"),
        "parametros_url": tarea.get("parametros_url"),
        "titulo_tabla": tarea.get("titulo_tabla"),
        "href_tabla": tarea.get("href_tabla"),
        "id_tabla": id_tabla
    }

    try:
        url_api, datos_api = descargar_datos_tabla(
            id_tabla=id_tabla,
            nult=nult,
            det=det,
            tip=tip
        )

        return {
            **salida_base,
            "url_api": url_api,
            "estado": "OK",
            "error": None,
            "datos_api": datos_api
        }

    except requests.exceptions.HTTPError as e:
        return {
            **salida_base,
            "url_api": f"{BASE_API_INE}/DATOS_TABLA/{id_tabla}",
            "estado": "ERROR",
            "error": f"Error HTTP: {e}",
            "datos_api": None
        }

    except requests.exceptions.ConnectionError:
        return {
            **salida_base,
            "url_api": f"{BASE_API_INE}/DATOS_TABLA/{id_tabla}",
            "estado": "ERROR",
            "error": "Error de conexión",
            "datos_api": None
        }

    except requests.exceptions.Timeout:
        return {
            **salida_base,
            "url_api": f"{BASE_API_INE}/DATOS_TABLA/{id_tabla}",
            "estado": "ERROR",
            "error": "Timeout",
            "datos_api": None
        }

    except requests.exceptions.RequestException as e:
        return {
            **salida_base,
            "url_api": f"{BASE_API_INE}/DATOS_TABLA/{id_tabla}",
            "estado": "ERROR",
            "error": f"Error requests: {e}",
            "datos_api": None
        }

    except Exception as e:
        return {
            **salida_base,
            "url_api": f"{BASE_API_INE}/DATOS_TABLA/{id_tabla}",
            "estado": "ERROR",
            "error": f"Error inesperado: {e}",
            "datos_api": None
        }


# ============================================================
# PROCESO PRINCIPAL CON HILOS
# ============================================================

def ejecutar_descarga_api(
    input_json=INPUT_JSON,
    output_jsonl=OUTPUT_JSONL,
    output_errores=OUTPUT_ERRORES,
    max_tablas=None,
    nult=None,
    det=2,
    tip="AM",
    num_hilos=None,
    sobrescribir=True,
    console_output=None
):
    tareas = preparar_tareas(input_json, max_tablas=max_tablas)

    if not tareas:
        print("[ERROR] No se han encontrado tablas para descargar.")
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
    print(f"[INFO] Tablas a descargar: {len(tareas)}")
    print(f"[INFO] Salida JSONL: {output_jsonl}")

    errores = []

    with ThreadPoolExecutor(max_workers=num_hilos) as executor:
        futuros = {
            executor.submit(
                procesar_tabla,
                tarea,
                nult,
                det,
                tip
            ): tarea
            for tarea in tareas
        }

        with tqdm(total=len(futuros), desc="DESCARGANDO API INE", file=console_output) as pbar:
            for futuro in as_completed(futuros):
                resultado = futuro.result()

                if resultado.get("estado") == "OK":
                    append_jsonl(output_jsonl, resultado)
                else:
                    errores.append(resultado)

                pbar.update(1)

    guardar_json(output_errores, errores)

    print("==============================================")
    print("[OK] Descarga API finalizada")
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
        description="Descarga datos de tablas del INE usando /DATOS_TABLA/{id_tabla}."
    )

    parser.add_argument("--input", default=INPUT_JSON)
    parser.add_argument("--output", default=OUTPUT_JSONL)
    parser.add_argument("--errores", default=OUTPUT_ERRORES)

    parser.add_argument(
        "--max-tablas",
        type=int,
        default=None,
        help="Número máximo de tablas a descargar. Útil para pruebas."
    )

    parser.add_argument(
        "--nult",
        type=int,
        default=1,
        help="Últimos N periodos. Por defecto descarga solo el último periodo."
    )

    parser.add_argument("--det", type=int, default=2)
    parser.add_argument("--tip", default="AM")
    parser.add_argument("--num-hilos", type=int, default=None)

    args = parser.parse_args()

    ejecutar(
    input_json=args.input,
    output_jsonl=args.output,
    output_errores=args.errores,
    max_tablas=args.max_tablas,
    nult=args.nult,
    det=args.det,
    tip=args.tip,
    num_hilos=args.num_hilos
    )


# ============================================================
# EJECUCIÓN DESDE OTROS MÓDULOS
# ============================================================

def ejecutar(
        input_json=INPUT_JSON,
        output_jsonl=OUTPUT_JSONL,
        output_errores=OUTPUT_ERRORES,
        max_tablas=None,
        nult=None,
        det=2,
        tip="AM",
        num_hilos=None):

    ejecutar_descarga_api(
        input_json=input_json,
        output_jsonl=output_jsonl,
        output_errores=output_errores,
        max_tablas=max_tablas,
        nult=nult,
        det=det,
        tip=tip,
        num_hilos=num_hilos
    )


if __name__ == "__main__":
    main()
