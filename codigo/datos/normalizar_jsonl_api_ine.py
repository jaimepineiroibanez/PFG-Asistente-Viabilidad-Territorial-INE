import json
import os
import re
import ast
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_JSONL = "./datos/validados/datos_tablas_api_ine_validos.jsonl"

OUTPUT_JSONL = "./datos/normalizados/dataset_ine_normalizado_api.jsonl"
OUTPUT_RESUMEN = "./datos/normalizados/resumen_normalizacion_api.json"
OUTPUT_ERRORES = "./datos/normalizados/errores_normalizacion_api.jsonl"


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


def append_jsonl(path, data):
    asegurar_carpeta(path)
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False) + "\n")


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
# CONVERSIONES
# ============================================================

def convertir_a_string(valor):
    if valor is None:
        return None

    if isinstance(valor, dict):
        return json.dumps(valor, ensure_ascii=False, sort_keys=True)

    if isinstance(valor, list):
        return json.dumps(valor, ensure_ascii=False, sort_keys=True)

    texto = str(valor).strip()
    return texto if texto else None


def convertir_a_float(valor):
    if valor is None or isinstance(valor, bool):
        return None, False

    if isinstance(valor, (int, float)):
        return float(valor), True

    if isinstance(valor, str):
        texto = valor.strip().replace(" ", "").replace(",", ".")
        if not texto:
            return None, False

        try:
            return float(texto), True
        except ValueError:
            return None, False

    return None, False


def convertir_a_int(valor):
    if valor is None or isinstance(valor, bool):
        return None, False

    if isinstance(valor, int):
        return valor, True

    if isinstance(valor, float) and valor.is_integer():
        return int(valor), True

    if isinstance(valor, str):
        texto = valor.strip().replace(",", ".")
        if not texto:
            return None, False

        try:
            return int(float(texto)), True
        except ValueError:
            return None, False

    return None, False


def parsear_posible_dict(valor):
    """
    Convierte valores que pueden venir como dict real o como string de dict.

    Ejemplos:
    {'Codigo': '03', 'Nombre': 'M03'}
    "{\"Codigo\": \"03\", \"Nombre\": \"M03\"}"
    """
    if isinstance(valor, dict):
        return valor

    if isinstance(valor, str):
        texto = valor.strip()

        if not texto:
            return None

        if (texto.startswith("{") and texto.endswith("}")):
            try:
                return json.loads(texto)
            except Exception:
                pass

            try:
                return ast.literal_eval(texto)
            except Exception:
                pass

    return None


# ============================================================
# EXTRACCIÓN GENÉRICA
# ============================================================

def obtener_primero(diccionario, claves):
    if not isinstance(diccionario, dict):
        return None, None

    for clave in claves:
        if clave in diccionario:
            valor = diccionario.get(clave)
            if valor is not None:
                return valor, clave

    return None, None


def obtener_array_datos(serie):
    if not isinstance(serie, dict):
        return []

    if isinstance(serie.get("Data"), list):
        return serie["Data"]

    if isinstance(serie.get("Datos"), list):
        return serie["Datos"]

    return []


def obtener_nombre_serie(serie):
    valor, _ = obtener_primero(
        serie,
        ["Nombre", "name", "Titulo", "Título", "titulo", "NombreSerie", "Serie"]
    )
    return convertir_a_string(valor)


def obtener_codigo_serie(serie):
    valor, _ = obtener_primero(
        serie,
        ["COD", "Codigo", "Código", "codigo", "Id", "ID"]
    )
    return convertir_a_string(valor)


def limpiar_metadata_serie(serie):
    if not isinstance(serie, dict):
        return {}

    return {
        clave: valor
        for clave, valor in serie.items()
        if clave not in ["Data", "Datos"]
    }


# ============================================================
# EXTRACCIÓN MEJORADA DE PERIODO / AÑO / UNIDAD
# ============================================================

