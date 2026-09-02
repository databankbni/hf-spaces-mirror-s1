"""Sección 5 (común a los 5 usos): frecuencia hidrológica no estacionaria,
integración de fuentes, eventos compuestos y sistemas de alerta temprana.

Esta sección se renderiza igual para captación de agua potable, riego,
hidroeléctrico, caudal ecológico e investigación científica. Aporta el
estado del arte en cambio climático aplicado al análisis hidrológico,
articulado con los sistemas operacionales de alerta temprana SENAMHI /
ECMWF / WMO / Copernicus.

Estructura: 5 subsecciones que combinan teoría (referencias), métodos,
aplicaciones por contexto y herramientas operacionales.
"""

from __future__ import annotations


SECCION_FRECUENCIA_NS = {
    "titulo": "5. Frecuencia hidrológica no estacionaria, eventos "
              "compuestos y sistemas de alerta temprana",
    "introduccion": (
        "El cambio climático rompe la hipótesis clásica de estacionariedad "
        "(Milly et al., 2008, «Stationarity is dead») sobre la que se "
        "construyen los análisis de frecuencia tradicionales. Esta sección "
        "presenta los enfoques contemporáneos para evaluar la frecuencia "
        "de escenarios hidrológicos históricos y futuros bajo condiciones "
        "no estacionarias, integrando observaciones in situ, productos "
        "satelitales, reanálisis y modelos físicos. Aborda los eventos "
        "compuestos (concurrencia espacio-temporal de múltiples peligros) "
        "destacados por el IPCC AR6, y las nuevas capacidades de "
        "predicción subestacional a estacional (S2S) que alimentan los "
        "sistemas operacionales de alerta temprana hidrometeorológica en "
        "contextos urbanos, naturales y agrícolas."
    ),
    # 5.1
    "no_estacionariedad": {
        "titulo": "5.1 Análisis de frecuencia no estacionaria (NSFA)",
        "descripcion": (
            "El análisis de frecuencia no estacionaria reemplaza el "
            "supuesto IID (independiente e idénticamente distribuido) por "
            "modelos cuyos parámetros varían en el tiempo o con "
            "covariables climáticas. Es el marco recomendado por el WMO, "
            "USGS y EU Copernicus para reevaluar períodos de retorno bajo "
            "cambio climático."
        ),
        "referencias_clave": [
            ("Milly, P. C. D., et al. (2008)",
             "«Stationarity is dead: whither water management?», Science, "
             "319 (5863), 573–574. Manifiesto fundacional del paradigma "
             "post-estacionario."),
            ("Salas, J. D. & Obeysekera, J. (2014)",
             "«Revisiting the concepts of return period and risk for "
             "nonstationary hydrologic extreme events», J. Hydrol. Eng., "
             "19(3), 554–568. Define el período de retorno bajo "
             "condiciones no estacionarias (Re, EW, EE)."),
            ("Sivapalan, M. & Samuel, J. M. (2009)",
             "«Transcending limitations of stationarity and the return "
             "period: process-based approach to flood estimation and "
             "risk assessment», Hydrol. Process., 23, 1671–1675."),
            ("Read, L. K. & Vogel, R. M. (2015)",
             "«Reliability, return periods, and risk under "
             "nonstationarity», Water Resour. Res., 51, 6381–6398."),
            ("Cheng, L., et al. (2014)",
             "«Non-stationary extreme value analysis in a changing "
             "climate», Climatic Change, 127, 353–369. Fundamenta el "
             "uso de GEV no estacionaria."),
            ("Rigby, R. A. & Stasinopoulos, D. M. (2005)",
             "«Generalized additive models for location, scale and shape "
             "(GAMLSS)», Appl. Stat., 54, 507–554. Marco estadístico de "
             "referencia para NSFA."),
            ("IPCC AR6 — WG I, Cap. 11 (2021)",
             "«Weather and climate extreme events in a changing "
             "climate». Confirma cambios detectables en la frecuencia "
             "de extremos hidrometeorológicos."),
        ],
        "metodos": [
            ("GEV no estacionaria con covariables temporales",
             "μ(t) = μ₀ + μ₁·t, σ(t) = σ₀·exp(σ₁·t). Parámetros varían "
             "linealmente con el año."),
            ("GEV con covariables climáticas",
             "Parámetros función de índices ENSO (Niño 3.4), NAO, PDO, "
             "AMO o de variables de gran escala (T global, P regional)."),
            ("GAMLSS — Generalized Additive Models for Location, Scale "
             "and Shape",
             "Permite distribuciones flexibles (GEV, Gumbel, LP3, "
             "Weibull) con covariables suavizadas no paramétricas."),
            ("Períodos de retorno re-derivados",
             "Effective Return Period (Re), Expected Waiting Time (EW), "
             "Expected number of Events (EE) según Salas & Obeysekera "
             "(2014)."),
            ("ML-NSFA — Machine Learning para NSFA",
             "Quantile regression neural networks (QRNN), random forest "
             "para regresión de cuantiles, gradient boosting de "
             "distribuciones."),
            ("Inferencia Bayesiana",
             "Cuantifica la incertidumbre de los parámetros tiempo-"
             "variantes con priors informados por proyecciones CMIP6."),
            ("Tests de detección de no estacionariedad",
             "Mann-Kendall, Spearman, Pettitt para tendencias y puntos "
             "de cambio; Cox-Stuart y Bayesian Change Point Detection."),
        ],
    },
    # 5.2
    "integracion": {
        "titulo": "5.2 Integración de datos, observación y modelización",
        "descripcion": (
            "Los análisis modernos combinan series in situ (limitadas en "
            "Bolivia), productos satelitales globales y reanálisis "
            "atmosféricos con modelos físicos y técnicas de Machine "
            "Learning, mediante asimilación de datos y ensembles "
            "multi-fuente. El objetivo es reconstruir series confiables "
            "donde la red de monitoreo es escasa y reducir la "
            "incertidumbre."
        ),
        "fuentes": [
            ("Reanálisis atmosféricos",
             "ERA5 (ECMWF, 0.25°, 1940–presente), MERRA-2 (NASA, 0.5°, "
             "1980–presente), JRA-55 (JMA). Forzamiento meteorológico "
             "histórico continuo."),
            ("Productos satelitales de precipitación",
             "CHIRPS v2.0 (UCSB, 0.05°, 1981–), IMERG GPM (NASA, 0.1°, "
             "2000–), CMORPH, PERSIANN, GSMaP. Cobertura espacial "
             "completa con calibración estacional."),
            ("Datos in-situ",
             "SENAMHI Bolivia (red meteorológica e hidrométrica BHN), "
             "GRDC (Global Runoff Data Centre), INE-ANDA, "
             "universidades (IHH-UMSA, CASA-UMSS)."),
            ("Reanálisis hidrológicos",
             "GLDAS (NASA, balance hídrico global 0.25°), ERA5-Land "
             "(0.1°, variables del suelo), MERRA-Land, GloFAS (sistema "
             "global de pronóstico de inundaciones EU JRC + ECMWF)."),
            ("Modelos hidrológicos físicos",
             "HBV (conceptual, robusto), GR4J / GR6J (parsimonioso), "
             "VIC (Variable Infiltration Capacity, distribuido), mHM "
             "(mesoscale Hydrologic Model), SWAT (semi-distribuido), "
             "WRF-Hydro (totalmente acoplado)."),
            ("Asimilación de datos",
             "Ensemble Kalman Filter (EnKF), 4D-Var, Particle Filter "
             "para fusionar observaciones con estados del modelo. "
             "Aplicado en GloFAS, NOAA NLDAS."),
            ("Machine Learning hidrológico",
             "LSTM (Long Short-Term Memory) para pronóstico (Kratzert "
             "et al., 2018, 2019), Random Forest, XGBoost para regresión "
             "y clasificación. Hybrid ML-physics models (Reichstein et "
             "al., 2019, Nature)."),
        ],
        "referencias_clave": [
            ("Kratzert, F., et al. (2019)",
             "«Towards learning universal, regional, and local "
             "hydrological behaviors via machine learning applied to "
             "large-sample datasets», HESS, 23, 5089–5110."),
            ("Reichstein, M., et al. (2019)",
             "«Deep learning and process understanding for data-driven "
             "Earth system science», Nature, 566, 195–204."),
            ("Beven, K. (2012)",
             "«Rainfall-Runoff Modelling: The Primer», 2nd ed., Wiley. "
             "Marco metodológico para modelización hidrológica con "
             "incertidumbre."),
            ("Clark, M. P., et al. (2015)",
             "«A unified approach for process-based hydrologic "
             "modeling», Water Resour. Res. Define la arquitectura "
             "SUMMA para experimentos multi-modelo."),
            ("WMO Guidelines on Multi-Hazard Impact-Based Forecast and "
             "Warning Services (2015, WMO-1150)",
             "Marco internacional para servicios de pronóstico basados "
             "en impacto."),
        ],
    },
    # 5.3
    "eventos_compuestos": {
        "titulo": "5.3 Eventos compuestos hidrometeorológicos",
        "descripcion": (
            "Los eventos compuestos son aquellos en que dos o más "
            "peligros climáticos o hidrológicos concurren en el espacio "
            "y/o en el tiempo, amplificando el impacto agregado. El IPCC "
            "AR6 (WG I, Cap. 11) los identifica como una de las áreas de "
            "mayor preocupación por su crecimiento detectable bajo "
            "cambio climático. Para Bolivia los más relevantes son las "
            "sequías meteorológicas concurrentes con olas de calor e "
            "incendios (Chiquitania 2019, 2024) y las lluvias intensas "
            "con saturación de suelos."
        ),
        "tipos": [
            ("Preconditioned",
             "Un evento incrementa la vulnerabilidad ante un segundo "
             "(suelo húmedo + lluvia intensa → inundación)."),
            ("Multivariate",
             "Múltiples variables superan umbrales simultáneamente en "
             "el mismo lugar (sequía + ola de calor)."),
            ("Temporally compounding",
             "Sucesión rápida de eventos del mismo tipo agota la "
             "capacidad de recuperación (sequías plurianuales)."),
            ("Spatially compounding",
             "Eventos individuales en regiones diferentes que afectan "
             "un mismo sistema (sequía en una cuenca + inundación en "
             "otra reducen producción nacional)."),
        ],
        "referencias_clave": [
            ("Zscheischler, J., et al. (2018)",
             "«Future climate risk from compound events», Nature Climate "
             "Change, 8, 469–477. Marco taxonómico fundacional."),
            ("Zscheischler, J., et al. (2020)",
             "«A typology of compound weather and climate events», "
             "Nature Reviews Earth & Environment, 1, 333–347."),
            ("IPCC AR6 WG I — Cap. 11 (2021)",
             "Sección 11.8 sobre eventos compuestos. Confirma "
             "atribución y proyección bajo escenarios SSP."),
            ("Ridder, N. N., et al. (2020)",
             "«Global hotspots for the occurrence of compound events», "
             "Nature Communications, 11, 5956."),
            ("Hao, Z., et al. (2018)",
             "«Compound events under global warming: a dependence "
             "perspective», J. Hydrol. Eng., 23, 03118001. Aplicación "
             "de copulas a eventos hidrológicos."),
            ("Bevacqua, E., et al. (2021)",
             "«Guidelines for studying diverse types of compound "
             "weather and climate events», Earth's Future, 9, "
             "e2021EF002340."),
        ],
        "metodos": [
            ("Copulas multivariadas",
             "Modelan la dependencia entre variables (P-T, Q-déficit, "
             "T-humedad) preservando las marginales. Familias "
             "Archimedianas (Clayton, Gumbel, Frank) y elípticas "
             "(Gaussiana, t-Student)."),
            ("Vine copulas",
             "Descomposición jerárquica para dimensionalidad alta. "
             "Recomendado para 4+ variables (Aas et al., 2009)."),
            ("Redes Bayesianas dinámicas",
             "Modelos gráficos probabilísticos para inferencia causal "
             "y propagación de incertidumbre."),
            ("Counterfactual analysis",
             "Compara escenarios con y sin cambio climático para "
             "atribuir el rol del calentamiento en eventos compuestos "
             "específicos."),
            ("Storyline approach",
             "Construye narrativas físicamente consistentes de eventos "
             "extremos compuestos para evaluación de riesgo "
             "(Shepherd et al., 2018, Climatic Change)."),
        ],
    },
    # 5.4
    "alerta_temprana": {
        "titulo": "5.4 Predicción operacional y sistemas de alerta "
                  "temprana (SAT)",
        "descripcion": (
            "Las nuevas capacidades de predicción subestacional a "
            "estacional (S2S, 2–60 días) y las plataformas operacionales "
            "globales permiten anticipar eventos hidrometeorológicos con "
            "ventanas de aviso útiles para la toma de decisiones. El "
            "Marco de Sendai 2015–2030 y la iniciativa CREWS exigen "
            "sistemas de alerta multi-peligro con enfoque centrado en "
            "el usuario."
        ),
        "sistemas_globales": [
            ("WMO HydroSOS — Global Hydrological Status and Outlook "
             "System",
             "Sistema global de la OMM para monitorear y pronosticar "
             "el estado hidrológico mensual a estacional."),
            ("GloFAS — Global Flood Awareness System (EU JRC + ECMWF)",
             "Pronóstico global de inundaciones a 30 días con "
             "probabilidades. Datos abiertos."),
            ("EFAS — European Flood Awareness System",
             "Análogo europeo de GloFAS con resolución mayor."),
            ("EDO — European Drought Observatory (EU JRC)",
             "Indicadores combinados de sequía (SPI, SMA, fAPAR). "
             "Reportes 10-diarios."),
            ("GDO — Global Drought Observatory (EU JRC)",
             "Equivalente global de EDO. Cobertura para Bolivia "
             "operacional."),
            ("ECMWF SEAS5 / S2S",
             "Pronósticos estacionales (7 meses) y subestacionales "
             "(46 días). Ensemble de 51 miembros."),
            ("NOAA CPC — Climate Prediction Center",
             "Pronósticos estacionales (3 meses) globales para T y P."),
            ("WMO State of the Global Climate (anual)",
             "Reporte oficial OMM con balance climático e hidrológico."),
            ("Copernicus C3S Seasonal Forecast",
             "Pronósticos multi-modelo (ECMWF, UK MetOffice, Météo-"
             "France, DWD, CMCC) en plataforma abierta CDS."),
        ],
        "sistemas_regionales": [
            ("CIIFEN — Centro Internacional para Investigación del "
             "Fenómeno El Niño (Guayaquil)",
             "Pronósticos ENSO específicos para la región andina. "
             "Foro Climático Regional Pacífico Sur."),
            ("CRRH SICA — Comité Regional de Recursos Hídricos "
             "(Centroamérica)",
             "Foros climáticos regionales con relevancia para Bolivia "
             "por las teleconexiones."),
            ("CIIFEN — Foros de Aplicaciones de los Pronósticos "
             "Climáticos",
             "Talleres regionales que adaptan los pronósticos S2S a "
             "decisiones agropecuarias y de gestión hídrica."),
        ],
        "sistemas_bolivia": [
            ("SENAMHI — Pronóstico operacional",
             "Boletines diarios, semanales, decadales, mensuales y "
             "estacionales. Avisos meteorológicos y agroclimáticos."),
            ("Defensa Civil + COE — Centro de Operaciones de "
             "Emergencia",
             "Articula la alerta meteorológica con los sistemas de "
             "respuesta departamentales y municipales."),
            ("DGRT — Dirección General de Gestión de Riesgos y "
             "Atención de Desastres",
             "Coordinación interinstitucional para Sistemas de Alerta "
             "Temprana en cuencas priorizadas."),
            ("Programa Mi Riego + GIZ-PROAGUA",
             "Avisos agroclimáticos para regantes en cuencas con "
             "infraestructura del Plan Nacional de Cuencas."),
            ("Sistema de Alerta Temprana del río Beni (SENAMHI + "
             "Defensa Civil)",
             "SAT operacional para inundaciones del Beni con boyas "
             "telemétricas."),
        ],
        "tecnologias": [
            ("WRF — Weather Research and Forecasting Model",
             "Modelo meteorológico regional de alta resolución. "
             "Operacional en SENAMHI y centros de investigación."),
            ("HEC-HMS / HEC-RAS (USACE)",
             "Modelización lluvia-escorrentía y propagación de avenidas "
             "para SAT locales."),
            ("Delft-FEWS (Deltares)",
             "Plataforma open-source para SAT hidrológicos con "
             "asimilación de datos. Usada en GloFAS, RWS Países Bajos."),
            ("DGI — Distributed Hydrological Models forzados con "
             "pronóstico S2S",
             "VIC, mHM, GR6J alimentados con SEAS5 para extender la "
             "ventana de pronóstico a meses."),
        ],
        "referencias_clave": [
            ("UN Sendai Framework for Disaster Risk Reduction (2015–"
             "2030)",
             "Compromiso global para reducir el riesgo de desastres con "
             "SAT multi-peligro."),
            ("WMO — Climate Risk Early Warning Systems (CREWS, 2015)",
             "Iniciativa global para desarrollar capacidades SAT en "
             "países en desarrollo (Bolivia incluida)."),
            ("WMO Guidelines on Multi-hazard Impact-Based Forecast and "
             "Warning Services (2015, WMO-1150 + revisión 2021)",
             "Marco metodológico para servicios basados en impacto, no "
             "solo en magnitud."),
            ("Vitart, F., et al. (2017)",
             "«The Subseasonal to Seasonal (S2S) Prediction Project "
             "Database», BAMS, 98, 163–173."),
            ("Pappenberger, F., et al. (2015)",
             "«The monetary benefit of early flood warnings in "
             "Europe», Environ. Sci. Policy, 51, 278–291. Fundamenta "
             "el retorno económico de SAT."),
        ],
    },
    # 5.5
    "contextos": {
        "titulo": "5.5 Aplicación por contextos: urbano, natural y "
                  "agrícola",
        "descripcion": (
            "Cada contexto exige enfoques de modelización, monitoreo y "
            "respuesta diferenciados. El informe articula las cinco "
            "subsecciones anteriores (NSFA, integración, eventos "
            "compuestos, SAT) con las particularidades del entorno "
            "donde se aplica el análisis."
        ),
        "urbano": {
            "descripcion": (
                "Cuencas urbanas con alta impermeabilización, "
                "respuesta hidrológica rápida y vulnerabilidad de "
                "infraestructura crítica. Tiempos de concentración "
                "cortos (15–90 min) y necesidad de pronóstico horario."
            ),
            "metodos": [
                "SWMM (Storm Water Management Model, EPA) — drenaje "
                "pluvial.",
                "MIKE Urban (DHI) — modelización integral urbana.",
                "Hidrogramas de diseño con IDF urbanas + Huff/Chicago.",
                "Pluviometría densa + radar meteorológico cuando hay.",
                "Mapas de inundación urbana 2D (HEC-RAS, MIKE FLOOD, "
                "ANUGA).",
            ],
            "casos_bolivia": [
                "La Paz — río Choqueyapu (riesgo de mazamorras).",
                "Cochabamba — Tunari + río Rocha (drenaje del valle "
                "central).",
                "Santa Cruz — anegamientos del 1er, 2do y 3er anillo.",
                "Sucre y Tarija — torrenteras urbanas.",
            ],
        },
        "natural": {
            "descripcion": (
                "Ecosistemas, biodiversidad acuática, humedales Ramsar "
                "y áreas protegidas. Foco en preservación del régimen "
                "natural, caudal ecológico y servicios ecosistémicos. "
                "Tiempos de respuesta lentos y variabilidad estacional "
                "alta."
            ),
            "metodos": [
                "Modelos hidrológicos distribuidos (mHM, VIC, WRF-Hydro).",
                "Modelos ecohidrológicos (SWIM, EFH, HEC-EFM).",
                "IFIM / PHABSIM — hábitat-caudal para fauna acuática.",
                "Índices ecológicos: IHA (Indicators of Hydrologic "
                "Alteration), DHRAM.",
                "Caudal ambiental holístico (BBM, DRIFT) — ver Sección 4.",
            ],
            "casos_bolivia": [
                "Llanos de Moxos (Beni) — humedal Ramsar.",
                "Pantanal (Santa Cruz) — humedal Ramsar transfronterizo.",
                "Pampas del Yacuma (Beni) — humedal Ramsar.",
                "Bañados del Izozog (Santa Cruz) — humedal Ramsar.",
                "Cordillera Real y Tunari — glaciares en retroceso.",
                "Reservas TIPNIS, Madidi, Pilón Lajas, Apolobamba.",
            ],
        },
        "agricola": {
            "descripcion": (
                "Cuencas con uso predominante agropecuario; foco en "
                "demanda hídrica del cultivo, seguridad alimentaria y "
                "resiliencia a sequías. Pronóstico estacional (S2S) "
                "para decisiones de siembra y manejo."
            ),
            "metodos": [
                "AquaCrop (FAO) — modelo de productividad agua-cultivo.",
                "DSSAT (Decision Support System for Agrotechnology "
                "Transfer).",
                "APSIM (Agricultural Production Systems Simulator).",
                "WaPOR (FAO) — productividad satelital del agua.",
                "Zonificación AEZ-FAO (Agro-Ecological Zones).",
                "Índices de sequía agrícola: SMA (soil moisture "
                "anomaly), VHI (vegetation health), VCI (vegetation "
                "condition), CDI (combined drought).",
                "Pronóstico estacional acoplado a modelo de cultivos.",
            ],
            "casos_bolivia": [
                "Valles interandinos (Cochabamba) — riego del valle "
                "alto, central y bajo.",
                "Chaco boliviano (Chuquisaca, Tarija, Santa Cruz) — "
                "agricultura de secano vulnerable a sequía.",
                "Altiplano norte y central — quinua, papa nativa "
                "(adaptación a sequía y heladas).",
                "Zona expansión Santa Cruz — soja, maíz, sorgo.",
                "Amazonía boliviana — agroforestería, cacao, café.",
            ],
        },
    },
    # Referencias agrupadas para el final
    "referencias_marco": [
        ("WMO — Manual on the Global Data-processing and Forecasting "
         "System (WMO-485)",
         "Estándares operacionales para los sistemas nacionales."),
        ("Copernicus Climate Change Service (C3S) Catalogue",
         "Datasets abiertos para reanálisis, satélite, proyecciones y "
         "pronóstico estacional."),
        ("FAO — Water Productivity Open-access portal (WaPOR)",
         "Productividad agrícola del agua."),
        ("CEH/UKCEH — Hydrological Outlook UK",
         "Modelo operacional UK que combina S2S + hidrología."),
    ],
}
