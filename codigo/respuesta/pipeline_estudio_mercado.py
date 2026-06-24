import argparse
import json
import os

from codigo.respuesta.informe_estudio_mercado import (
    generar_informe_estudio
)

from configuracion.config_ine import (
    INPUT_INDEX,
    INPUT_METADATA,
    INPUT_DUCKDB,
    NOMBRE_TABLA_DUCKDB,
    MODELO_EMBEDDINGS,
    MODELO_LLM,
    TOP_K_FINAL,
    LIMITE_POR_CANDIDATO,
    SCORE_FINAL_MINIMO,
)

from codigo.utilidades.utils_ine import (
    guardar_json
)

from codigo.respuesta.faiss_retriever_ine import (
    cargar_indice_faiss,
    cargar_metadata_faiss,
    cargar_modelo_embeddings,
    buscar_faiss,
)

from codigo.respuesta.duckdb_retriever_ine import (
    conectar_duckdb,
    generar_contexto_duckdb_desde_faiss,
    generar_contexto_duckdb_fallback,
)

from codigo.respuesta.context_builder_ine import (
    preparar_contexto_para_llm
)

from codigo.respuesta.interpretar_estudio_mercado import (
    interpretar_estudio_mercado
)

from codigo.respuesta.consultas_estudio_mercado import (
    seleccionar_pilares,
    generar_consultas_por_pilar,
)

# ============================================================
# EJECUCION DE CONSULTAS INTERNAS
# ============================================================

def ejecutar_consulta_estadistica(
    pregunta,
    territorio,
    index,
    metadata,
    modelo_embeddings,
    con,
    tabla,
    top_k=TOP_K_FINAL,
    limite_por_candidato=LIMITE_POR_CANDIDATO,
    score_minimo=SCORE_FINAL_MINIMO,
):
    """
    Ejecuta una consulta estadística interna del estudio de mercado.

    Esta función reutiliza la capa semántica FAISS y la capa de datos DuckDB,
    pero no genera una respuesta final individual. Su objetivo es devolver
    contexto estructurado para construir el informe completo.
    """

    #print("\n" + "=" * 100)
    print(f"[CONSULTA INTERNA] {pregunta}")
    #print("=" * 100)

    faiss_data = buscar_faiss(
        index=index,
        metadata=metadata,
        modelo=modelo_embeddings,
        pregunta=pregunta,
        top_k=top_k,
        score_minimo=score_minimo,
    )
    
    faiss_data.setdefault("filtros_detectados", {})
    faiss_data["filtros_detectados"]["territorio"] = territorio


    if faiss_data.get("total_resultados", 0) > 0:
        contexto_duckdb = generar_contexto_duckdb_desde_faiss(
            con=con,
            tabla=tabla,
            faiss_data=faiss_data,
            limite_por_candidato=limite_por_candidato,
        )
        
    else:
        print("[INFO] FAISS no encontró resultados. Activando fallback textual en DuckDB...")
        contexto_duckdb = generar_contexto_duckdb_fallback(
            con=con,
            tabla=tabla,
            pregunta=pregunta,
            limite=limite_por_candidato,
        )

    contexto_llm = preparar_contexto_para_llm(contexto_duckdb)

    return {
        "pregunta": pregunta,
        "faiss": faiss_data,
        "duckdb": contexto_duckdb,
        "contexto_llm": contexto_llm,
    }


# ============================================================
# CONTEXTO DEL ESTUDIO
# ============================================================

def construir_contexto_estudio(negocio, territorio, consultas, resultados_por_pilar):
    """
    Agrupa todos los resultados recuperados por pilar para construir
    el contexto que recibirá el LLM generador del informe.
    """

    return {
        "tipo_contexto": "informe_viabilidad_territorial_ine",
        "negocio": negocio,
        "territorio": territorio,
        "advertencias": [
            "El informe se basa únicamente en datos recuperados del INE.",
            "Los datos pueden corresponder a distintos años o periodos.",
            "El sistema no analiza competencia directa, precios de alquiler, ubicación exacta ni demanda real.",
            "Las conclusiones deben entenderse como una aproximación preliminar, no como una recomendación definitiva de inversión.",
        ],
        "consultas_ejecutadas": consultas,
        "resultados_por_pilar": resultados_por_pilar,
    }




# ============================================================
# PIPELINE PRINCIPAL
# ============================================================