def extraer_periodo_raw(punto):
    claves = [
        "Periodo",
        "periodo",
        "NombrePeriodo",
        "nombrePeriodo",
        "Anyo",
        "Año",
        "anyo",
        "Fecha",
        "fecha",
        "FK_Periodo"
    ]

    valor, clave = obtener_primero(punto, claves)
    return valor, clave


def normalizar_periodo(valor_periodo):
    """
    Devuelve:
    - periodo: texto usable
    - periodo_codigo
    - periodo_nombre

    Si viene dict:
    {'Codigo': '03', 'Nombre': 'M03'}
    """
    periodo_codigo = None
    periodo_nombre = None

    dict_periodo = parsear_posible_dict(valor_periodo)

    if dict_periodo:
        periodo_codigo = convertir_a_string(
            dict_periodo.get("Codigo")
            or dict_periodo.get("Código")
            or dict_periodo.get("codigo")
            or dict_periodo.get("Code")
        )

        periodo_nombre = convertir_a_string(
            dict_periodo.get("Nombre")
            or dict_periodo.get("nombre")
            or dict_periodo.get("Name")
        )

        if periodo_nombre:
            periodo = periodo_nombre
        elif periodo_codigo:
            periodo = periodo_codigo
        else:
            periodo = convertir_a_string(dict_periodo)

        return periodo, periodo_codigo, periodo_nombre

    periodo = convertir_a_string(valor_periodo)
    return periodo, periodo_codigo, periodo_nombre


def extraer_anyo_desde_objeto(obj):
    """
    Intenta extraer año de:
    - int/string directo
    - dict con Nombre/Codigo
    - strings tipo 2024(A), 2026, M03, etc.
    """
    if obj is None:
        return None, None

    dict_obj = parsear_posible_dict(obj)

    if dict_obj:
        for clave in ["Anyo", "Año", "anyo", "Year", "year"]:
            if clave in dict_obj:
                anyo, ok = convertir_a_int(dict_obj.get(clave))
                if ok:
                    return anyo, f"dict_{clave}"

        for clave in ["Nombre", "nombre", "Codigo", "Código", "codigo"]:
            if clave in dict_obj:
                anyo, origen = extraer_anyo_desde_objeto(dict_obj.get(clave))
                if anyo is not None:
                    return anyo, f"dict_{clave}_{origen}"

        return None, None

    anyo, ok = convertir_a_int(obj)
    if ok and 1800 <= anyo <= 2200:
        return anyo, "directo"

    texto = convertir_a_string(obj)
    if texto:
        match = re.search(r"(18|19|20|21)\d{2}", texto)
        if match:
            anyo, ok = convertir_a_int(match.group(0))
            if ok:
                return anyo, "regex"

    return None, None


def obtener_anyo_mejorado(punto, periodo, periodo_codigo, periodo_nombre):
    """
    Busca año en más sitios que la versión anterior.
    """
    claves_anyo = [
        "Anyo",
        "Año",
        "anyo",
        "Year",
        "year",
        "Fecha",
        "fecha"
    ]

    for clave in claves_anyo:
        if isinstance(punto, dict) and clave in punto:
            anyo, origen = extraer_anyo_desde_objeto(punto.get(clave))
            if anyo is not None:
                return anyo, f"punto_{clave}_{origen}"

    for candidato, nombre in [
        (periodo, "periodo"),
        (periodo_nombre, "periodo_nombre"),
        (periodo_codigo, "periodo_codigo")
    ]:
        anyo, origen = extraer_anyo_desde_objeto(candidato)
        if anyo is not None:
            return anyo, f"{nombre}_{origen}"

    # Algunos puntos temporales de WSTempus pueden traer metadata anidada
    for clave, valor in punto.items():
        if isinstance(valor, dict):
            anyo, origen = extraer_anyo_desde_objeto(valor)
            if anyo is not None:
                return anyo, f"punto_dict_{clave}_{origen}"

    return None, None


