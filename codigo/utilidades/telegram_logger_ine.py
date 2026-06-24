import os
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

LOG_DIR = BASE_DIR / "registros" / "respuesta"

LOG_DIR_RESULTADOS = BASE_DIR / "resultados" / "consultas"

# ============================================================
# REGISTRO DE CONSULTAS TELEGRAM
# ============================================================

def crear_fichero_log_telegram():
    os.makedirs(LOG_DIR, exist_ok=True)

    nombre = datetime.now().strftime("consultas_telegram_%Y%m%d_%H%M%S.jsonl")
    return os.path.join(LOG_DIR, nombre)


def extraer_resumen_pilares(resultado):
    resumen = {}

    resultados_por_pilar = resultado.get("resultados_por_pilar", {}) or {}

    for pilar, resultados in resultados_por_pilar.items():
        resumen[pilar] = []

        if isinstance(resultados, dict):
            resultados = [resultados]

        for item in resultados:
            contexto_llm = item.get("contexto_llm", {}) or {}
            datos = contexto_llm.get("datos_recuperados", []) or []

            resumen[pilar].append({
                "pregunta": item.get("pregunta"),
                "total_series_enviadas_llm": contexto_llm.get("resumen_recuperacion", {}).get("total_series_enviadas_llm"),
                "tablas_recuperadas": [
                    {
                        "id_tabla": bloque.get("id_tabla"),
                        "operacion": bloque.get("operacion"),
                        "serie": bloque.get("serie"),
                        "relevancia": bloque.get("relevancia"),
                        "rank_faiss": bloque.get("rank_faiss"),
                    }
                    for bloque in datos
                ]
            })

    return resumen


def escribir_log_telegram(path_log, chat_id, pregunta_usuario, resultado, cobertura):
    if not path_log:
        return

    if resultado.get("error"):
        return

    if not resultado.get("resultados_por_pilar"):
        return

    registro = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "chat_id": chat_id,
        "pregunta_usuario": pregunta_usuario,
        "negocio": resultado.get("negocio"),
        "territorio": resultado.get("territorio"),
        "cobertura": cobertura.get("nivel"),
        "porcentaje_cobertura": cobertura.get("porcentaje"),
        "puntuacion_datos": {
            "puntuacion_total": cobertura.get("puntuacion_total"),
            "puntuacion_maxima": cobertura.get("puntuacion_maxima"),
        },
        "puntos_pilares": cobertura.get("detalle_pilares", {}),
        "consultas_generadas": resultado.get("consultas", {}),
        "resumen_recuperacion_por_pilar": extraer_resumen_pilares(resultado),
    }

    with open(path_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        
# ============================================================
# LOG RESUMIDO DE RESULTADOS PARA ANÁLISIS POSTERIOR
# ============================================================

def crear_fichero_resultados_telegram():
    os.makedirs(LOG_DIR_RESULTADOS, exist_ok=True)

    nombre = datetime.now().strftime("resultados_telegram_%Y%m%d_%H%M%S.jsonl")
    return os.path.join(LOG_DIR_RESULTADOS, nombre)


def escribir_log_resultados_telegram(path_resultados, chat_id, pregunta_usuario, resultado, cobertura):
    if not path_resultados:
        return

    if resultado.get("error"):
        return

    detalle = cobertura.get("detalle_pilares", {}) or {}

    registro = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "chat_id": chat_id,
        "pregunta_usuario": pregunta_usuario,
        "negocio": resultado.get("negocio"),
        "territorio": resultado.get("territorio"),
        "cobertura_porcentaje": cobertura.get("porcentaje"),
        "nivel_fiabilidad": cobertura.get("nivel"),
        "puntuacion_total": cobertura.get("puntuacion_total"),
        "puntuacion_maxima": cobertura.get("puntuacion_maxima"),
        "pilar_mercado": detalle.get("mercado"),
        "pilar_demografia": detalle.get("demografia"),
        "pilar_economia": detalle.get("economia"),
        "pilar_laboral": detalle.get("laboral"),
        "pilar_empresas": detalle.get("empresas"),
        "pilar_actividad_empresarial": detalle.get("actividad_empresarial"),
        "pilar_sector_negocio": detalle.get("sector_negocio"),
        "pilar_turismo": detalle.get("turismo"),
    }

    with open(path_resultados, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    
    print(f"[OK] Log resumido guardado en: {path_resultados}")