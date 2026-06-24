# Sistema inteligente para la generación automática de informes preliminares de viabilidad territorial mediante datos abiertos del INE

Este proyecto implementa un sistema capaz de recopilar, procesar e interpretar información estadística procedente del Instituto Nacional de Estadística (INE) con el objetivo de generar informes preliminares de viabilidad territorial para distintos tipos de actividades económicas.

La aplicación está organizada en tres capas principales:

* **Capa de datos**: recopilación, validación, normalización y almacenamiento de la información en DuckDB.
* **Capa semántica**: generación de documentos semánticos y creación del índice vectorial FAISS.
* **Capa de respuesta**: recuperación de información y generación automática de informes mediante modelos de lenguaje.

La ejecución del sistema se realiza desde un único punto de entrada:

```bash
python main.py
```

## Estructura general

```text
codigo/
configuracion/
datos/
registros/
resultados/
main.py
```

## Requisitos

Las dependencias necesarias pueden instalarse mediante:

```bash
pip install -r requirements.txt
```

## Autor

Jaime Piñeiro Ibáñez

Proyecto Fin de Grado: Sistema inteligente para la generación automática de informes de viabilidad territorial mediante técnicas de scraping y datos abiertos del INE
