# ============================================================
# CONFIGURACION GENERAL DEL SISTEMA INE
# ============================================================
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_INDEX = (
    BASE_DIR
    / "datos"
    / "semanticos"
    / "index_ine.faiss"
)

INPUT_METADATA = (
    BASE_DIR
    / "datos"
    / "semanticos"
    / "metadata_ine.jsonl"
)

INPUT_DUCKDB = (
    BASE_DIR
    / "datos"
    / "duckdb"
    / "ine_dataset.duckdb"
)

NOMBRE_TABLA_DUCKDB = "dataset_ine"
MODELO_EMBEDDINGS = "sentence-transformers/all-MiniLM-L6-v2"
MODELO_LLM = "gpt-4.1-mini"

TOP_K_FINAL = 12
FACTOR_CANDIDATOS_FAISS = 20
SCORE_FINAL_MINIMO = 0.40
LIMITE_POR_CANDIDATO = 30

# Valores alternativos utilizados durante las pruebas:
#
# TOP_K_FINAL = 20
# FACTOR_CANDIDATOS_FAISS = 50
# SCORE_FINAL_MINIMO = 0.25
# LIMITE_POR_CANDIDATO = 50