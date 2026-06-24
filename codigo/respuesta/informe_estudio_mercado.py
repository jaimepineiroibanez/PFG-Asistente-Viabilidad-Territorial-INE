
import json
import os

from configuracion.config_ine import MODELO_LLM


# ============================================================
# GENERACIÓN DEL INFORME FINAL
# ============================================================


def construir_prompt_informe_estudio(contexto_estudio):
    """
    Construye el prompt para generar el informe final.
    """

    return f"""
Eres un analista especializado en generación automática de informes preliminares de viabilidad territorial utilizando datos oficiales del Instituto Nacional de Estadística (INE).

Tu función consiste en describir el contexto socioeconómico de un territorio para una posible implantación empresarial.

NO estás realizando un estudio de mercado profesional.

NO dispones de información sobre:
- competencia directa
- demanda real
- precios
- alquileres
- hábitos de consumo
- clientes potenciales reales

Por tanto:

- No evalúes rentabilidad.
- No recomiendes invertir.
- No recomiendes abrir o no abrir el negocio.
- No utilices expresiones como:
  "es una buena oportunidad",
  "es recomendable abrir",
  "el negocio será rentable".

Limítate a describir el contexto territorial utilizando exclusivamente los datos recuperados.
Tu tarea es elaborar un informe preliminar para un emprendedor.

IMPORTANTE:

- Utiliza únicamente la información presente en el contexto.
- No inventes datos.
- No inventes años.
- No inventes valores.
- No inventes conclusiones.
- No afirmes que un negocio será rentable.
- No recomiendes abrir o no abrir el negocio.
- Utiliza lenguaje prudente.
- Si faltan datos para algún apartado, indícalo.
- Explica las limitaciones cuando sea necesario.
- Menciona años y periodos cuando estén disponibles.
- Si un dato pertenece a un municipio o zona distinta del territorio principal solicitado, indícalo claramente y no lo uses como representativo del conjunto del territorio.
- Prioriza siempre los datos del territorio exacto solicitado frente a municipios, secciones censales o zonas parciales.
- Cuando un pilar tenga datos parciales o relacionados, debe indicarse explícitamente que no son datos suficientes para una conclusión fuerte
- No te limites a enumerar datos estadísticos.
- Interpreta brevemente qué implican los indicadores para el contexto territorial.
- Explica si un indicador puede favorecer, limitar o no aportar información suficiente para valorar el territorio.
- Utiliza expresiones prudentes como:
  "puede favorecer",
  "puede limitar",
  "sugiere",
  "apunta a",
  "debe interpretarse con cautela",
  "no permite extraer conclusiones sólidas".
- Diferencia claramente entre:
  a) datos útiles para caracterizar el territorio
  b) datos insuficientes para evaluar el negocio concreto.
- Cuando existan datos demográficos, económicos o empresariales relevantes, explica brevemente su posible impacto sobre la implantación de actividades económicas en general.
- No realices recomendaciones empresariales específicas.
- No utilices términos sectoriales inventados.
- Si no existen datos específicos del negocio analizado, indícalo claramente.
- No repitas en todos los apartados que faltan datos de demanda, competencia o hábitos de consumo; menciónalo únicamente en Limitaciones.
- Cuando aparezcan datos relacionados con el negocio, diferéncialos claramente de los datos territoriales generales.

Estructura obligatoria:

# # INFORME PRELIMINAR DE VIABILIDAD TERRITORIAL

## Negocio analizado

## Territorio analizado

## 1. Contexto poblacional

Analiza:
- población
- censo
- volumen potencial de clientes

## 2. Perfil demográfico

Analiza:
- edad
- sexo
- grupos de población relevantes

## 3. Situación económica

Analiza:
- renta
- capacidad económica

## 4. Situacion laboral

Analiza:
- empleo
- paro
- actividad económica

## 5. Tejido empresarial

Analiza:
- número de empresas
- estructura empresarial

## 6. Actividad empresarial

Analiza:
- sectores económicos
- actividad predominante
- sector servicios
- locales por actividad económica

## 7. Sector específico del negocio

Analiza únicamente los datos recuperados directamente relacionados con el negocio indicado.

Si no existen datos específicos del negocio analizado, indica claramente:
"No se han recuperado datos específicos del sector del negocio analizado."

No inventes información sectorial.
No extrapoles desde sectores generales.
Diferencia claramente entre:
- datos territoriales generales
- datos específicos o relacionados con el negocio

## 8. Turismo

Inclúyelo únicamente si existen datos turísticos.

## 9. Limitaciones del análisis

## 10. Valoración territorial preliminar
La valoración territorial debe resumir:

- fortalezas observadas en el territorio
- debilidades observadas en el territorio
- oportunidades territoriales generales observadas en los datos
- limitaciones de los datos disponibles

Debe responder a la pregunta:

"¿Qué características relevantes presenta este territorio para una posible implantación empresarial?"

No debe responder a:

"¿Debe abrirse este negocio?"

No debe indicar si el negocio tendrá éxito.

No debe recomendar invertir o no invertir.

Debe mantener un enfoque descriptivo y territorial.

La conclusión debe ser prudente y basada únicamente en los datos recuperados.

Contexto:

{json.dumps(contexto_estudio, ensure_ascii=False, indent=2)}

Informe:
""".strip()