def obtener_fecha(punto):
    valor, _ = obtener_primero(punto, ["Fecha", "fecha", "Date", "date"])
    return convertir_a_string(valor)


def extraer_unidad_raw(serie, punto):
    claves = [
        "Unidad",
        "unidad",
        "UnidadMedida",
        "unidad_medida",
        "Medida",
        "medida"
    ]

    valor, clave = obtener_primero(serie, claves)
    if valor is not None:
        return valor, f"serie_{clave}"

    valor, clave = obtener_primero(punto, claves)
    if valor is not None:
        return valor, f"punto_{clave}"

    return None, None


def normalizar_unidad(valor_unidad):
    """
    Devuelve:
    - unidad: texto principal
    - unidad_nombre
    - unidad_codigo
    - unidad_abrev
    """
    unidad_nombre = None
    unidad_codigo = None
    unidad_abrev = None

    dict_unidad = parsear_posible_dict(valor_unidad)

    if dict_unidad:
        unidad_nombre = convertir_a_string(
            dict_unidad.get("Nombre")
            or dict_unidad.get("nombre")
            or dict_unidad.get("Name")
        )

        unidad_codigo = convertir_a_string(
            dict_unidad.get("Codigo")
            or dict_unidad.get("Código")
            or dict_unidad.get("codigo")
            or dict_unidad.get("Code")
        )

        unidad_abrev = convertir_a_string(
            dict_unidad.get("Abrev")
            or dict_unidad.get("abrev")
            or dict_unidad.get("Abreviatura")
        )

        unidad = unidad_nombre or unidad_abrev or unidad_codigo
        return unidad, unidad_nombre, unidad_codigo, unidad_abrev

    unidad = convertir_a_string(valor_unidad)
    return unidad, unidad_nombre, unidad_codigo, unidad_abrev


def obtener_valor(punto):
    for clave in ["Valor", "valor", "Value", "value"]:
        if isinstance(punto, dict) and clave in punto:
            valor, ok = convertir_a_float(punto.get(clave))
            return valor, ok, clave

    return None, False, None


# ============================================================
# NORMALIZACIÓN
# ============================================================

