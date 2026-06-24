import json
import os
import argparse
from collections import Counter


INPUT_JSONL = "./datos/originales/datos_tablas_api_ine.jsonl"
OUTPUT_RESUMEN = "./datos/validados/resumen_validacion_api_ine.json"
OUTPUT_VALIDOS = "./datos/validados/datos_tablas_api_ine_validos.jsonl"
OUTPUT_INVALIDOS = "./datos/validados/datos_tablas_api_ine_invalidos.jsonl"


def asegurar_carpeta(path):
    carpeta = os.path.dirname(path)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)


def guardar_json(path, data):
    asegurar_carpeta(path)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def append_jsonl(path, data):
    asegurar_carpeta(path)
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False) + "\n")


def borrar_si_existe(path):
    if os.path.exists(path):
        os.remove(path)


def detectar_tipo_datos_api(datos_api):
    if datos_api is None:
        return "null"

    if isinstance(datos_api, list):
        if len(datos_api) == 0:
            return "lista_vacia"

        primer = datos_api[0]

        if isinstance(primer, dict):
            claves = set(primer.keys())

            if "Data" in claves:
                return "lista_series_con_Data"

            if "Datos" in claves:
                return "lista_series_con_Datos"

            return "lista_diccionarios_sin_Data"

        return "lista_valores"

    if isinstance(datos_api, dict):
        if len(datos_api) == 0:
            return "dict_vacio"

        claves = set(datos_api.keys())

        if "Data" in claves:
            return "dict_con_Data"

        if "Datos" in claves:
            return "dict_con_Datos"

        return "dict_otro"

    return type(datos_api).__name__


def contar_observaciones(datos_api):
    if datos_api is None:
        return 0

    total = 0

    if isinstance(datos_api, list):
        for elemento in datos_api:
            if isinstance(elemento, dict):
                if isinstance(elemento.get("Data"), list):
                    total += len(elemento["Data"])
                elif isinstance(elemento.get("Datos"), list):
                    total += len(elemento["Datos"])

    elif isinstance(datos_api, dict):
        if isinstance(datos_api.get("Data"), list):
            total += len(datos_api["Data"])
        elif isinstance(datos_api.get("Datos"), list):
            total += len(datos_api["Datos"])

    return total


def contar_series(datos_api):
    if isinstance(datos_api, list):
        return len(datos_api)

    if isinstance(datos_api, dict):
        return 1

    return 0


def extraer_claves_principales(datos_api):
    claves = Counter()

    if isinstance(datos_api, list):
        for elemento in datos_api[:20]:
            if isinstance(elemento, dict):
                claves.update(elemento.keys())

    elif isinstance(datos_api, dict):
        claves.update(datos_api.keys())

    return dict(claves)


def validar_registro(registro, numero_linea):
    errores = []
    avisos = []

    id_tabla = registro.get("id_tabla")
    estado = registro.get("estado")
    datos_api = registro.get("datos_api")

    if not id_tabla:
        errores.append("Falta id_tabla")

    if estado != "OK":
        errores.append(f"Estado no OK: {estado}")

    if datos_api is None:
        errores.append("datos_api es null")

    tipo_estructura = detectar_tipo_datos_api(datos_api)
    num_series = contar_series(datos_api)
    num_observaciones = contar_observaciones(datos_api)
    claves_principales = extraer_claves_principales(datos_api)

    if tipo_estructura in ["null", "lista_vacia", "dict_vacio"]:
        errores.append(f"Respuesta vacia: {tipo_estructura}")

    if num_series == 0:
        errores.append("No se han detectado series")

    if num_observaciones == 0:
        avisos.append("No se han detectado observaciones en Data/Datos")

    if "Data" not in claves_principales and "Datos" not in claves_principales:
        avisos.append("No aparece clave Data/Datos en las claves principales")

    es_valido = len(errores) == 0

    detalle = {
        "numero_linea": numero_linea,
        "id_tabla": id_tabla,
        "Dato": registro.get("Dato"),
        "titulo_tabla": registro.get("titulo_tabla"),
        "url_api": registro.get("url_api"),
        "estado": estado,
        "valido": es_valido,
        "errores": errores,
        "avisos": avisos,
        "tipo_estructura": tipo_estructura,
        "num_series": num_series,
        "num_observaciones": num_observaciones,
        "claves_principales": claves_principales
    }

    return es_valido, detalle


