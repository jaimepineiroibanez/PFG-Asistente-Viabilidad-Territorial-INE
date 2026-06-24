import json
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from html import unescape

DOMINIO_URL = "https://www.ine.es"

HEADERS = {
    "User-Agent": "PFG-Scraper-INE/1.0 (j.pineiroi@alumnos.upm.es)"
}

URL_INDICE_AZ = "https://www.ine.es/dyngs/INEbase/indiceAZ.htm"

OUTPUT_JSON = "./datos/originales/resultado_indice_url.json"


def get_html(url):
    """Descarga el HTML desde la URL especificada y lo devuelve como texto."""
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return response.text


def normalizar_html(html):
    """
    Normaliza el HTML de entrada.

    Sirve para dos casos:
    1. HTML real descargado de INE.
    2. HTML guardado desde Firefox como 'view-source:', donde las etiquetas reales
       aparecen escapadas dentro de spans.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Si el fichero es una vista de código fuente de Firefox, el HTML útil está
    # escapado como texto dentro del body id="viewsource".
    body = soup.find("body", id="viewsource")
    if body:
        return unescape(body.get_text())

    return html


def parse_html_indice(html):
    """Extrae el índice A-Z del HTML nuevo del INEbase.

    Devuelve una estructura equivalente a la del parser antiguo:
    [
        {
            "Letra": "A",
            "resultado_indice": [
                {
                    "Dato": "...",
                    "href": "https://www.ine.es/...",
                    "Tablas_mas_consultadas": []
                }
            ]
        }
    ]
    """
    html = normalizar_html(html)
    soup = BeautifulSoup(html, "html.parser")

    lista_final = []
    articulos = soup.find_all("article", class_="columnas")

    if not articulos:
        print("[ERROR] No se han encontrado bloques <article class='columnas'> en el HTML")
        return lista_final

    for articulo in articulos:
        letra = articulo.get("data-letter")

        if not letra:
            cabecera = articulo.find("header")
            letra = cabecera.get_text(strip=True) if cabecera else None

        if not letra:
            continue

        letra_actual = {"Letra": letra, "resultado_indice": []}

        for enlace in articulo.find_all("a", href=True):
            texto = enlace.get_text(" ", strip=True)
            href_completa = urljoin(DOMINIO_URL, enlace["href"])

            if texto:
                letra_actual["resultado_indice"].append({
                    "Dato": texto,
                    "href": href_completa,
                    "Tablas_mas_consultadas": []
                })

        lista_final.append(letra_actual)

    return lista_final


def save_to_json(data, filename):
    """Guarda los datos en un fichero JSON."""
    try:
        if not filename.endswith(".json"):
            filename += ".json"

        carpeta = os.path.dirname(filename)
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)

        with open(filename, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)

    except Exception as e:
        print(f"Error al guardar los datos en JSON: {e}")


def obtenerListadoIndiceURL(url):
    """Obtiene el listado A-Z desde una URL."""
    try:
        html = get_html(url)
        return parse_html_indice(html)
    except requests.exceptions.HTTPError as e:
        print(f"Error HTTP: {e}")
    except requests.exceptions.ConnectionError:
        print("Error de conexión. Verifica tu internet o la URL.")
    except requests.exceptions.Timeout:
        print("La solicitud tardó demasiado en responder.")
    except requests.exceptions.RequestException as e:
        print(f"Ocurrió un error inesperado: {e}")
    return []


def ejecutar(output_json=OUTPUT_JSON):
    """
    Obtiene el índice A-Z del INE y guarda el resultado.
    """

    datos = obtenerListadoIndiceURL(URL_INDICE_AZ)

    save_to_json(
        datos,
        output_json
    )

    return datos