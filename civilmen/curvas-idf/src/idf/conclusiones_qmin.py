"""Generador de conclusiones y recomendaciones para el informe de caudales mínimos.

Las conclusiones se arman dinámicamente combinando los datos del análisis
(coordenadas, estaciones cercanas, marco normativo del uso seleccionado)
con bloques fijos del estado del arte (Sección 5). Las recomendaciones
combinan recomendaciones generales con específicas por uso.
"""

from __future__ import annotations


def _calidad_red(met_cerc: list, hidro_cerc: list) -> str:
    """Calificación de la red de estaciones (alta / media / baja)."""
    activas = sum(1 for e, _ in hidro_cerc if getattr(e, "estado", "") == "activa")
    cercana_50 = sum(1 for e, d in hidro_cerc if d < 50.0 and
                      getattr(e, "estado", "") == "activa")
    if cercana_50 >= 1 and activas >= 3:
        return "alta"
    if activas >= 2:
        return "media"
    return "baja"


def _hidro_referencia(hidro_cerc: list) -> tuple[object | None, float | None]:
    """Estación hidrométrica activa de referencia más cercana (si existe)."""
    activas = [(e, d) for e, d in hidro_cerc
               if getattr(e, "estado", "") == "activa"]
    if activas:
        return activas[0]
    return None, None


def _met_referencia(met_cerc: list) -> tuple[object | None, float | None]:
    """Estación meteorológica de referencia más cercana."""
    return (met_cerc[0] if met_cerc else (None, None))