def ejecutar_estudio_mercado(
    texto_usuario,
    index,
    metadata,
    modelo_embeddings,
    con,
    tabla=NOMBRE_TABLA_DUCKDB,
    usar_llm=True,
    modelo_llm=MODELO_LLM,
    top_k=TOP_K_FINAL,
    limite_por_candidato=LIMITE_POR_CANDIDATO,
    score_minimo=SCORE_FINAL_MINIMO,
):
    """
    Pipeline principal del generador de informes preliminares de viabilidad territorial.

    Flujo:
    1. Extrae negocio y territorio.
    2. Selecciona pilares.
    3. Genera consultas internas por pilar.
    4. Ejecuta FAISS + DuckDB por cada consulta.
    5. Agrupa los resultados.
    6. Genera un informe final estructurado.
    """

    interpretacion = interpretar_estudio_mercado(
        texto_usuario=texto_usuario,
        modelo_llm=modelo_llm,
    )

    negocio = interpretacion.get("negocio")
    territorio = interpretacion.get("territorio")

    if not negocio or not territorio:
        return {
            "texto_usuario": texto_usuario,
            "interpretacion": interpretacion,
            "error": "No se ha podido identificar correctamente el negocio y el territorio.",
            "informe": (
                "No se ha podido identificar correctamente el tipo de negocio y el territorio.\n\n"
                "Prueba con una frase como:\n"
                "- Quiero abrir un gimnasio en Madrid\n"
                "- Hazme un estudio preliminar para una cafetería en Toledo\n"
                "- Estoy pensando en montar un hotel en Málaga"
            ),
        }

    print("\n" + "=" * 100)
    print("[INTERPRETACIÓN DEL ESTUDIO]")
    print("=" * 100)
    print(f"Negocio detectado: {negocio}")
    print(f"Territorio detectado: {territorio}")

    pilares = seleccionar_pilares(negocio)

    consultas = generar_consultas_por_pilar(
        territorio=territorio,
        pilares=pilares,
        negocio=negocio
    )

    print("\n[PILARES SELECCIONADOS]")
    for pilar in pilares:
        print(f"- {pilar}")

    print("\n[CONSULTAS GENERADAS]")
    for pilar, lista_consultas in consultas.items():
        print(f"- {pilar}:")
        for consulta in lista_consultas:
            print(f"  · {consulta}")

    resultados_por_pilar = {}

    for pilar, lista_consultas in consultas.items():
        resultados_pilar = []

        for consulta in lista_consultas:
            resultado = ejecutar_consulta_estadistica(
                pregunta=consulta,
                territorio=territorio,
                index=index,
                metadata=metadata,
                modelo_embeddings=modelo_embeddings,
                con=con,
                tabla=tabla,
                top_k=top_k,
                limite_por_candidato=limite_por_candidato,
                score_minimo=score_minimo,
            )

            resultados_pilar.append(resultado)

        resultados_por_pilar[pilar] = resultados_pilar

    contexto_estudio = construir_contexto_estudio(
        negocio=negocio,
        territorio=territorio,
        consultas=consultas,
        resultados_por_pilar=resultados_por_pilar,
    )

    informe = generar_informe_estudio(
        contexto_estudio=contexto_estudio,
        usar_llm=usar_llm,
        modelo_llm=modelo_llm,
    )
    return {
        "texto_usuario": texto_usuario,
        "interpretacion": interpretacion,
        "negocio": negocio,
        "territorio": territorio,
        "pilares": pilares,
        "consultas": consultas,
        "resultados_por_pilar": resultados_por_pilar,
        "contexto_estudio": contexto_estudio,
        "informe": informe,
    }


# ============================================================
# MODO INTERACTIVO
# ============================================================

