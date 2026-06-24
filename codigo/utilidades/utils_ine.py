import os
import json
import unicodedata

# ============================================================
# UTILIDADES GENERALES DEL SISTEMA INE
# ============================================================


def asegurar_carpeta(path):
    carpeta = os.path.dirname(path)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)


def guardar_json(path, data):
    if not path:
        return
    asegurar_carpeta(path)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)
    print(f"[OK] JSON guardado en: {path}")


def cargar_json(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"No existe el fichero JSON: {path}")
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def normalizar_texto(texto):
    if texto is None:
        return ""
    texto = str(texto).lower().strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto


def calcular_hilos_trabajo():
    cpu_total = os.cpu_count() or 1
    restantes = max(cpu_total - 1, 0)
    num_hilos_trabajo = (restantes // 2) + 1
    return cpu_total, num_hilos_trabajo


def valor_a_texto(valor):
    if valor is None:
        return "No disponible"
    try:
        v = float(valor)
        if v.is_integer():
            return str(int(v))
        return str(round(v, 4))
    except Exception:
        return str(valor)
