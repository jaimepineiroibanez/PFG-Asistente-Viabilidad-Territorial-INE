import os
import re
import json

import faiss
from sentence_transformers import SentenceTransformer

from configuracion.config_ine import (
    TOP_K_FINAL,
    FACTOR_CANDIDATOS_FAISS,
    SCORE_FINAL_MINIMO
)

from codigo.utilidades.utils_ine import normalizar_texto

# ============================================================
# RECUPERACIÓN SEMÁNTICA MEDIANTE FAISS
# ============================================================

def cargar_indice_faiss(path_index):
    path_index = str(path_index)
    if not os.path.exists(path_index):
        raise FileNotFoundError(f"No existe el índice FAISS: {path_index}")

    print("[INFO] Cargando índice FAISS...")
    index = faiss.read_index(path_index)
    print(f"[INFO] Índice cargado. Vectores: {index.ntotal}")
    return index


def cargar_metadata_faiss(path_metadata):
    path_metadata = str(path_metadata)
    if not os.path.exists(path_metadata):
        raise FileNotFoundError(f"No existe metadata FAISS: {path_metadata}")

    print("[INFO] Cargando metadata FAISS...")
    metadata = []

    with open(path_metadata, "r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                metadata.append(json.loads(line))

    print(f"[INFO] Metadata cargada: {len(metadata)} registros")
    return metadata


def cargar_modelo_embeddings(nombre_modelo):
    print("[INFO] Cargando modelo de embeddings...")
    modelo = SentenceTransformer(nombre_modelo)
    print("[INFO] Modelo de embeddings cargado")
    return modelo


def generar_embedding_pregunta(modelo, pregunta):
    embedding = modelo.encode(
        [pregunta],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False
    )
    return embedding.astype("float32")

# ============================================================
# RECUPERACIÓN SEMÁNTICA MEDIANTE FAISS
# ============================================================

def detectar_sexo(pregunta_norm):
    if any(x in pregunta_norm for x in ["hombres", "hombre", "varones", "varon"]):
        return "hombres"

    if any(x in pregunta_norm for x in ["mujeres", "mujer"]):
        return "mujeres"

    return None


def detectar_edad(pregunta_norm):
    patrones = [
        r"de\s+\d+\s+a\s+\d+\s+anos",
        r"\d+\s+a\s+\d+\s+anos",
        r"\d+\s+y\s+mas\s+anos",
        r"menores\s+de\s+\d+\s+anos",
        r"mayores\s+de\s+\d+\s+anos",
        r"todas\s+las\s+edades"
    ]

    for patron in patrones:
        match = re.search(patron, pregunta_norm)
        if match:
            return match.group(0)

    return None


def extraer_filtros_basicos(pregunta):
    pregunta_norm = normalizar_texto(pregunta)
    filtros = {}

    match_anyo = re.search(r"\b(19\d{2}|20\d{2})\b", pregunta_norm)
    if match_anyo:
        filtros["anyo"] = int(match_anyo.group(1))

    sexo = detectar_sexo(pregunta_norm)
    if sexo:
        filtros["sexo"] = sexo

    edad = detectar_edad(pregunta_norm)
    if edad:
        filtros["edad"] = edad

    return filtros

# ============================================================
# DETECCIÓN DE FILTROS
# ============================================================

def construir_texto_meta_tabla(meta):
    return normalizar_texto(" ".join([
        str(meta.get("dato_operacion") or ""),
        str(meta.get("titulo_tabla") or ""),
        " ".join(meta.get("series_principales") or []),
        " ".join(meta.get("palabras_clave") or []),
        " ".join(meta.get("vocabulario") or []),
        " ".join(meta.get("unidades") or []),
        str(meta.get("anyo_min") or ""),
        str(meta.get("anyo_max") or "")
    ]))

def cumple_filtros(meta, filtros):
    if not filtros:
        return True

    texto_meta = construir_texto_meta_tabla(meta)

    if filtros.get("anyo") is not None:
        anyo = filtros["anyo"]
        anyo_min = meta.get("anyo_min")
        anyo_max = meta.get("anyo_max")

        if anyo_min is not None and anyo_max is not None:
            if not (int(anyo_min) <= int(anyo) <= int(anyo_max)):
                return False

    if filtros.get("territorio"):
        territorio = normalizar_texto(filtros["territorio"])

        alternativas = [territorio]

        if territorio == "madrid":
            alternativas.extend([
                "madrid",
                "comunidad madrid",
                "comunidad de madrid"
            ])

        if territorio == "andalucia":
            alternativas.extend(["andalucia"])

        if not any(alt in texto_meta for alt in alternativas):
            return False

    if filtros.get("sexo"):
        sexo = filtros["sexo"]

        if sexo == "hombres":
            alternativas_sexo = ["hombres", "hombre", "varones", "varon"]
        elif sexo == "mujeres":
            alternativas_sexo = ["mujeres", "mujer"]
        else:
            alternativas_sexo = [sexo]

        alternativas_sexo = [normalizar_texto(s) for s in alternativas_sexo]

        if not any(s in texto_meta for s in alternativas_sexo):
            return False

    if filtros.get("edad"):
        edad = normalizar_texto(filtros["edad"])
        edad_sin_de = edad.replace("de ", "").strip()

        alternativas_edad = [
            edad,
            edad_sin_de,
            "edad",
            "edades",
            "grupo edad",
            "grupos edad",
            "grupos de edad"
        ]

        if not any(normalizar_texto(e) in texto_meta for e in alternativas_edad):
            return False

    return True

# ============================================================
# REORDENACIÓN LÉXICA
# ============================================================

def extraer_ngramas_importantes(pregunta):
    palabras = [
        palabra.strip(".,;:()¿?¡!")
        for palabra in normalizar_texto(pregunta).split()
    ]
    palabras = [palabra for palabra in palabras if len(palabra) > 2]

    ngramas = []
    for i in range(len(palabras) - 1):
        ngramas.append(palabras[i] + " " + palabras[i + 1])
    for i in range(len(palabras) - 2):
        ngramas.append(palabras[i] + " " + palabras[i + 1] + " " + palabras[i + 2])

    return ngramas


def bonus_lexico(pregunta, meta):
    texto_meta = construir_texto_meta_tabla(meta)

    bonus = 0.0

    for ngrama in extraer_ngramas_importantes(pregunta):
        if ngrama in texto_meta:
            bonus += 0.05

    tokens = [
        token.strip(".,;:()¿?¡!")
        for token in normalizar_texto(pregunta).split()
        if len(token.strip(".,;:()¿?¡!")) > 3
    ]

    bonus += sum(1 for token in tokens if token in texto_meta) * 0.02

    return bonus


def penalizacion_por_ruido(pregunta, meta):
    return 0.0

# ============================================================
# BÚSQUEDA PRINCIPAL
# ============================================================

def buscar_faiss(index, metadata, modelo, pregunta, top_k=TOP_K_FINAL,  score_minimo=SCORE_FINAL_MINIMO):
    embedding = generar_embedding_pregunta(modelo, pregunta)
    filtros = extraer_filtros_basicos(pregunta)

    top_k_ampliado = min(top_k * FACTOR_CANDIDATOS_FAISS, index.ntotal)
    scores, indices = index.search(embedding, top_k_ampliado)

    resultados = []

    for idx, score in zip(indices[0], scores[0]):
        if idx < 0 or idx >= len(metadata):
            continue

        registro = metadata[idx]
        meta = registro.get("metadata", {})

        
        score_faiss = float(score)
        score_bonus = bonus_lexico(pregunta, meta) + penalizacion_por_ruido(pregunta, meta)
        score_final = score_faiss + score_bonus

        if score_final < score_minimo:
            continue

        resultados.append({
            "rank": 0,
            "score": score_faiss,
            "score_bonus": round(score_bonus, 4),
            "score_final": round(score_final, 4),
            "posicion": int(idx),
            "id_documento": registro.get("id_documento"),
            "id_tabla": meta.get("id_tabla"),
            "dato_operacion": meta.get("dato_operacion"),
            "titulo_tabla": meta.get("titulo_tabla"),

            "nombre_serie": None,
            "anyo": filtros.get("anyo"),
            "periodo": None,
            "valor": None,
            "unidad": None,

            "anyo_min": meta.get("anyo_min"),
            "anyo_max": meta.get("anyo_max"),
            "fuentes_datos": meta.get("fuentes_datos"),
            "total_observaciones": meta.get("total_observaciones"),
            "num_series": meta.get("num_series"),
            "series_principales": meta.get("series_principales"),
            "palabras_clave": meta.get("palabras_clave"),
            "vocabulario": meta.get("vocabulario"),

            "href_tabla": meta.get("href_tabla"),
            "url_api": meta.get("url_api")
        })

    resultados = sorted(resultados, key=lambda x: x["score_final"], reverse=True)[:top_k]

    for rank, resultado in enumerate(resultados, start=1):
        resultado["rank"] = rank

    return {
        "fuente": "faiss",
        "pregunta": pregunta,
        "filtros_detectados": filtros,
        "total_resultados": len(resultados),
        "resultados": resultados
    }
