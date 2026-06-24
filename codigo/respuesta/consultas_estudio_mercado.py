
# ============================================================
# CONSULTAS INTERNAS DEL ESTUDIO DE MERCADO
# ============================================================

PILARES_BASE = [
    "mercado",
    "demografia",
    "economia",
    "laboral",
    "empresas",
    "actividad_empresarial",
    "sector_negocio"
]

NEGOCIOS_TURISTICOS = {
    "hotel",
    "hostal",
    "apartamento turistico",
    "apartamento turístico",
    "casa rural",
    "alojamiento turistico",
    "alojamiento turístico",
    "camping",
    "albergue",
    "pensión",
    "pension",
    "apartahotel",
    "hotel rural",
    "hostel",
}

# ============================================================
# SELECCIÓN DE PILARES
# ============================================================

def seleccionar_pilares(negocio):
    """
    Devuelve los pilares que deben analizarse
    para el tipo de negocio indicado.
    """

    negocio = negocio.lower().strip()

    pilares = PILARES_BASE.copy()

    if any(tipo in negocio for tipo in NEGOCIOS_TURISTICOS):
        pilares.append("turismo")

    return pilares

# ============================================================
# CONSULTAS POR PILAR
# ============================================================

CONSULTAS_POR_PILAR = {
    "mercado": [
        "censo de población en {territorio}",
        "población de {territorio} según censo",
    ],

    "demografia": [
        "población por sexo y edad en {territorio}",
        "edad media de la población en {territorio}",
        "población mayor de 65 años en {territorio}",
        "población menor de 5 años en {territorio}",
    ],

    "economia": [
        "renta neta media por persona en {territorio}",
        "renta neta media por hogar en {territorio}",
    ],

    "laboral": [
        "indicadores laborales en {territorio}",
        "tasa de paro en {territorio}",
        "actividad y paro en {territorio}",
        "coste laboral en {territorio}",
    ],

    "empresas": [
        "número de empresas en {territorio}",
        "estructura empresarial en {territorio}",
        "tipos de empresa en {territorio}",
    ],

    "actividad_empresarial": [
        "sectores económicos en {territorio}",
        "empresas por sector económico en {territorio}",
        "locales por actividad económica en {territorio}",
        "sector servicios en {territorio}",
    ],

    "turismo": [
        "viajeros y pernoctaciones en {territorio}",
        "ocupación hotelera en {territorio}",
        "plazas hoteleras en {territorio}",
        "establecimientos hoteleros en {territorio}",
    ],
    
    "sector_negocio": [
        "{negocio} en {territorio}",
        "empresas de {negocio} en {territorio}",
        "locales de {negocio} en {territorio}",
        "actividad relacionada con {negocio} en {territorio}",
        "sector relacionado con {negocio} en {territorio}",
        "servicios relacionados con {negocio} en {territorio}",
    ],
    
}

# ============================================================
# GENERACIÓN DE CONSULTAS
# ============================================================

def generar_consultas_por_pilar(territorio, pilares, negocio=None):
    """
    Genera varias consultas por cada pilar.

    Las consultas generales caracterizan el territorio.
    Las consultas con negocio introducen una búsqueda semántica específica
    sobre la actividad analizada.
    """

    consultas = {}

    negocio = (negocio or "").strip()

    for pilar in pilares:
        if pilar not in CONSULTAS_POR_PILAR:
            continue

        consultas[pilar] = [
            plantilla.format(
                territorio=territorio,
                negocio=negocio
            )
            for plantilla in CONSULTAS_POR_PILAR[pilar]
        ]

    return consultas

def generar_estudio(negocio, territorio):
    """
    Función principal.
    """

    pilares = seleccionar_pilares(negocio)

    consultas = generar_consultas_por_pilar(
        territorio=territorio,
        pilares=pilares,
        negocio=negocio
    )

    return {
        "negocio": negocio,
        "territorio": territorio,
        "pilares": pilares,
        "consultas": consultas
    }