def normalizar_registro(registro):
    filas = []
    errores = []

    datos_api = registro.get("datos_api")

    if isinstance(datos_api, dict):
        series = [datos_api]
    elif isinstance(datos_api, list):
        series = datos_api
    else:
        return [], [{
            "id_tabla": registro.get("id_tabla"),
            "error": f"datos_api no soportado: {type(datos_api).__name__}"
        }]

    parametros_url = registro.get("parametros_url") or {}

    for indice_serie, serie in enumerate(series):
        if not isinstance(serie, dict):
            errores.append({
                "id_tabla": registro.get("id_tabla"),
                "error": "serie no es diccionario",
                "indice_serie": indice_serie
            })
            continue

        datos_temporales = obtener_array_datos(serie)

        if not datos_temporales:
            errores.append({
                "id_tabla": registro.get("id_tabla"),
                "error": "serie sin Data/Datos",
                "indice_serie": indice_serie,
                "nombre_serie": obtener_nombre_serie(serie)
            })
            continue

        nombre_serie = obtener_nombre_serie(serie)
        codigo_serie = obtener_codigo_serie(serie)
        metadata_serie_raw = json.dumps(
            limpiar_metadata_serie(serie),
            ensure_ascii=False,
            sort_keys=True
        )

        for indice_punto, punto in enumerate(datos_temporales):
            if not isinstance(punto, dict):
                errores.append({
                    "id_tabla": registro.get("id_tabla"),
                    "error": "punto temporal no es diccionario",
                    "indice_serie": indice_serie,
                    "indice_punto": indice_punto
                })
                continue

            valor, valor_ok, _ = obtener_valor(punto)

            if not valor_ok:
                errores.append({
                    "id_tabla": registro.get("id_tabla"),
                    "error": "valor no convertible a float",
                    "indice_serie": indice_serie,
                    "indice_punto": indice_punto,
                    "punto": punto
                })
                continue

            periodo_raw, _ = extraer_periodo_raw(punto)
            periodo, periodo_codigo, periodo_nombre = normalizar_periodo(periodo_raw)

            anyo, origen_anyo = obtener_anyo_mejorado(
                punto=punto,
                periodo=periodo,
                periodo_codigo=periodo_codigo,
                periodo_nombre=periodo_nombre
            )

            fecha = obtener_fecha(punto)

            unidad_raw, _ = extraer_unidad_raw(serie, punto)
            unidad, unidad_nombre, unidad_codigo, unidad_abrev = normalizar_unidad(unidad_raw)

            fila = {
                "letra": convertir_a_string(registro.get("Letra")),
                "dato_operacion": convertir_a_string(registro.get("Dato")),
                "href_operacion": convertir_a_string(registro.get("href_operacion")),

                "c": convertir_a_string(parametros_url.get("c")),
                "cid": convertir_a_string(parametros_url.get("cid")),
                "idp": convertir_a_string(parametros_url.get("idp")),

                "id_tabla": convertir_a_string(registro.get("id_tabla")),
                "titulo_tabla": convertir_a_string(registro.get("titulo_tabla")),
                "href_tabla": convertir_a_string(registro.get("href_tabla")),
                "url_api": convertir_a_string(registro.get("url_api")),

                "nombre_serie": convertir_a_string(nombre_serie),
                "codigo_serie": convertir_a_string(codigo_serie),

                "unidad": convertir_a_string(unidad),
                "unidad_nombre": convertir_a_string(unidad_nombre),
                "unidad_codigo": convertir_a_string(unidad_codigo),
                "unidad_abrev": convertir_a_string(unidad_abrev),

                "periodo": convertir_a_string(periodo),
                "periodo_codigo": convertir_a_string(periodo_codigo),
                "periodo_nombre": convertir_a_string(periodo_nombre),

                "anyo": anyo,
                "fecha": convertir_a_string(fecha),
                "valor": valor,

                "origen_anyo": convertir_a_string(origen_anyo),
                "datos_periodo_raw": json.dumps(punto, ensure_ascii=False, sort_keys=True),
                "metadata_serie_raw": metadata_serie_raw
            }

            filas.append(fila)

    return filas, errores


# ============================================================
# HILOS
# ============================================================

def procesar_linea(numero_linea, line):
    line = line.strip()

    if not line:
        return {
            "numero_linea": numero_linea,
            "filas": [],
            "errores": [],
            "linea_vacia": True
        }

    try:
        registro = json.loads(line)
    except json.JSONDecodeError as e:
        return {
            "numero_linea": numero_linea,
            "filas": [],
            "errores": [{
                "numero_linea": numero_linea,
                "error": f"JSON mal formado: {e}"
            }],
            "linea_vacia": False
        }

    filas, errores = normalizar_registro(registro)

    for error in errores:
        error["numero_linea"] = numero_linea

    return {
        "numero_linea": numero_linea,
        "filas": filas,
        "errores": errores,
        "linea_vacia": False
    }


def cargar_lineas(input_jsonl, max_lineas=None):
    tareas = []

    with open(input_jsonl, "r", encoding="utf-8") as file:
        for numero_linea, line in enumerate(file, start=1):
            if max_lineas is not None and len(tareas) >= max_lineas:
                break

            if not line.strip():
                continue

            tareas.append((numero_linea, line))

    return tareas