def modo_interactivo_estudio(
    index,
    metadata,
    modelo_embeddings,
    con,
    tabla,
    usar_llm,
    modelo_llm,
    top_k,
    limite_por_candidato,
    score_minimo,
    output,
):
    print("\n" + "=" * 100)
    print(" ASISTENTE DE ESTUDIOS PRELIMINARES DE MERCADO - INE")
    print("=" * 100)
    print("Escribe una idea de negocio y un territorio.")
    print("Ejemplos:")
    print("  - Quiero abrir un gimnasio en Madrid")
    print("  - Hazme un estudio preliminar para una cafetería en Toledo")
    print("  - Estoy pensando en montar un hotel en Málaga")
    print("Para salir: salir")
    print("=" * 100)

    while True:
        texto_usuario = input("\nIdea de negocio: ").strip()

        if texto_usuario.lower() in ["salir", "exit", "q"]:
            print("[INFO] Saliendo...")
            break

        if not texto_usuario:
            continue

        resultado = ejecutar_estudio_mercado(
            texto_usuario=texto_usuario,
            index=index,
            metadata=metadata,
            modelo_embeddings=modelo_embeddings,
            con=con,
            tabla=tabla,
            usar_llm=usar_llm,
            modelo_llm=modelo_llm,
            top_k=top_k,
            limite_por_candidato=limite_por_candidato,
            score_minimo=score_minimo,
        )

        print("\n" + "=" * 100)
        print("[INFORME FINAL]")
        print("=" * 100)
        print(resultado.get("informe"))

        if output:
            guardar_json(output, resultado)


# ============================================================
# EJECUCIÓN DESDE OTROS MÓDULOS
# ============================================================

def ejecutar(
        texto_usuario,
        usar_llm=True):

    index = cargar_indice_faiss(INPUT_INDEX)

    metadata = cargar_metadata_faiss(INPUT_METADATA)

    modelo_embeddings = cargar_modelo_embeddings(
        MODELO_EMBEDDINGS
    )

    con = conectar_duckdb(INPUT_DUCKDB)

    try:

        return ejecutar_estudio_mercado(
            texto_usuario=texto_usuario,
            index=index,
            metadata=metadata,
            modelo_embeddings=modelo_embeddings,
            con=con,
            usar_llm=usar_llm
        )

    finally:
        con.close()

# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Pipeline guiado para estudios preliminares de mercado con datos del INE."
    )

    parser.add_argument("--index", default=INPUT_INDEX)
    parser.add_argument("--metadata", default=INPUT_METADATA)
    parser.add_argument("--duckdb", default=INPUT_DUCKDB)
    parser.add_argument("--tabla", default=NOMBRE_TABLA_DUCKDB)
    parser.add_argument("--modelo-embeddings", default=MODELO_EMBEDDINGS)
    parser.add_argument("--modelo-llm", default=MODELO_LLM)

    parser.add_argument(
        "--pregunta",
        default=None,
        help="Idea de negocio en lenguaje natural. Ejemplo: 'Quiero abrir un gimnasio en Madrid'.",
    )
    parser.add_argument("--output", default=None)

    parser.add_argument("--top-k", type=int, default=TOP_K_FINAL)
    parser.add_argument("--score-minimo", type=float, default=SCORE_FINAL_MINIMO)
    parser.add_argument("--limite-por-candidato", type=int, default=LIMITE_POR_CANDIDATO)
    parser.add_argument("--num-hilos", type=int, default=None)

    parser.add_argument(
        "--sin-llm",
        action="store_true",
        help="Genera un informe por plantilla, sin usar OpenAI.",
    )

    args = parser.parse_args()

    index = cargar_indice_faiss(args.index)
    metadata = cargar_metadata_faiss(args.metadata)
    modelo_embeddings = cargar_modelo_embeddings(args.modelo_embeddings)
    con = conectar_duckdb(args.duckdb, args.num_hilos)

    try:
        if args.pregunta:
            resultado = ejecutar_estudio_mercado(
                texto_usuario=args.pregunta,
                index=index,
                metadata=metadata,
                modelo_embeddings=modelo_embeddings,
                con=con,
                tabla=args.tabla,
                usar_llm=not args.sin_llm,
                modelo_llm=args.modelo_llm,
                top_k=args.top_k,
                limite_por_candidato=args.limite_por_candidato,
                score_minimo=args.score_minimo,
            )

            print("\n" + "=" * 100)
            print("[INFORME FINAL]")
            print("=" * 100)
            print(resultado.get("informe"))

            if args.output:
                guardar_json(args.output, resultado)

        else:
            modo_interactivo_estudio(
                index=index,
                metadata=metadata,
                modelo_embeddings=modelo_embeddings,
                con=con,
                tabla=args.tabla,
                usar_llm=not args.sin_llm,
                modelo_llm=args.modelo_llm,
                top_k=args.top_k,
                limite_por_candidato=args.limite_por_candidato,
                score_minimo=args.score_minimo,
                output=args.output,
            )

    finally:
        con.close()
        print("[INFO] Conexión DuckDB cerrada.")




if __name__ == "__main__":
    main()
