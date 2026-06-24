# ============================================================
# PRINCIPAL - SISTEMA INE
# ============================================================

import os
import sys
from pathlib import Path


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

CARPETAS_NECESARIAS = [
    "datos/originales",
    "datos/validados",
    "datos/normalizados",
    "datos/parquet",
    "datos/duckdb",
    "datos/semanticos",
    "registros/datos",
    "registros/semantica",
    "registros/respuesta",
    "resultados/informes",
    "resultados/consultas",
]


# ============================================================
# UTILIDADES DEL MENÚ
# ============================================================

def limpiar_pantalla():
    os.system("cls" if os.name == "nt" else "clear")


def pausar():
    input("\nPulsa ENTER para continuar...")


def crear_carpetas_necesarias():
    for carpeta in CARPETAS_NECESARIAS:
        ruta = BASE_DIR / carpeta
        ruta.mkdir(parents=True, exist_ok=True)

    print("[OK] Estructura de carpetas comprobada.")


def mostrar_titulo(titulo):
    limpiar_pantalla()
    print("=" * 70)
    print(titulo)
    print("=" * 70)


def ejecutar_paso(nombre, funcion, *args, **kwargs):
    print("\n" + "-" * 70)
    print(f"[INICIO] {nombre}")
    print("-" * 70)

    resultado = funcion(*args, **kwargs)

    print("-" * 70)
    print(f"[OK] {nombre}")
    print("-" * 70)

    return resultado


# ============================================================
# CAPA DE DATOS
# ============================================================

def ejecutar_capa_datos_completa():
    from codigo.datos.obtener_fichero_html import ejecutar as obtener_html
    from codigo.datos.extraer_identificadores_ine import ejecutar as extraer_identificadores
    from codigo.datos.descargar_datos_api_ine import ejecutar as descargar_api
    from codigo.datos.descargar_datos_href_ine import ejecutar as descargar_href
    from codigo.datos.validar_jsonl_api_ine import ejecutar as validar_api
    from codigo.datos.validar_jsonl_href_ine import ejecutar as validar_href
    from codigo.datos.normalizar_jsonl_api_ine import ejecutar as normalizar_api
    from codigo.datos.normalizar_jsonl_href_ine import ejecutar as normalizar_href
    from codigo.datos.convertir_jsonl_a_parquet import ejecutar as convertir_parquet
    from codigo.almacenamiento.crear_duckdb import ejecutar as crear_duckdb

    crear_carpetas_necesarias()

    ejecutar_paso("Obtener índice A-Z del INE", obtener_html)
    ejecutar_paso("Extraer identificadores INE", extraer_identificadores)
    ejecutar_paso("Descargar datos API INE", descargar_api)
    ejecutar_paso("Descargar datos HREF/CSV INE", descargar_href)
    ejecutar_paso("Validar JSONL API", validar_api)
    ejecutar_paso("Validar JSONL HREF", validar_href)
    ejecutar_paso("Normalizar JSONL API", normalizar_api)
    ejecutar_paso("Normalizar JSONL HREF", normalizar_href)

    ejecutar_paso(
        "Convertir API a Parquet",
        convertir_parquet,
        input_jsonl="./datos/normalizados/dataset_ine_normalizado_api.jsonl",
        output_parquet="./datos/parquet/dataset_ine_normalizado_api.parquet",
        output_resumen="./datos/parquet/resumen_parquet_api.json",
    )

    ejecutar_paso(
        "Convertir HREF a Parquet",
        convertir_parquet,
        input_jsonl="./datos/normalizados/dataset_ine_normalizado_href.jsonl",
        output_parquet="./datos/parquet/dataset_ine_normalizado_href.parquet",
        output_resumen="./datos/parquet/resumen_parquet_href.json",
    )

    ejecutar_paso("Crear DuckDB", crear_duckdb)


# ============================================================
# CAPA SEMÁNTICA
# ============================================================

def ejecutar_capa_semantica_completa():
    from codigo.semantica.generar_dataset_semantico_por_tabla import ejecutar as generar_dataset_semantico
    from codigo.semantica.crear_indice_faiss_ine import ejecutar as crear_indice_faiss

    crear_carpetas_necesarias()

    ejecutar_paso(
        "Generar dataset semántico por tabla",
        generar_dataset_semantico
    )

    ejecutar_paso(
        "Crear índice FAISS",
        crear_indice_faiss
    )


# ============================================================
# SISTEMA COMPLETO
# ============================================================

