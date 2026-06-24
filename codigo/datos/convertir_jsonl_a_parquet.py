import os
import json
import argparse
import pandas as pd

from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_JSONL = "./datos/normalizados/dataset_ine_normalizado_api.jsonl"
OUTPUT_PARQUET = "./datos/parquet/dataset_ine_normalizado_api.parquet"
OUTPUT_RESUMEN = "./datos/parquet/resumen_parquet_api.json"

CHUNK_SIZE = 50000


# ============================================================
# UTILIDADES
# ============================================================

def asegurar_carpeta(path):
    carpeta = os.path.dirname(path)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)


def guardar_json(path, data):
    asegurar_carpeta(path)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def contar_lineas_jsonl(path):
    total = 0
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                total += 1
    return total


def calcular_hilos_trabajo():
    cpu_total = os.cpu_count() or 1
    restantes = max(cpu_total - 1, 0)
    num_hilos_trabajo = (restantes // 2) + 1
    return cpu_total, num_hilos_trabajo


def generar_chunks_jsonl(path, chunk_size):
    """
    Lee el JSONL en bloques de líneas para procesarlo en paralelo.
    """
    chunk = []
    numero_chunk = 0

    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            chunk.append(line)

            if len(chunk) >= chunk_size:
                numero_chunk += 1
                yield numero_chunk, chunk
                chunk = []

    if chunk:
        numero_chunk += 1
        yield numero_chunk, chunk


# ============================================================
# PROCESAMIENTO DE CHUNKS
# ============================================================

def ajustar_tipos_dataframe(df):
    """
    Ajusta tipos antes de guardar en Parquet.
    """
    columnas_string = [
        "letra",
        "dato_operacion",
        "href_operacion",
        "c",
        "cid",
        "idp",
        "id_tabla",
        "titulo_tabla",
        "href_tabla",
        "url_api",
        "nombre_serie",
        "codigo_serie",
        "unidad",
        "periodo",
        "fecha",
        "datos_periodo_raw",
        "metadata_serie_raw"
    ]

    for col in columnas_string:
        if col in df.columns:
            df[col] = df[col].astype("string")

    if "anyo" in df.columns:
        df["anyo"] = pd.to_numeric(df["anyo"], errors="coerce").astype("Int64")

    if "valor" in df.columns:
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce")

    return df


def procesar_chunk(numero_chunk, lineas):
    """
    Convierte un bloque de líneas JSONL en DataFrame.
    """
    registros = []

    for indice_linea, line in enumerate(lineas, start=1):
        try:
            registros.append(json.loads(line))
        except json.JSONDecodeError as e:
            # Si una línea está mal, la ignoramos en el dataframe,
            # pero devolvemos el error para el resumen.
            pass

    if not registros:
        return numero_chunk, pd.DataFrame(), {
            "numero_chunk": numero_chunk,
            "filas": 0,
            "error": "Chunk sin registros válidos"
        }

    df = pd.DataFrame(registros)
    df = ajustar_tipos_dataframe(df)

    info = {
        "numero_chunk": numero_chunk,
        "filas": int(len(df)),
        "columnas": int(len(df.columns))
    }

    return numero_chunk, df, info


# ============================================================
# CONVERSIÓN JSONL -> PARQUET CON HILOS
# ============================================================

def convertir_jsonl_a_parquet_hilos(
    input_jsonl=INPUT_JSONL,
    output_parquet=OUTPUT_PARQUET,
    output_resumen=OUTPUT_RESUMEN,
    chunk_size=CHUNK_SIZE,
    num_hilos=None
):
    if not os.path.exists(input_jsonl):
        print(f"[ERROR] No existe el fichero de entrada: {input_jsonl}")
        return None

    asegurar_carpeta(output_parquet)
    asegurar_carpeta(output_resumen)

    cpu_total, hilos_calculados = calcular_hilos_trabajo()

    if num_hilos is None:
        num_hilos = hilos_calculados

    if num_hilos < 1:
        num_hilos = 1

    print("==============================================")
    print(" CONVERSIÓN JSONL NORMALIZADO -> PARQUET CON HILOS")
    print("==============================================")
    print(f"[INFO] Entrada JSONL: {input_jsonl}")
    print(f"[INFO] Salida Parquet: {output_parquet}")
    print(f"[INFO] CPU lógicas detectadas: {cpu_total}")
    print(f"[INFO] Hilos calculados: {hilos_calculados}")
    print(f"[INFO] Hilos usados: {num_hilos}")
    print(f"[INFO] Tamaño chunk: {chunk_size}")

    total_lineas = contar_lineas_jsonl(input_jsonl)
    print(f"[INFO] Filas detectadas en JSONL: {total_lineas}")

    chunks = list(generar_chunks_jsonl(input_jsonl, chunk_size))
    print(f"[INFO] Chunks generados: {len(chunks)}")

    dataframes_por_chunk = {}
    info_chunks = []

    with ThreadPoolExecutor(max_workers=num_hilos) as executor:
        futuros = {
            executor.submit(procesar_chunk, numero_chunk, lineas): numero_chunk
            for numero_chunk, lineas in chunks
        }

        with tqdm(total=len(futuros), desc="PROCESANDO CHUNKS") as pbar:
            for futuro in as_completed(futuros):
                numero_chunk = futuros[futuro]

                try:
                    _, df_chunk, info = futuro.result()
                    dataframes_por_chunk[numero_chunk] = df_chunk
                    info_chunks.append(info)

                except Exception as e:
                    dataframes_por_chunk[numero_chunk] = pd.DataFrame()
                    info_chunks.append({
                        "numero_chunk": numero_chunk,
                        "filas": 0,
                        "error": f"Error no controlado en hilo: {e}"
                    })

                pbar.update(1)

    print("[INFO] Consolidando chunks...")
    dataframes_ordenados = [
        dataframes_por_chunk[numero_chunk]
        for numero_chunk in sorted(dataframes_por_chunk.keys())
        if not dataframes_por_chunk[numero_chunk].empty
    ]

    if not dataframes_ordenados:
        print("[ERROR] No se generó ningún DataFrame válido.")
        return None

    df = pd.concat(dataframes_ordenados, ignore_index=True)
    df = ajustar_tipos_dataframe(df)

    print("[INFO] Guardando Parquet...")
    df.to_parquet(
        output_parquet,
        index=False,
        engine="pyarrow",
        compression="snappy"
    )

    resumen = {
        "input_jsonl": input_jsonl,
        "output_parquet": output_parquet,
        "total_lineas_jsonl": total_lineas,
        "total_filas_dataframe": int(len(df)),
        "total_columnas": int(len(df.columns)),
        "chunk_size": chunk_size,
        "num_chunks": len(chunks),
        "cpu_total": cpu_total,
        "hilos_calculados": hilos_calculados,
        "hilos_usados": num_hilos,
        "columnas": list(df.columns),
        "tipos_datos": {
            columna: str(tipo)
            for columna, tipo in df.dtypes.items()
        },
        "nulos_por_columna": {
            columna: int(df[columna].isna().sum())
            for columna in df.columns
        },
        "info_chunks": sorted(info_chunks, key=lambda x: x["numero_chunk"]),
        "memoria_dataframe_mb": round(df.memory_usage(deep=True).sum() / (1024 * 1024), 2),
        "tamano_parquet_mb": round(os.path.getsize(output_parquet) / (1024 * 1024), 2)
    }

    guardar_json(output_resumen, resumen)

    print("==============================================")
    print("[OK] Conversión finalizada")
    print(f"[INFO] Filas guardadas: {len(df)}")
    print(f"[INFO] Columnas: {len(df.columns)}")
    print(f"[INFO] Parquet: {output_parquet}")
    print(f"[INFO] Resumen: {output_resumen}")
    print(f"[INFO] Tamaño Parquet MB: {resumen['tamano_parquet_mb']}")
    print("==============================================")

    return resumen


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convierte dataset_ine_normalizado_hilos.jsonl a Parquet usando hilos."
    )

    parser.add_argument("--input", default=INPUT_JSONL)
    parser.add_argument("--output", default=OUTPUT_PARQUET)
    parser.add_argument("--resumen", default=OUTPUT_RESUMEN)
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--num-hilos", type=int, default=None)

    args = parser.parse_args()

    ejecutar(
        input_jsonl=args.input,
        output_parquet=args.output,
        output_resumen=args.resumen,
        chunk_size=args.chunk_size,
        num_hilos=args.num_hilos
    )


# ============================================================
# EJECUCIÓN DESDE OTROS MÓDULOS
# ============================================================

def ejecutar(
        input_jsonl=INPUT_JSONL,
        output_parquet=OUTPUT_PARQUET,
        output_resumen=OUTPUT_RESUMEN,
        chunk_size=CHUNK_SIZE,
        num_hilos=None):

    return convertir_jsonl_a_parquet_hilos(
        input_jsonl=input_jsonl,
        output_parquet=output_parquet,
        output_resumen=output_resumen,
        chunk_size=chunk_size,
        num_hilos=num_hilos
    )


if __name__ == "__main__":
    main()
