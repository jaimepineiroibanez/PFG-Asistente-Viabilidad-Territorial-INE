import os
import duckdb

from codigo.utilidades.utils_ine import (
    calcular_hilos_trabajo,
    normalizar_texto
)

# ============================================================
# CONEXIÓN CON DUCKDB
# ============================================================

def conectar_duckdb(path_duckdb, num_hilos=None):
    path_duckdb = str(path_duckdb)
    if not os.path.exists(path_duckdb):
        raise FileNotFoundError(f"No existe DuckDB: {path_duckdb}")

    _, hilos_calculados = calcular_hilos_trabajo()

    if num_hilos is None:
        num_hilos = hilos_calculados

    if num_hilos < 1:
        num_hilos = 1

    con = duckdb.connect(path_duckdb)
    con.execute(f"PRAGMA threads={num_hilos}")
    print(f"[INFO] DuckDB conectado con {num_hilos} hilos")
    return con

# ============================================================
# PREPROCESAMIENTO DE CANDIDATOS
# ============================================================

def deduplicar_candidatos_faiss(candidatos):
    candidatos_unicos = []
    claves_vistas = set()

    for candidato in candidatos:
        clave = (
            str(candidato.get("id_tabla")),
            normalizar_texto(candidato.get("nombre_serie")),
            str(candidato.get("unidad")),
            str(candidato.get("fuente_datos"))
        )

        if clave in claves_vistas:
            continue

        claves_vistas.add(clave)
        candidatos_unicos.append(candidato)

    return candidatos_unicos

def obtener_filtro_textual(filtros_detectados, clave):
    valor = filtros_detectados.get(clave)
    if valor is None:
        return None

    valor = normalizar_texto(valor)
    return valor if valor else None

# ============================================================
# CONSTRUCCIÓN DE CONSULTAS
# ============================================================

def construir_condicion_like_normalizada(campo_sql, valores, condiciones, parametros):
    valores = [normalizar_texto(v) for v in valores if v]
    valores = [v for v in valores if v]

    if not valores:
        return

    subcondiciones = []

    for valor in valores:
        subcondiciones.append(f"lower({campo_sql}) LIKE ?")
        parametros.append(f"%{valor}%")

    condiciones.append("(" + " OR ".join(subcondiciones) + ")")


def construir_order_relevancia(filtros_detectados):
    territorio = obtener_filtro_textual(filtros_detectados, "territorio")
    sexo = obtener_filtro_textual(filtros_detectados, "sexo")
    edad = obtener_filtro_textual(filtros_detectados, "edad")

    criterios = []

    nombre_serie_norm = normalizar_campo_sql("nombre_serie")

    if territorio:
        criterios.append(
            f"CASE WHEN {nombre_serie_norm} LIKE '%{territorio}%' THEN 0 ELSE 1 END"
        )

    if sexo:
        if sexo == "hombres":
            criterios.append("""
                CASE
                    WHEN lower(nombre_serie) LIKE '%hombres%' THEN 0
                    WHEN lower(nombre_serie) LIKE '%varones%' THEN 0
                    ELSE 1
                END
            """)
        elif sexo == "mujeres":
            criterios.append("""
                CASE
                    WHEN lower(nombre_serie) LIKE '%mujeres%' THEN 0
                    WHEN lower(nombre_serie) LIKE '%mujer%' THEN 0
                    ELSE 1
                END
            """)

    if edad:
        criterios.append(
            f"CASE WHEN lower(nombre_serie) LIKE '%{edad}%' THEN 0 ELSE 1 END"
        )

    criterios.append("""
        CASE
            WHEN lower(nombre_serie) LIKE '%provincia%total%' THEN 0
            WHEN lower(nombre_serie) LIKE '%capital%provincia%total%' THEN 1
            WHEN lower(nombre_serie) LIKE '%total%' THEN 2
            WHEN lower(nombre_serie) LIKE '%con tax%' THEN 3
            WHEN lower(nombre_serie) LIKE '%sin tax%' THEN 4
            ELSE 9
        END
    """)

    criterios.append("anyo DESC NULLS LAST")
    criterios.append("periodo DESC NULLS LAST")

    return ",\n".join(criterios)