def generar_informe_con_llm(
    contexto_estudio,
    modelo_llm=MODELO_LLM
):
    """
    Genera el informe final usando OpenAI.
    """

    try:
        from openai import OpenAI
    except ImportError:
        return (
            "[ERROR] No está instalada la librería openai.\n"
            "Ejecuta: pip install openai"
        )

    api_key = (
        os.getenv("API_KEY_INE_CHATBOT")
        or os.getenv("OPENAI_API_KEY")
    )

    if not api_key:
        return (
            "[ERROR] No se ha encontrado "
            "API_KEY_INE_CHATBOT ni OPENAI_API_KEY."
        )

    client = OpenAI(api_key=api_key)

    contexto_reducido = reducir_contexto_para_informe(contexto_estudio)
    prompt = construir_prompt_informe_estudio(contexto_reducido)

    response = client.responses.create(
        model=modelo_llm,
        input=prompt
    )

    return response.output_text.strip()


def generar_informe_plantilla(contexto_estudio):
    """
    Informe básico sin LLM.
    Muy útil para depurar el pipeline.
    """

    negocio = contexto_estudio.get("negocio")
    territorio = contexto_estudio.get("territorio")

    resultados = contexto_estudio.get(
        "resultados_por_pilar",
        {}
    )

    lineas = []

    lineas.append("=" * 80)
    lineas.append("ESTUDIO PRELIMINAR DE MERCADO")
    lineas.append("=" * 80)
    lineas.append("")

    lineas.append(f"Negocio: {negocio}")
    lineas.append(f"Territorio: {territorio}")
    lineas.append("")

    for pilar, resultado in resultados.items():

        lineas.append("-" * 80)
        lineas.append(f"PILAR: {pilar.upper()}")
        lineas.append("-" * 80)

        pregunta = resultado.get("pregunta")

        if pregunta:
            lineas.append(
                f"Consulta ejecutada: {pregunta}"
            )

        contexto_llm = resultado.get(
            "contexto_llm",
            {}
        )

        datos = contexto_llm.get(
            "datos_recuperados",
            []
        )

        if not datos:
            lineas.append(
                "No se han recuperado datos."
            )
            lineas.append("")
            continue

        for bloque in datos[:3]:

            lineas.append(
                f"Tabla: {bloque.get('id_tabla')}"
            )

            lineas.append(
                f"Operación: {bloque.get('operacion')}"
            )

            serie = bloque.get("serie")

            if serie:
                lineas.append(
                    f"Serie: {serie}"
                )

            registros = bloque.get(
                "datos",
                []
            )

            for fila in registros[:5]:

                anyo = fila.get("anyo")
                periodo = fila.get("periodo")
                valor = fila.get("valor")
                unidad = fila.get("unidad")

                lineas.append(
                    f"  - {anyo} | "
                    f"{periodo} | "
                    f"{valor} {unidad or ''}"
                )

        lineas.append("")

    return "\n".join(lineas)


def generar_informe_estudio(
    contexto_estudio,
    usar_llm=True,
    modelo_llm=MODELO_LLM
):
    """
    Punto de entrada principal.
    """

    if usar_llm:
        return generar_informe_con_llm(
            contexto_estudio=contexto_estudio,
            modelo_llm=modelo_llm
        )

    return generar_informe_plantilla(
        contexto_estudio
    )

def reducir_contexto_para_informe(contexto_estudio, max_bloques_por_pilar=8, max_filas_por_bloque=6):
    contexto_reducido = {
        "negocio": contexto_estudio.get("negocio"),
        "territorio": contexto_estudio.get("territorio"),
        "advertencias": contexto_estudio.get("advertencias", []),
        "pilares": {}
    }

    resultados = contexto_estudio.get("resultados_por_pilar", {})

    for pilar, resultados_pilar in resultados.items():

        if isinstance(resultados_pilar, dict):
            resultados_pilar = [resultados_pilar]

        bloques_pilar = []

        for resultado in resultados_pilar:
            contexto_llm = resultado.get("contexto_llm", {})
            datos_recuperados = contexto_llm.get("datos_recuperados", [])

            for bloque in datos_recuperados:
                filas_reducidas = []

                for fila in bloque.get("datos", [])[:max_filas_por_bloque]:
                    filas_reducidas.append({
                        "serie": fila.get("serie"),
                        "anyo": fila.get("anyo"),
                        "periodo": fila.get("periodo"),
                        "valor": fila.get("valor"),
                        "unidad": fila.get("unidad"),
                    })

                bloques_pilar.append({
                    "consulta": resultado.get("pregunta"),
                    "id_tabla": bloque.get("id_tabla"),
                    "operacion": bloque.get("operacion"),
                    "serie": bloque.get("serie"),
                    "unidad": bloque.get("unidad"),
                    "datos": filas_reducidas,
                })

        contexto_reducido["pilares"][pilar] = {
            "datos": bloques_pilar[:max_bloques_por_pilar]
        }

    return contexto_reducido