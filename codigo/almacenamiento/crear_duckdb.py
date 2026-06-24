import os
import json
import argparse
import duckdb


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_PARQUET_API = "./datos/parquet/dataset_ine_normalizado_api.parquet"
INPUT_PARQUET_HREF = "./datos/parquet/dataset_ine_normalizado_href.parquet"
OUTPUT_DUCKDB = "./datos/duckdb/ine_dataset.duckdb"
OUTPUT_RESUMEN = "./datos/duckdb/resumen_duckdb_ine.json"

NOMBRE_TABLA = "dataset_ine"


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


def calcular_hilos_trabajo():
    cpu_total = os.cpu_count() or 1
    restantes = max(cpu_total - 1, 0)
    num_hilos_trabajo = (restantes // 2) + 1
    return cpu_total, num_hilos_trabajo


# ============================================================
# PARQUET -> DUCKDB
# ============================================================

def crear_duckdb_desde_parquet(
    input_parquet_api=INPUT_PARQUET_API,
    input_parquet_href=INPUT_PARQUET_HREF,
    output_duckdb=OUTPUT_DUCKDB,
    output_resumen=OUTPUT_RESUMEN,
    nombre_tabla=NOMBRE_TABLA,
    sobrescribir=True,
    num_hilos=None
):
    if not os.path.exists(input_parquet_api):
        print(f"[ERROR] No existe el Parquet de entrada: {input_parquet_api}")
        return None
    
    if not os.path.exists(input_parquet_href):
        print(f"[ERROR] No existe el Parquet de entrada: {input_parquet_href}")
        return None

    asegurar_carpeta(output_duckdb)
    asegurar_carpeta(output_resumen)

    cpu_total, hilos_calculados = calcular_hilos_trabajo()

    if num_hilos is None:
        num_hilos = hilos_calculados

    if num_hilos < 1:
        num_hilos = 1

    if sobrescribir and os.path.exists(output_duckdb):
        os.remove(output_duckdb)

    print("==============================================")
    print(" CREACIÓN DUCKDB DESDE PARQUET")
    print("==============================================")
    print(f"[INFO] Parquet entrada API: {input_parquet_api}")
    print(f"[INFO] Parquet entrada HREF: {input_parquet_href}")
    print(f"[INFO] DuckDB salida:   {output_duckdb}")
    print(f"[INFO] Tabla:           {nombre_tabla}")
    print(f"[INFO] CPU lógicas:     {cpu_total}")
    print(f"[INFO] Hilos calculados:{hilos_calculados}")
    print(f"[INFO] Hilos usados:    {num_hilos}")

    con = duckdb.connect(output_duckdb)

    try:
        con.execute(f"PRAGMA threads={num_hilos}")

        print("[INFO] Creando tabla desde Parquet...")
        con.execute(f"""
            CREATE TABLE {nombre_tabla} AS
            SELECT *, 'api' AS fuente_datos
            FROM read_parquet('{input_parquet_api}')

            UNION ALL

            SELECT *, 'href' AS fuente_datos
            FROM read_parquet('{input_parquet_href}')
        """)

        print("[INFO] Creando índices básicos...")
        indices = [
            ("idx_id_tabla", "id_tabla"),
            ("idx_anyo", "anyo"),
            ("idx_dato_operacion", "dato_operacion"),
            ("idx_titulo_tabla", "titulo_tabla")
        ]

        indices_creados = []

        for nombre_indice, columna in indices:
            columnas = con.execute(f"PRAGMA table_info('{nombre_tabla}')").fetchall()
            columnas_existentes = {col[1] for col in columnas}

            if columna in columnas_existentes:
                try:
                    con.execute(f"CREATE INDEX {nombre_indice} ON {nombre_tabla}({columna})")
                    indices_creados.append({
                        "indice": nombre_indice,
                        "columna": columna,
                        "estado": "OK"
                    })
                except Exception as e:
                    indices_creados.append({
                        "indice": nombre_indice,
                        "columna": columna,
                        "estado": "ERROR",
                        "error": str(e)
                    })

        print("[INFO] Verificando tabla...")

        total_filas = con.execute(f"SELECT COUNT(*) FROM {nombre_tabla}").fetchone()[0]
        total_columnas = len(con.execute(f"PRAGMA table_info('{nombre_tabla}')").fetchall())

        columnas_info = con.execute(f"PRAGMA table_info('{nombre_tabla}')").fetchall()

        columnas = [
            {
                "cid": col[0],
                "nombre": col[1],
                "tipo": col[2],
                "notnull": bool(col[3]),
                "default": col[4],
                "pk": bool(col[5])
            }
            for col in columnas_info
        ]

        muestra = con.execute(f"""
            SELECT *
            FROM {nombre_tabla}
            LIMIT 5
        """).fetchdf().to_dict(orient="records")

        top_operaciones = con.execute(f"""
            SELECT dato_operacion, COUNT(*) AS total_filas
            FROM {nombre_tabla}
            GROUP BY dato_operacion
            ORDER BY total_filas DESC
            LIMIT 10
        """).fetchdf().to_dict(orient="records")

        top_tablas = con.execute(f"""
            SELECT id_tabla, titulo_tabla, COUNT(*) AS total_filas
            FROM {nombre_tabla}
            GROUP BY id_tabla, titulo_tabla
            ORDER BY total_filas DESC
            LIMIT 10
        """).fetchdf().to_dict(orient="records")

        resumen = {
            "input_parquet_api": input_parquet_api,
            "input_parquet_href": input_parquet_href,
            "output_duckdb": output_duckdb,
            "nombre_tabla": nombre_tabla,
            "cpu_total": cpu_total,
            "hilos_calculados": hilos_calculados,
            "hilos_usados": num_hilos,
            "total_filas": int(total_filas),
            "total_columnas": int(total_columnas),
            "columnas": columnas,
            "indices_creados": indices_creados,
            "top_10_operaciones": top_operaciones,
            "top_10_tablas": top_tablas,
            "muestra_5_filas": muestra,
            "tamano_duckdb_mb": round(os.path.getsize(output_duckdb) / (1024 * 1024), 2)
        }

        guardar_json(output_resumen, resumen)

        print("==============================================")
        print("[OK] DuckDB creado correctamente")
        print(f"[INFO] Filas: {total_filas}")
        print(f"[INFO] Columnas: {total_columnas}")
        print(f"[INFO] Base DuckDB: {output_duckdb}")
        print(f"[INFO] Resumen: {output_resumen}")
        print(f"[INFO] Tamaño DuckDB MB: {resumen['tamano_duckdb_mb']}")
        print("==============================================")

        return resumen

    finally:
        con.close()


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Crea una base DuckDB desde el Parquet normalizado del INE."
    )

    parser.add_argument("--input-api", default=INPUT_PARQUET_API)
    parser.add_argument("--input-href", default=INPUT_PARQUET_HREF)
    parser.add_argument("--output", default=OUTPUT_DUCKDB)
    parser.add_argument("--resumen", default=OUTPUT_RESUMEN)
    parser.add_argument("--tabla", default=NOMBRE_TABLA)
    parser.add_argument("--num-hilos", type=int, default=None)

    args = parser.parse_args()

    ejecutar(
        input_parquet_api=args.input_api,
        input_parquet_href=args.input_href,
        output_duckdb=args.output,
        output_resumen=args.resumen,
        nombre_tabla=args.tabla,
        num_hilos=args.num_hilos
    )


# ============================================================
# EJECUCIÓN DESDE OTROS MÓDULOS
# ============================================================

def ejecutar(
        input_parquet_api=INPUT_PARQUET_API,
        input_parquet_href=INPUT_PARQUET_HREF,
        output_duckdb=OUTPUT_DUCKDB,
        output_resumen=OUTPUT_RESUMEN,
        nombre_tabla=NOMBRE_TABLA,
        sobrescribir=True,
        num_hilos=None):

    return crear_duckdb_desde_parquet(
        input_parquet_api=input_parquet_api,
        input_parquet_href=input_parquet_href,
        output_duckdb=output_duckdb,
        output_resumen=output_resumen,
        nombre_tabla=nombre_tabla,
        sobrescribir=sobrescribir,
        num_hilos=num_hilos
    )

if __name__ == "__main__":
    main()
