import re

from codigo.utilidades.utils_ine import normalizar_texto

# ============================================================
# CONSTRUCCIÓN DEL CONTEXTO PARA EL LLM
# ============================================================

def normalizar_serie_para_deduplicar(serie):
    serie_norm = normalizar_texto(serie)
    serie_norm = serie_norm.replace("madrid, comunidad de", "madrid")
    serie_norm = serie_norm.replace("madrid (comunidad de)", "madrid")
    serie_norm = re.sub(r"\s+", " ", serie_norm).strip()
    return serie_norm

# ============================================================
# PREPARACIÓN DEL CONTEXTO
# ============================================================

def preparar_contexto_para_llm(contexto_duckdb):
    datos_recuperados = []
    claves_vistas = set()

    for bloque in contexto_duckdb.get("resultados", []):
        candidato = bloque.get("candidato_faiss", {})
        datos = bloque.get("datos_duckdb", [])

        datos_limpios = []

        for fila in datos:
            clave_fila = (
                str(candidato.get("id_tabla")),
                normalizar_serie_para_deduplicar(fila.get("nombre_serie")),
                str(fila.get("anyo")),
                str(fila.get("periodo")),
                str(fila.get("valor")),
                str(fila.get("unidad"))
            )

            if clave_fila in claves_vistas:
                continue

            claves_vistas.add(clave_fila)

            datos_limpios.append({
                "serie": fila.get("nombre_serie"),
                "anyo": fila.get("anyo"),
                "periodo": fila.get("periodo"),
                "valor": fila.get("valor"),
                "unidad": fila.get("unidad")
            })

        if not datos_limpios:
            continue

        datos_recuperados.append({
            "relevancia": candidato.get("score_final"),
            "rank_faiss": candidato.get("rank"),
            "id_tabla": candidato.get("id_tabla"),
            "operacion": candidato.get("dato_operacion"),
            "serie": candidato.get("nombre_serie"),
            "unidad": candidato.get("unidad"),
            "fuente": (
                datos[0].get("href_operacion")
                or datos[0].get("href_tabla")
                or datos[0].get("url_api")
            ) if datos else None,
            "datos": datos_limpios
        })

    return {
        "tipo_contexto": "respuesta_estadistica_ine",
        "pregunta_usuario": contexto_duckdb.get("pregunta_usuario"),
        "instrucciones_para_llm": [
            "Responde únicamente con los datos proporcionados.",
            "No inventes valores, años, periodos ni unidades.",
            "Si hay varias series candidatas, preséntalas como posibles interpretaciones.",
            "Prioriza los resultados con mayor relevancia.",
            "Indica claramente el año, periodo, valor y unidad.",
            "Si los datos no permiten una respuesta única, explícalo."
        ],
        "filtros_detectados": contexto_duckdb.get("filtros_detectados", {}),
        "resumen_recuperacion": {
            "total_candidatos_faiss": contexto_duckdb.get("total_candidatos_faiss"),
            "total_candidatos_unicos": contexto_duckdb.get("total_candidatos_unicos"),
            "total_candidatos_con_datos": contexto_duckdb.get("total_candidatos_con_datos"),
            "total_series_enviadas_llm": len(datos_recuperados)
        },
        "datos_recuperados": datos_recuperados
    }