def consulta_desde_candidato_faiss(con, tabla, candidato, filtros_detectados=None, limite=50):
    filtros_detectados = filtros_detectados or {}

    id_tabla = candidato.get("id_tabla")
    nombre_serie = candidato.get("nombre_serie")
    unidad = candidato.get("unidad")

    anyo = filtros_detectados.get("anyo")
    periodo = filtros_detectados.get("periodo")
    territorio = obtener_filtro_textual(filtros_detectados, "territorio")
    sexo = obtener_filtro_textual(filtros_detectados, "sexo")
    edad = obtener_filtro_textual(filtros_detectados, "edad")

    condiciones = []
    parametros = []

    if id_tabla:
        condiciones.append("id_tabla = ?")
        parametros.append(str(id_tabla))

    if nombre_serie:
        condiciones.append("nombre_serie = ?")
        parametros.append(nombre_serie)

    if unidad:
        condiciones.append("(unidad = ? OR unidad IS NULL)")
        parametros.append(unidad)

    if anyo is not None:
        condiciones.append("anyo = ?")
        parametros.append(int(anyo))

    if periodo:
        condiciones.append("periodo = ?")
        parametros.append(str(periodo))

   
    if not condiciones:
        return None

    where_sql = " AND ".join(condiciones)
    order_sql = construir_order_relevancia(filtros_detectados)

    query = f"""
        SELECT
            id_tabla,
            dato_operacion,
            titulo_tabla,
            nombre_serie,
            periodo,
            anyo,
            valor,
            unidad,
            href_operacion,
            href_tabla,
            url_api
        FROM {tabla}
        WHERE {where_sql}
          AND valor IS NOT NULL
        ORDER BY
            {order_sql}
        LIMIT {int(limite)}
    """
    
    return con.execute(query, parametros).fetchdf()

# ============================================================
# RECUPERACIÓN DESDE FAISS
# ============================================================

def generar_contexto_duckdb_desde_faiss(con, tabla, faiss_data, limite_por_candidato=50):
    pregunta = faiss_data.get("pregunta")
    filtros_detectados = faiss_data.get("filtros_detectados", {})
    candidatos_originales = faiss_data.get("resultados", [])
    candidatos = deduplicar_candidatos_faiss(candidatos_originales)

    resultados_duckdb = []

    MAX_CANDIDATOS_DUCKDB = 10

    for candidato in candidatos[:MAX_CANDIDATOS_DUCKDB]:
        df = consulta_desde_candidato_faiss(
            con=con,
            tabla=tabla,
            candidato=candidato,
            filtros_detectados=filtros_detectados,
            limite=limite_por_candidato
        )

        if df is None or df.empty:
            continue

        df_limpio = df.where(df.notna(), None)

        resultados_duckdb.append({
            "candidato_faiss": {
                "rank": candidato.get("rank"),
                "score_faiss": candidato.get("score"),
                "score_bonus": candidato.get("score_bonus"),
                "score_final": candidato.get("score_final"),
                "id_documento": candidato.get("id_documento"),
                "id_tabla": candidato.get("id_tabla"),
                "dato_operacion": candidato.get("dato_operacion"),
                "nombre_serie": candidato.get("nombre_serie"),
                "anyo": candidato.get("anyo"),
                "periodo": candidato.get("periodo"),
                "unidad": candidato.get("unidad"),
                "anyo_min": candidato.get("anyo_min"),
                "anyo_max": candidato.get("anyo_max"),
                "fuente_datos": candidato.get("fuente_datos"),
                "total_observaciones": candidato.get("total_observaciones")
            },
            "datos_duckdb": df_limpio.to_dict(orient="records")
        })

    return {
        "fuente": "duckdb_desde_faiss",
        "pregunta_usuario": pregunta,
        "filtros_detectados": filtros_detectados,
        "total_candidatos_faiss": len(candidatos_originales),
        "total_candidatos_unicos": len(candidatos),
        "total_candidatos_con_datos": len(resultados_duckdb),
        "resultados": resultados_duckdb
    }

# ============================================================
# FALLBACK TEXTUAL
# ============================================================
  
def extraer_tokens_busqueda(pregunta):
    stopwords = {
        "dime", "los", "las", "el", "la", "de", "del", "en", "y",
        "mas", "más", "sobre", "datos", "dato", "informacion",
        "información", "para", "por", "con", "un", "una", "que",
        "cuales", "cuál", "cual"
    }

    tokens = []

    for token in normalizar_texto(pregunta).split():
        token = token.strip(".,;:()¿?¡!")
        if len(token) <= 3:
            continue
        if token in stopwords:
            continue
        tokens.append(token)

    return tokens