# Recomendaciones específicas por uso (clave del MARCOS).
RECOMENDACIONES_USO = {
    "captacion_agua": [
        ("Adoptar el Q90 de la FDC como umbral mínimo de captación "
         "para garantizar continuidad del servicio el 90 % del tiempo, "
         "y verificar que la captación no supere el 20 % del Q mín, "
         "5 años (Ley 1333, Art. 48°)."),
        ("Elaborar el Plan de Seguridad del Agua (Water Safety Plan, "
         "WHO 2023) cubriendo la cadena fuente-red-consumidor; es "
         "obligatorio para sistemas servidos a más de 5 000 "
         "habitantes."),
        ("Clasificar la fuente según NB 512 (Clase A / B / C / D) "
         "para dimensionar el tren de tratamiento. Para fuentes Clase "
         "B y C se debe contemplar coagulación-floculación, "
         "sedimentación, filtración y desinfección."),
        ("Proyectar la demanda con horizonte mínimo de 20 años "
         "siguiendo NB 688, con dotación entre 80 y 250 L/hab·día "
         "según altitud y zona climática. Verificar margen de "
         "seguridad Q90 / Q_demanda ≥ 1.20."),
        ("Tramitar la concesión ante la AAPS y, si la captación supera "
         "el 20 % del Q mín 5 años, presentar Estudio de Evaluación "
         "de Impacto Ambiental (EEIA) ante la Prefectura."),
    ],
    "riego": [
        ("Adoptar Q75 (o Q80 para riego de subsistencia) como umbral "
         "de oferta segura, conforme a FAO IDP 56 y la práctica "
         "regional andina."),
        ("Calcular la demanda hídrica con balance Penman-Monteith × Kc "
         "(FAO IDP 56) descontando la precipitación efectiva (USDA-SCS) "
         "para cada mes y cultivo de la cédula."),
        ("Verificar la calidad del agua según FAO Water Quality for "
         "Agriculture (2023) y Risks and Risk Mitigation (2023): "
         "CE, SAR, pH, alcalinidad, toxicidad iónica y metales "
         "pesados (As, Cd, Cr, Pb, Hg)."),
        ("Tramitar el Registro (comunidad indígena/campesina con uso "
         "tradicional) o la Autorización (riego tecnificado) ante el "
         "SENARI/SEDERI, conforme a Ley 2878 y DS 28817."),
        ("Si la cuenca tiene presa derivadora, aplicar criterios USBR / "
         "SPANCOLD para obras menores y boletines ICOLD para presas "
         "mayores a 15 m de altura o vaso > 3 hm³."),
    ],
    "hidroelectrico": [
        ("Adoptar Q95 como caudal firme (energía firme) según práctica "
         "regional (Brasil ANEEL 396/2010, Chile DGA, Perú DS 009-93-EM) "
         "y verificar los límites Bolivianos del 20 % del Q mín 5 años "
         "(Ley 1333 Art. 48°) y 33 % del Q río (Art. 44°)."),
        ("Dimensionar el caudal de diseño entre Q40 y Q60 para "
         "optimizar la energía total generada, descontando el caudal "
         "ecológico y las pérdidas."),
        ("Elaborar el EEIA categoría 1 obligatoriamente (Ley 2066 + "
         "DS 24176) y articular el proyecto con las salvaguardas "
         "del Banco Mundial (ESS6), CAF, BID y los estándares IEC "
         "61116 / 60041 para tests de aceptación."),
        ("Para presas mayores a 15 m de altura o vaso > 3 hm³ aplicar "
         "íntegramente los boletines técnicos ICOLD y las "
         "recomendaciones de la IHA Hydropower Sustainability "
         "Standard (2021)."),
        ("Verificar el caudal ecológico aguas abajo en todo escenario; "
         "es no negociable bajo la Ley 071 (Derechos de la Madre "
         "Tierra)."),
    ],
    "ecologico": [
        ("Reportar al menos cuatro métodos de caudal ecológico "
         "complementarios (10 % Q anual, Q90, Q85, 33–50 % Q medio "
         "bajo de la UE) para evidenciar la dispersión metodológica."),
        ("Verificar el cumplimiento simultáneo de la triple "
         "condición operativa: Q demanda ≤ Q captación disponible, "
         "Q residual ≥ Q eco, y calidad de agua compatible con el "
         "uso (FAO 2023)."),
        ("Para proyectos hidroeléctricos > 50 MW o presas con vaso "
         "> 10 hm³ aplicar análisis holístico (BBM o DRIFT) según "
         "exigen las salvaguardas del Banco Mundial y la CAF."),
        ("Si la cuenca afecta humedales Ramsar bolivianos (Llanos de "
         "Moxos, Pantanal, Pampas del Yacuma, Bañados del Izozog) "
         "preservar los caudales de pulso que reproduzcan el régimen "
         "estacional natural."),
        ("Definir el plan de monitoreo mensual al SENARI/SEDERI/AAPS "
         "con umbrales de alerta basados en los percentiles "
         "históricos P10–P90 y acciones correctivas ante "
         "incumplimiento."),
    ],
    "investigacion_cientifica": [
        ("Si el estudio involucra biodiversidad acuática, obtener "
         "previamente el reconocimiento como ICA y la aprobación de "
         "la AACN (Reglamento RM 026/2009; vigencia 5 años, "
         "intransferible, plazo 15 días hábiles)."),
        ("Si el estudio es universitario, articularlo con el Banco de "
         "Proyectos y el Plan de Investigación Anual de la universidad "
         "ejecutora (UCB, UPDS, UAGRM-ICU u otra), respetando el "
         "reglamento interno."),
        ("Aplicar análisis de frecuencia no estacionaria (GAMLSS, "
         "GEV con covariables temporales o climáticas), reportando "
         "siempre la incertidumbre del ensemble (no solo la mediana)."),
        ("Integrar fuentes complementarias (ERA5 / CHIRPS / GRDC / "
         "SENAMHI / NEX-GDDP / CORDEX-SAM) y comparar con estudios "
         "análogos en cuencas andinas (Mantaro, Rímac, Paute, "
         "Aconcagua, Maipo) y europeas (Pirineos, Alpes)."),
        ("Publicar bajo licencia abierta conforme a la UNESCO "
         "Recomendación de Ciencia Abierta (2021): publicaciones, "
         "datos, protocolos, código y software en repositorios FAIR "
         "no comerciales."),
    ],
}