def escribir_resultados_y_resumen(resultados, input_jsonl, output_jsonl, output_resumen, output_errores):
    total_lineas = 0
    total_filas = 0
    total_errores = 0
    registros_sin_filas = 0

    nulos = {
        "titulo_tabla": 0,
        "periodo": 0,
        "periodo_codigo": 0,
        "periodo_nombre": 0,
        "anyo": 0,
        "fecha": 0,
        "unidad": 0,
        "unidad_nombre": 0,
        "nombre_serie": 0,
        "codigo_serie": 0
    }

    tipos_valor = {}
    origen_anyo_counter = {}
    ejemplos_filas = []
    ejemplos_errores = []

    resultados.sort(key=lambda x: x["numero_linea"])

    for resultado in resultados:
        if resultado.get("linea_vacia"):
            continue

        total_lineas += 1
        filas = resultado.get("filas", [])
        errores = resultado.get("errores", [])

        if not filas:
            registros_sin_filas += 1

        for fila in filas:
            append_jsonl(output_jsonl, fila)
            total_filas += 1

            for campo in nulos:
                if fila.get(campo) is None:
                    nulos[campo] += 1

            tipo = type(fila["valor"]).__name__
            tipos_valor[tipo] = tipos_valor.get(tipo, 0) + 1

            origen = fila.get("origen_anyo") or "null"
            origen_anyo_counter[origen] = origen_anyo_counter.get(origen, 0) + 1

            if len(ejemplos_filas) < 5:
                ejemplos_filas.append(fila)

        for error in errores:
            append_jsonl(output_errores, error)
            total_errores += 1

            if len(ejemplos_errores) < 10:
                ejemplos_errores.append(error)

    campos_salida = {
        "letra": "string",
        "dato_operacion": "string",
        "href_operacion": "string",
        "c": "string",
        "cid": "string",
        "idp": "string",
        "id_tabla": "string",
        "titulo_tabla": "string",
        "href_tabla": "string",
        "url_api": "string",
        "nombre_serie": "string",
        "codigo_serie": "string",
        "unidad": "string",
        "unidad_nombre": "string",
        "unidad_codigo": "string",
        "unidad_abrev": "string",
        "periodo": "string",
        "periodo_codigo": "string",
        "periodo_nombre": "string",
        "anyo": "int",
        "fecha": "string",
        "valor": "float",
        "origen_anyo": "string",
        "datos_periodo_raw": "string_json",
        "metadata_serie_raw": "string_json"
    }

    completitud = {}
    for campo, num_nulos in nulos.items():
        completitud[campo] = round(((total_filas - num_nulos) / total_filas) * 100, 2) if total_filas else 0

    completitud["valor"] = 100.0 if total_filas else 0

    resumen = {
        "fecha_ejecucion": datetime.now().isoformat(timespec="seconds"),
        "input_jsonl": input_jsonl,
        "output_jsonl": output_jsonl,
        "output_errores": output_errores,
        "total_lineas_entrada": total_lineas,
        "total_filas_normalizadas": total_filas,
        "total_errores_normalizacion": total_errores,
        "registros_sin_filas": registros_sin_filas,
        "campos_salida": campos_salida,
        "tipos_valor": tipos_valor,
        "nulos": nulos,
        "porcentaje_completitud": completitud,
        "origen_anyo": origen_anyo_counter,
        "ejemplos_filas": ejemplos_filas,
        "ejemplos_errores": ejemplos_errores
    }

    guardar_json(output_resumen, resumen)

    return resumen


