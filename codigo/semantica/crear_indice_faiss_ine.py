import json
import os
import argparse
import time

import faiss

from tqdm import tqdm
from sentence_transformers import SentenceTransformer


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_JSONL = "./datos/semanticos/dataset_ine_semantico_por_tabla.jsonl"

OUTPUT_INDEX = "./datos/semanticos/index_ine.faiss"
OUTPUT_METADATA = "./datos/semanticos/metadata_ine.jsonl"
OUTPUT_RESUMEN = "./datos/semanticos/resumen_faiss_ine.json"

MODELO_EMBEDDINGS = "sentence-transformers/all-MiniLM-L6-v2"

BATCH_SIZE = 1024


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


def contar_lineas_jsonl(path):
    total = 0

    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                total += 1

    return total


def generar_batches_jsonl(path, batch_size, max_lineas=None):
    textos = []
    metadatos = []
    ids_documento = []

    total_leidas = 0

    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            if max_lineas is not None and total_leidas >= max_lineas:
                break

            line = line.strip()

            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            texto = data.get("texto")
            metadata = data.get("metadata", {})
            id_documento = data.get("id_documento")

            if not texto:
                continue

            textos.append(texto)
            metadatos.append(metadata)
            ids_documento.append(id_documento)
            total_leidas += 1

            if len(textos) >= batch_size:
                yield textos, metadatos, ids_documento
                textos = []
                metadatos = []
                ids_documento = []

    if textos:
        yield textos, metadatos, ids_documento