RECOMENDACIONES_GENERALES = [
    ("Pasar del análisis estacionario al no estacionario (GAMLSS, GEV "
     "no estacionaria) conforme al cambio de paradigma postulado por "
     "Milly et al. (2008) y avalado por el IPCC AR6."),
    ("Integrar el análisis con los sistemas de alerta temprana "
     "operacionales en Bolivia (SENAMHI, Defensa Civil + COE, DGRT) "
     "y con plataformas globales (GloFAS, HydroSOS, ECMWF S2S, "
     "Copernicus C3S, EU JRC EDO)."),
    ("Evaluar eventos compuestos (sequía + ola de calor + incendios, "
     "lluvia extrema + suelo saturado) usando copulas multivariadas, "
     "redes Bayesianas o el storyline approach (Shepherd et al. 2018), "
     "siguiendo IPCC AR6 Cap. 11.8."),
    ("Actualizar el catálogo de estaciones hidrométricas con datos "
     "GRDC, BHN-SENAMHI y aforos institucionales (ENDE, ABT, SEARPI) "
     "antes de iniciar el análisis. La densidad de la red condiciona "
     "directamente la confiabilidad del resultado."),
    ("Documentar el proceso con metadatos FAIR (Findable, Accessible, "
     "Interoperable, Reusable) para alimentar futuros estudios "
     "regionales (CRRH SICA, CIIFEN) y el sistema de alerta temprana "
     "nacional."),
]