def validar_jsonl(
    input_jsonl=INPUT_JSONL,
    output_resumen=OUTPUT_RESUMEN,
    output_validos=OUTPUT_VALIDOS,
    output_invalidos=OUTPUT_INVALIDOS,
    max_lineas=None,
    guardar_separados=True
):
    if not os.path.exists(input_jsonl):
        print(f"[ERROR] No existe el fichero: {input_jsonl}")
        return None

    if guardar_separados:
        borrar_si_existe(output_validos)
        borrar_si_existe(output_invalidos)

    total_lineas = 0
    json_mal_formado = 0
    validos = 0
    invalidos = 0

    errores_counter = Counter()
    avisos_counter = Counter()
    estructuras_counter = Counter()
    claves_counter = Counter()

    ejemplos_invalidos = []
    ejemplos_validos = []
    tablas_sin_observaciones = []
    observaciones_por_tabla = []

    print("==============================================")
    print(" VALIDACION JSONL API INE")
    print("==============================================")
    print(f"[INFO] Entrada: {input_jsonl}")

    with open(input_jsonl, "r", encoding="utf-8") as file:
        for numero_linea, line in enumerate(file, start=1):
            if max_lineas is not None and total_lineas >= max_lineas:
                break

            line = line.strip()

            if not line:
                continue

            total_lineas += 1

            try:
                registro = json.loads(line)
            except json.JSONDecodeError as e:
                json_mal_formado += 1
                invalidos += 1

                detalle_error = {
                    "numero_linea": numero_linea,
                    "valido": False,
                    "errores": [f"JSON mal formado: {e}"],
                    "contenido_linea": line[:500]
                }

                if len(ejemplos_invalidos) < 10:
                    ejemplos_invalidos.append(detalle_error)

                if guardar_separados:
                    append_jsonl(output_invalidos, detalle_error)

                continue

            es_valido, detalle = validar_registro(registro, numero_linea)

            estructuras_counter[detalle["tipo_estructura"]] += 1
            claves_counter.update(detalle["claves_principales"].keys())

            for error in detalle["errores"]:
                errores_counter[error] += 1

            for aviso in detalle["avisos"]:
                avisos_counter[aviso] += 1

            observaciones_por_tabla.append({
                "id_tabla": detalle["id_tabla"],
                "Dato": detalle["Dato"],
                "titulo_tabla": detalle["titulo_tabla"],
                "num_series": detalle["num_series"],
                "num_observaciones": detalle["num_observaciones"]
            })

            if detalle["num_observaciones"] == 0:
                tablas_sin_observaciones.append(detalle)

            if es_valido:
                validos += 1

                if len(ejemplos_validos) < 5:
                    ejemplos_validos.append(detalle)

                if guardar_separados:
                    append_jsonl(output_validos, registro)

            else:
                invalidos += 1

                if len(ejemplos_invalidos) < 10:
                    ejemplos_invalidos.append(detalle)

                if guardar_separados:
                    append_jsonl(output_invalidos, {
                        "detalle_validacion": detalle,
                        "registro_original": registro
                    })

    observaciones_ordenadas = sorted(
        observaciones_por_tabla,
        key=lambda x: x["num_observaciones"],
        reverse=True
    )

    resumen = {
        "input_jsonl": input_jsonl,
        "total_lineas_procesadas": total_lineas,
        "json_mal_formado": json_mal_formado,
        "validos": validos,
        "invalidos": invalidos,
        "porcentaje_validos": round((validos / total_lineas) * 100, 2) if total_lineas else 0,
        "estructuras_detectadas": dict(estructuras_counter),
        "errores_mas_frecuentes": dict(errores_counter.most_common()),
        "avisos_mas_frecuentes": dict(avisos_counter.most_common()),
        "claves_principales_detectadas": dict(claves_counter.most_common()),
        "top_10_tablas_mas_observaciones": observaciones_ordenadas[:10],
        "top_10_tablas_menos_observaciones": observaciones_ordenadas[-10:] if observaciones_ordenadas else [],
        "num_tablas_sin_observaciones": len(tablas_sin_observaciones),
        "ejemplos_validos": ejemplos_validos,
        "ejemplos_invalidos": ejemplos_invalidos,
        "output_validos": output_validos if guardar_separados else None,
        "output_invalidos": output_invalidos if guardar_separados else None
    }

    guardar_json(output_resumen, resumen)

    print("==============================================")
    print("[OK] Validacion finalizada")
    print(f"[INFO] Lineas procesadas: {total_lineas}")
    print(f"[INFO] Registros validos: {validos}")
    print(f"[INFO] Registros invalidos: {invalidos}")
    print(f"[INFO] JSON mal formado: {json_mal_formado}")
    print(f"[INFO] Porcentaje validos: {resumen['porcentaje_validos']}%")
    print(f"[INFO] Resumen: {output_resumen}")

    if guardar_separados:
        print(f"[INFO] Validos: {output_validos}")
        print(f"[INFO] Invalidos: {output_invalidos}")

    print("==============================================")

    return resumen


def main():
    parser = argparse.ArgumentParser(
        description="Valida el JSONL descargado desde la API del INE."
    )

    parser.add_argument("--input", default=INPUT_JSONL)
    parser.add_argument("--resumen", default=OUTPUT_RESUMEN)
    parser.add_argument("--validos", default=OUTPUT_VALIDOS)
    parser.add_argument("--invalidos", default=OUTPUT_INVALIDOS)

    parser.add_argument(
        "--max-lineas",
        type=int,
        default=None,
        help="Numero maximo de lineas a validar."
    )

    parser.add_argument(
        "--no-separar",
        action="store_true",
        help="No genera JSONL separado de validos e invalidos."
    )

    args = parser.parse_args()

    ejecutar(
    input_jsonl=args.input,
    output_resumen=args.resumen,
    output_validos=args.validos,
    output_invalidos=args.invalidos,
    max_lineas=args.max_lineas,
    guardar_separados=not args.no_separar
    )

# ============================================================
# EJECUCIÓN DESDE OTROS MÓDULOS
# ============================================================
def ejecutar(
        input_jsonl=INPUT_JSONL,
        output_resumen=OUTPUT_RESUMEN,
        output_validos=OUTPUT_VALIDOS,
        output_invalidos=OUTPUT_INVALIDOS,
        max_lineas=None,
        guardar_separados=True):

    return validar_jsonl(
        input_jsonl=input_jsonl,
        output_resumen=output_resumen,
        output_validos=output_validos,
        output_invalidos=output_invalidos,
        max_lineas=max_lineas,
        guardar_separados=guardar_separados
    )

if __name__ == "__main__":
    main()