def ejecutar_sistema_completo():
    mostrar_titulo("EJECUCIÓN COMPLETA DEL SISTEMA")

    ejecutar_capa_datos_completa()
    ejecutar_capa_semantica_completa()

    print("\n[OK] Sistema completo ejecutado correctamente.")


# ============================================================
# CAPA DE RESPUESTA
# ============================================================

def ejecutar_consulta_consola(usar_llm=True):
    from codigo.respuesta.pipeline_estudio_mercado import ejecutar

    mostrar_titulo("CONSULTA POR CONSOLA")

    texto_usuario = input(
        "Introduce una consulta. Ejemplo: 'Quiero abrir un gimnasio en Madrid'\n\n> "
    ).strip()

    if not texto_usuario:
        print("[ERROR] No se ha introducido ninguna consulta.")
        return

    resultado = ejecutar(
        texto_usuario=texto_usuario,
        usar_llm=usar_llm
    )

    print("\n" + "=" * 70)
    print("INFORME GENERADO")
    print("=" * 70)
    print(resultado.get("informe"))


def iniciar_bot_telegram():
    from codigo.interfaz.telegram_bot_estudio_mercado import main as iniciar_bot

    mostrar_titulo("BOT DE TELEGRAM")
    iniciar_bot()


# ============================================================
# COMPROBACIONES
# ============================================================

def comprobar_estructura():
    mostrar_titulo("COMPROBACIÓN DE ESTRUCTURA")

    crear_carpetas_necesarias()

    rutas_clave = [
        "datos/duckdb/ine_dataset.duckdb",
        "datos/semanticos/index_ine.faiss",
        "datos/semanticos/metadata_ine.jsonl",
        "configuracion/config_ine.py",
    ]

    for ruta in rutas_clave:
        path = BASE_DIR / ruta

        if path.exists():
            print(f"[OK] {ruta}")
        else:
            print(f"[FALTA] {ruta}")


# ============================================================
# SUBMENÚS
# ============================================================

def menu_datos():
    while True:
        mostrar_titulo("CAPA DE DATOS")

        print("1. Ejecutar capa de datos completa")
        print("0. Volver")

        opcion = input("\nSelecciona una opción: ").strip()

        if opcion == "1":
            ejecutar_capa_datos_completa()
            pausar()
        elif opcion == "0":
            break
        else:
            print("[ERROR] Opción no válida.")
            pausar()


def menu_semantica():
    while True:
        mostrar_titulo("CAPA SEMÁNTICA")

        print("1. Ejecutar capa semántica completa")
        print("0. Volver")

        opcion = input("\nSelecciona una opción: ").strip()

        if opcion == "1":
            ejecutar_capa_semantica_completa()
            pausar()
        elif opcion == "0":
            break
        else:
            print("[ERROR] Opción no válida.")
            pausar()


def menu_respuesta():
    while True:
        mostrar_titulo("CAPA DE RESPUESTA")

        print("1. Ejecutar consulta por consola con LLM")
        print("2. Ejecutar consulta por consola sin LLM")
        print("0. Volver")

        opcion = input("\nSelecciona una opción: ").strip()

        if opcion == "1":
            ejecutar_consulta_consola(usar_llm=True)
            pausar()
        elif opcion == "2":
            ejecutar_consulta_consola(usar_llm=False)
            pausar()
        elif opcion == "0":
            break
        else:
            print("[ERROR] Opción no válida.")
            pausar()


# ============================================================
# MENÚ PRINCIPAL
# ============================================================

def menu_principal():
    crear_carpetas_necesarias()

    while True:
        mostrar_titulo("SISTEMA INE - ASISTENTE DE VIABILIDAD TERRITORIAL")

        print("1. Ejecutar sistema completo")
        print("2. Capa de datos")
        print("3. Capa semántica")
        print("4. Capa de respuesta")
        print("5. Iniciar bot de Telegram")
        print("6. Comprobar estructura del proyecto")
        print("0. Salir")

        opcion = input("\nSelecciona una opción: ").strip()

        if opcion == "1":
            ejecutar_sistema_completo()
            pausar()

        elif opcion == "2":
            menu_datos()

        elif opcion == "3":
            menu_semantica()

        elif opcion == "4":
            menu_respuesta()

        elif opcion == "5":
            iniciar_bot_telegram()

        elif opcion == "6":
            comprobar_estructura()
            pausar()

        elif opcion == "0":
            print("\n[INFO] Sistema finalizado.")
            break

        else:
            print("[ERROR] Opción no válida.")
            pausar()


if __name__ == "__main__":
    try:
        menu_principal()

    except KeyboardInterrupt:
        print("\n[INFO] Ejecución interrumpida por el usuario.")
        sys.exit(0)