def conclusiones_dinamicas(uso: str, marco: dict, lat: float, lon: float,
                            met_cerc: list, hidro_cerc: list,
                            n_met_total: int, n_hidro_total: int,
                            estado_hidro: dict) -> list[tuple[str, str]]:
    """Construye una lista de (título, párrafo) con conclusiones para el HTML.

    Cada par representa un bloque temático con su título y contenido.
    """
    nombre_uso = {
        "captacion_agua": "captación de agua potable",
        "riego": "captación para riego",
        "hidroelectrico": "aprovechamiento hidroeléctrico",
        "ecologico": "caudal ecológico mínimo",
        "investigacion_cientifica": "investigación científica",
    }.get(uso, uso)

    met_ref, dist_met = _met_referencia(met_cerc)
    hidro_ref, dist_hidro = _hidro_referencia(hidro_cerc)
    calidad = _calidad_red(met_cerc, hidro_cerc)
    activas = estado_hidro.get("activa", 0)
    pasivas = (estado_hidro.get("pasiva", 0) +
               estado_hidro.get("intermitente", 0))

    conclusiones = []

    # 6.1 — Caracterización y ubicación
    conclusiones.append((
        "6.1 Sobre la caracterización del punto",
        f"El punto de análisis se ubica en latitud {lat:.6f}° y longitud "
        f"{lon:.6f}°, dentro del territorio nacional boliviano. La "
        "delineación de la cuenca de aporte se realizará por watershed "
        "D8 con MERIT Hydro a 90 m de resolución, integrando los 36 "
        "parámetros morfométricos del catálogo ArcGeek (geometría, "
        "relieve, forma, red de drenaje, hipsometría) para sustentar "
        f"el análisis del uso seleccionado ({nombre_uso}). La "
        "caracterización morfométrica condiciona la respuesta "
        "hidrológica y, con ella, los caudales mínimos disponibles."
    ))

    # 6.2 — Información local disponible
    if met_ref and hidro_ref:
        param_str = (
            f"La estación meteorológica SENAMHI más cercana es "
            f"<b>{met_ref.nombre}</b> ({dist_met:.1f} km del sitio), y la "
            f"estación hidrométrica activa más próxima es "
            f"<b>{hidro_ref.nombre}</b> en el "
            f"<b>{hidro_ref.cuerpo_agua}</b> ({dist_hidro:.1f} km, "
            f"fuente {hidro_ref.fuente}, período "
            f"{hidro_ref.anio_inicio}–{hidro_ref.anio_fin}). "
        )
    elif met_ref:
        param_str = (
            f"La estación meteorológica más cercana es "
            f"<b>{met_ref.nombre}</b> ({dist_met:.1f} km), pero no hay "
            "estaciones hidrométricas activas en proximidad razonable. "
        )
    else:
        param_str = "No se identificaron estaciones en proximidad inmediata. "
    if calidad == "alta":
        veredicto = (
            "La red disponible se califica como <b>alta confiabilidad</b>: "
            "se cuenta con datos directos para apuntalar el análisis."
        )
    elif calidad == "media":
        veredicto = (
            "La red disponible se califica como <b>confiabilidad media</b>: "
            "el análisis debe complementar los aforos con balance modelado "
            "CHIRPS·ERA5 sobre la cuenca delineada."
        )
    else:
        veredicto = (
            "La red disponible se califica como <b>baja confiabilidad</b>: "
            "el análisis dependerá del balance hidrológico modelado "
            "(CHIRPS + ERA5-Land) y de la transferencia regional de "
            "estaciones análogas, con incertidumbre que debe reportarse "
            "explícitamente."
        )
    conclusiones.append((
        "6.2 Sobre la información local disponible",
        f"El catálogo nacional incluye {n_met_total} estaciones "
        f"meteorológicas SENAMHI y {n_hidro_total} estaciones "
        f"hidrométricas (SENAMHI-BHN + GRDC + SEARPI + ABT), de las "
        f"cuales {activas} están activas y {pasivas} pasivas o "
        f"intermitentes. {param_str}{veredicto}"
    ))

    # 6.3 — Modelos de cambio climático
    conclusiones.append((
        "6.3 Sobre los modelos de cambio climático disponibles",
        "El punto cuenta con cobertura espacial completa de los "
        "principales conjuntos de proyecciones climáticas: NASA "
        "NEX-GDDP-CMIP6 (25 km, 35 modelos GCM, 4 escenarios SSP), "
        "CORDEX-SAM (RCA4, REMO a 50 km con downscaling dinámico "
        "calibrado para los Andes), el Atlas de Cambio Climático para "
        "Bolivia del MMAyA (2010) y CHIRP-GEFS proyectado. La "
        "confiabilidad regional de los modelos es alta a media; la "
        "incertidumbre se cuantificará mediante el rango intercuartil "
        "(IQR) del ensemble multi-modelo conforme a las recomendaciones "
        "del IPCC AR6 y la WMO."
    ))

    # 6.4 — Marco normativo del uso
    n_nac = len(marco.get("marco_nacional", []))
    n_int = len(marco.get("marco_internacional", []))
    n_met = len(marco.get("metodos", []))
    n_par = len(marco.get("parametros_clave", []))
    flujo = marco.get("flujo_tecnico", [])
    n_flujo = len(flujo)
    conclusiones.append((
        f"6.4 Sobre el marco normativo del uso «{nombre_uso}»",
        f"El análisis se articula sobre {n_nac} referencias normativas "
        f"nacionales bolivianas y {n_int} referencias internacionales "
        f"aplicables al uso seleccionado, con {n_met} métodos de "
        f"cálculo y {n_par} parámetros clave a reportar en el informe " +
        (f"final. El flujo técnico propuesto comprende {n_flujo} pasos "
         "operativos desde la caracterización hasta la implementación y "
         "monitoreo continuo. "
         if n_flujo else "final. ") +
        f"{marco.get('consideraciones', '')}"
    ))

    # 6.5 — Frecuencia no estacionaria y SAT
    conclusiones.append((
        "6.5 Sobre el análisis no estacionario y los sistemas de alerta",
        "El informe adopta el paradigma post-estacionario establecido "
        "por Milly et al. (2008) y avalado por el IPCC AR6: el análisis "
        "de frecuencia se reformulará con GAMLSS o GEV no estacionaria "
        "(covariables temporales y climáticas), los eventos compuestos "
        "se evaluarán con copulas multivariadas y storyline approach "
        "(Zscheischler et al., 2018, 2020), y los resultados se "
        "articularán con los sistemas de alerta temprana operacionales "
        "(SENAMHI, GloFAS, ECMWF S2S, Copernicus C3S) en sus tres "
        "contextos de aplicación (urbano, natural y agrícola)."
    ))

    return conclusiones


def recomendaciones(uso: str) -> dict[str, list[str]]:
    """Devuelve recomendaciones específicas del uso + generales."""
    return {
        "especificas": RECOMENDACIONES_USO.get(uso, []),
        "generales": RECOMENDACIONES_GENERALES,
    }