def buscar_duckdb_por_texto(con, tabla, pregunta, limite=20):
    tokens = extraer_tokens_busqueda(pregunta)

    if not tokens:
        return None

    condiciones = []
    parametros = []

    for token in tokens:
        condiciones.append("""
            (
                lower(dato_operacion) LIKE ?
                OR lower(COALESCE(titulo_tabla, '')) LIKE ?
                OR lower(nombre_serie) LIKE ?
                OR lower(COALESCE(unidad, '')) LIKE ?
            )
        """)

        patron = f"%{token}%"
        parametros.extend([patron, patron, patron, patron])

    where_sql = " OR ".join(condiciones)

    query = f"""
        SELECT
            id_tabla,
            dato_operacion,
            titulo_tabla,
            nombre_serie,
            periodo,
            anyo,
            valor,
            unidad,
            href_operacion,
            href_tabla,
            url_api
        FROM {tabla}
        WHERE {where_sql}
          AND valor IS NOT NULL
        ORDER BY anyo DESC NULLS LAST, periodo DESC NULLS LAST
        LIMIT {int(limite)}
    """

    return con.execute(query, parametros).fetchdf()


def generar_contexto_duckdb_fallback(con, tabla, pregunta, limite=20):
    df = buscar_duckdb_por_texto(
        con=con,
        tabla=tabla,
        pregunta=pregunta,
        limite=limite
    )

    resultados = []

    if df is not None and not df.empty:
        df_limpio = df.where(df.notna(), None)

        for i, fila in enumerate(df_limpio.to_dict(orient="records"), start=1):
            resultados.append({
                "candidato_faiss": {
                    "rank": i,
                    "score_faiss": None,
                    "score_bonus": None,
                    "score_final": None,
                    "id_documento": None,
                    "id_tabla": fila.get("id_tabla"),
                    "dato_operacion": fila.get("dato_operacion"),
                    "nombre_serie": fila.get("nombre_serie"),
                    "anyo": fila.get("anyo"),
                    "periodo": fila.get("periodo"),
                    "unidad": fila.get("unidad")
                },
                "datos_duckdb": [fila]
            })

    return {
        "fuente": "duckdb_fallback_textual",
        "metodo_recuperacion": "duckdb_fallback_textual",
        "pregunta_usuario": pregunta,
        "filtros_detectados": {},
        "total_candidatos_faiss": 0,
        "total_candidatos_unicos": 0,
        "total_candidatos_con_datos": len(resultados),
        "resultados": resultados
    }

# ============================================================
# CONSULTA DIRECTA POR ID_TABLA
# ============================================================
 
def consulta_por_id_tabla(con, tabla, id_tabla, limite=50):
    query = f"""
        SELECT
            id_tabla,
            dato_operacion,
            titulo_tabla,
            nombre_serie,
            periodo,
            anyo,
            valor,
            unidad,
            href_operacion,
            href_tabla,
            url_api
        FROM {tabla}
        WHERE id_tabla = ?
        ORDER BY anyo DESC NULLS LAST, periodo DESC NULLS LAST
        LIMIT {int(limite)}
    """

    return con.execute(query, [str(id_tabla)]).fetchdf()


def generar_contexto_duckdb_por_id_tabla(con, tabla, id_tabla, pregunta, limite=50):
    df = consulta_por_id_tabla(
        con=con,
        tabla=tabla,
        id_tabla=id_tabla,
        limite=limite
    )

    resultados = []

    if df is not None and not df.empty:
        df_limpio = df.where(df.notna(), None)

        for i, fila in enumerate(df_limpio.to_dict(orient="records"), start=1):
            resultados.append({
                "candidato_faiss": {
                    "rank": i,
                    "score_faiss": None,
                    "score_bonus": None,
                    "score_final": None,
                    "id_documento": None,
                    "id_tabla": fila.get("id_tabla"),
                    "dato_operacion": fila.get("dato_operacion"),
                    "nombre_serie": fila.get("nombre_serie"),
                    "anyo": fila.get("anyo"),
                    "periodo": fila.get("periodo"),
                    "unidad": fila.get("unidad")
                },
                "datos_duckdb": [fila]
            })

    return {
        "fuente": "duckdb_id_tabla",
        "metodo_recuperacion": "duckdb_id_tabla",
        "pregunta_usuario": pregunta,
        "filtros_detectados": {
            "id_tabla": str(id_tabla)
        },
        "total_candidatos_faiss": 0,
        "total_candidatos_unicos": 0,
        "total_candidatos_con_datos": len(resultados),
        "resultados": resultados
    }

# ============================================================
# NORMALIZACIÓN SQL
# ============================================================
def normalizar_campo_sql(campo):
    return f"""
        lower(
            replace(
            replace(
            replace(
            replace(
            replace(
            replace(
            replace({campo}, 'á', 'a'),
            'é', 'e'),
            'í', 'i'),
            'ó', 'o'),
            'ú', 'u'),
            'ü', 'u'),
            'ñ', 'n')
        )
    """