def normalizar_jsonl_mejorado(
    input_jsonl=INPUT_JSONL,
    output_jsonl=OUTPUT_JSONL,
    output_resumen=OUTPUT_RESUMEN,
    output_errores=OUTPUT_ERRORES,
    max_lineas=None,
    num_hilos=None,
    sobrescribir=True,
    console_output=None
):
    if not os.path.exists(input_jsonl):
        print(f"[ERROR] No existe el fichero de entrada: {input_jsonl}")
        return None

    if sobrescribir:
        borrar_si_existe(output_jsonl)
        borrar_si_existe(output_errores)
        borrar_si_existe(output_resumen)

    tareas = cargar_lineas(input_jsonl, max_lineas=max_lineas)

    if not tareas:
        print("[ERROR] No hay líneas para normalizar.")
        return None

    cpu_total, hilos_calculados = calcular_hilos_trabajo()

    if num_hilos is None:
        num_hilos = hilos_calculados

    if num_hilos < 1:
        num_hilos = 1

    print("==============================================")
    print(" NORMALIZACIÓN MEJORADA JSONL API INE CON HILOS")
    print("==============================================")
    print(f"[INFO] Entrada: {input_jsonl}")
    print(f"[INFO] Salida:  {output_jsonl}")
    print(f"[INFO] CPU lógicas detectadas: {cpu_total}")
    print(f"[INFO] Hilos calculados: {hilos_calculados}")
    print(f"[INFO] Hilos usados: {num_hilos}")
    print(f"[INFO] Líneas a procesar: {len(tareas)}")

    resultados = []

    with ThreadPoolExecutor(max_workers=num_hilos) as executor:
        futuros = {
            executor.submit(procesar_linea, numero_linea, line): numero_linea
            for numero_linea, line in tareas
        }

        with tqdm(total=len(futuros), desc="NORMALIZANDO MEJORADO", file=console_output) as pbar:
            for futuro in as_completed(futuros):
                try:
                    resultados.append(futuro.result())
                except Exception as e:
                    numero_linea = futuros[futuro]
                    resultados.append({
                        "numero_linea": numero_linea,
                        "filas": [],
                        "errores": [{
                            "numero_linea": numero_linea,
                            "error": f"Error no controlado en hilo: {e}"
                        }],
                        "linea_vacia": False
                    })

                pbar.update(1)

    print("[INFO] Escribiendo resultados normalizados...")
    resumen = escribir_resultados_y_resumen(
        resultados=resultados,
        input_jsonl=input_jsonl,
        output_jsonl=output_jsonl,
        output_resumen=output_resumen,
        output_errores=output_errores
    )

    print("==============================================")
    print("[OK] Normalización mejorada finalizada")
    print(f"[INFO] Líneas de entrada: {resumen['total_lineas_entrada']}")
    print(f"[INFO] Filas normalizadas: {resumen['total_filas_normalizadas']}")
    print(f"[INFO] Errores: {resumen['total_errores_normalizacion']}")
    print(f"[INFO] Registros sin filas: {resumen['registros_sin_filas']}")
    print(f"[INFO] JSONL normalizado: {output_jsonl}")
    print(f"[INFO] Resumen: {output_resumen}")
    print(f"[INFO] Errores: {output_errores}")
    print("==============================================")

    return resumen


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Normaliza datos_tablas_api_ine_validos.jsonl con limpieza mejorada de periodo, año y unidad."
    )

    parser.add_argument("--input", default=INPUT_JSONL)
    parser.add_argument("--output", default=OUTPUT_JSONL)
    parser.add_argument("--resumen", default=OUTPUT_RESUMEN)
    parser.add_argument("--errores", default=OUTPUT_ERRORES)
    parser.add_argument("--max-lineas", type=int, default=None)
    parser.add_argument("--num-hilos", type=int, default=None)

    args = parser.parse_args()

    ejecutar(
    input_jsonl=args.input,
    output_jsonl=args.output,
    output_resumen=args.resumen,
    output_errores=args.errores,
    max_lineas=args.max_lineas,
    num_hilos=args.num_hilos
    )


# ============================================================
# EJECUCIÓN DESDE OTROS MÓDULOS
# ============================================================

def ejecutar(
        input_jsonl=INPUT_JSONL,
        output_jsonl=OUTPUT_JSONL,
        output_resumen=OUTPUT_RESUMEN,
        output_errores=OUTPUT_ERRORES,
        max_lineas=None,
        num_hilos=None):

    return normalizar_jsonl_mejorado(
        input_jsonl=input_jsonl,
        output_jsonl=output_jsonl,
        output_resumen=output_resumen,
        output_errores=output_errores,
        max_lineas=max_lineas,
        num_hilos=num_hilos
    )


if __name__ == "__main__":
    main()