def detectar_dispositivo():
    """
    Usa GPU si sentence-transformers/torch la detecta.
    Si no, usa CPU.
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"

    except Exception:
        pass

    return "cpu"


# ============================================================
# CREACIÓN FAISS OPTIMIZADA
# ============================================================

def crear_indice_faiss_optimizado(
    input_jsonl=INPUT_JSONL,
    output_index=OUTPUT_INDEX,
    output_metadata=OUTPUT_METADATA,
    output_resumen=OUTPUT_RESUMEN,
    modelo_nombre=MODELO_EMBEDDINGS,
    batch_size=BATCH_SIZE,
    max_lineas=None,
    normalizar=True,
    sobrescribir=True
):
    if not os.path.exists(input_jsonl):
        print(f"[ERROR] No existe el fichero de entrada: {input_jsonl}")
        return None

    asegurar_carpeta(output_index)
    asegurar_carpeta(output_metadata)
    asegurar_carpeta(output_resumen)

    if sobrescribir:
        borrar_si_existe(output_index)
        borrar_si_existe(output_metadata)
        borrar_si_existe(output_resumen)

    total_lineas = contar_lineas_jsonl(input_jsonl)

    if max_lineas is not None:
        total_objetivo = min(total_lineas, max_lineas)
    else:
        total_objetivo = total_lineas

    dispositivo = detectar_dispositivo()

    print("==============================================")
    print(" CREACIÓN ÍNDICE FAISS OPTIMIZADO")
    print("==============================================")
    print(f"[INFO] Entrada JSONL: {input_jsonl}")
    print(f"[INFO] Índice FAISS:  {output_index}")
    print(f"[INFO] Metadata:      {output_metadata}")
    print(f"[INFO] Modelo:        {modelo_nombre}")
    print(f"[INFO] Dispositivo:   {dispositivo}")
    print(f"[INFO] Batch size:    {batch_size}")
    print(f"[INFO] Total docs:    {total_objetivo}")

    print("[INFO] Cargando modelo de embeddings...")
    modelo = SentenceTransformer(modelo_nombre, device=dispositivo)

    indice = None
    dimension = None

    total_documentos = 0
    total_batches = 0

    tiempo_inicio = time.time()

    print("[INFO] Generando embeddings por batches...")

    with open(output_metadata, "w", encoding="utf-8") as metadata_file:
        with tqdm(total=total_objetivo, desc="EMBEDDINGS + FAISS") as pbar:
            for textos, metadatos, ids_documento in generar_batches_jsonl(
                input_jsonl,
                batch_size=batch_size,
                max_lineas=max_lineas
            ):
                embeddings = modelo.encode(
                    textos,
                    batch_size=batch_size,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    normalize_embeddings=normalizar
                )

                embeddings = embeddings.astype("float32")

                if indice is None:
                    dimension = embeddings.shape[1]

                    if normalizar:
                        # Con embeddings normalizados, producto interno equivale a similitud coseno
                        indice = faiss.IndexFlatIP(dimension)
                    else:
                        indice = faiss.IndexFlatL2(dimension)

                indice.add(embeddings)

                for id_documento, metadata in zip(ids_documento, metadatos):
                    registro_metadata = {
                        "posicion": total_documentos,
                        "id_documento": id_documento,
                        "metadata": metadata
                    }
                    metadata_file.write(json.dumps(registro_metadata, ensure_ascii=False) + "\n")
                    total_documentos += 1

                total_batches += 1
                pbar.update(len(textos))

    print("[INFO] Guardando índice FAISS...")
    faiss.write_index(indice, output_index)

    tiempo_total = round(time.time() - tiempo_inicio, 2)

    resumen = {
        "input_jsonl": input_jsonl,
        "output_index": output_index,
        "output_metadata": output_metadata,
        "modelo": modelo_nombre,
        "dispositivo": dispositivo,
        "batch_size": batch_size,
        "normalizar_embeddings": normalizar,
        "tipo_indice": "IndexFlatIP" if normalizar else "IndexFlatL2",
        "dimension": int(dimension) if dimension is not None else None,
        "total_documentos_indexados": int(total_documentos),
        "total_batches": int(total_batches),
        "tiempo_total_segundos": tiempo_total,
        "tiempo_total_minutos": round(tiempo_total / 60, 2),
        "documentos_por_segundo": round(total_documentos / tiempo_total, 2) if tiempo_total > 0 else None,
        "tamano_index_mb": round(os.path.getsize(output_index) / (1024 * 1024), 2),
        "tamano_metadata_mb": round(os.path.getsize(output_metadata) / (1024 * 1024), 2)
    }

    guardar_json(output_resumen, resumen)

    print("==============================================")
    print("[OK] Índice FAISS creado correctamente")
    print(f"[INFO] Documentos indexados: {total_documentos}")
    print(f"[INFO] Dimensión embeddings: {dimension}")
    print(f"[INFO] Tiempo total minutos: {resumen['tiempo_total_minutos']}")
    print(f"[INFO] Docs/segundo: {resumen['documentos_por_segundo']}")
    print(f"[INFO] Índice: {output_index}")
    print(f"[INFO] Metadata: {output_metadata}")
    print(f"[INFO] Resumen: {output_resumen}")
    print("==============================================")

    return resumen


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Crea un índice FAISS optimizado desde el dataset semántico del INE."
    )

    parser.add_argument("--input", default=INPUT_JSONL)
    parser.add_argument("--index", default=OUTPUT_INDEX)
    parser.add_argument("--metadata", default=OUTPUT_METADATA)
    parser.add_argument("--resumen", default=OUTPUT_RESUMEN)
    parser.add_argument("--modelo", default=MODELO_EMBEDDINGS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--max-lineas", type=int, default=None)

    parser.add_argument(
        "--no-normalizar",
        action="store_true",
        help="No normaliza embeddings. Si se usa, FAISS utilizará L2 en vez de similitud coseno."
    )

    args = parser.parse_args()

    ejecutar(
        input_jsonl=args.input,
        output_index=args.index,
        output_metadata=args.metadata,
        output_resumen=args.resumen,
        modelo_nombre=args.modelo,
        batch_size=args.batch_size,
        max_lineas=args.max_lineas,
        normalizar=not args.no_normalizar
    )


# ============================================================
# EJECUCIÓN DESDE OTROS MÓDULOS
# ============================================================
def ejecutar(
        input_jsonl=INPUT_JSONL,
        output_index=OUTPUT_INDEX,
        output_metadata=OUTPUT_METADATA,
        output_resumen=OUTPUT_RESUMEN,
        modelo_nombre=MODELO_EMBEDDINGS,
        batch_size=BATCH_SIZE,
        max_lineas=None,
        normalizar=True,
        sobrescribir=True):

    return crear_indice_faiss_optimizado(
        input_jsonl=input_jsonl,
        output_index=output_index,
        output_metadata=output_metadata,
        output_resumen=output_resumen,
        modelo_nombre=modelo_nombre,
        batch_size=batch_size,
        max_lineas=max_lineas,
        normalizar=normalizar,
        sobrescribir=sobrescribir
    )

if __name__ == "__main__":
    main()
