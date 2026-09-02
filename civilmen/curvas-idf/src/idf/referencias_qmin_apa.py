"""Referencias bibliográficas del informe de caudales mínimos en formato APA 7.

Consolida todas las fuentes citadas en las Secciones 1-5, agrupadas por
categoría temática para facilitar la lectura. La numeración es secuencial
dentro de cada categoría, y el lector puede usarla para la trazabilidad
cuando el texto cita un número entre corchetes.

Formato APA 7.ª edición: Apellido, I. I. (año). Título en formato normal.
Fuente en cursiva, volumen(número), páginas. https://doi.org/...
"""

from __future__ import annotations


REFERENCIAS_APA = [
    # ──────────── A. Marco general nacional Bolivia ────────────
    ("A. Marco normativo y técnico — Bolivia", [
        "Asamblea Legislativa Plurinacional. (1992). Ley N.º 1333 — "
        "Ley del Medio Ambiente. Estado Plurinacional de Bolivia.",
        "Asamblea Legislativa Plurinacional. (1999). Ley N.º 2029 — "
        "Ley de Servicios de Agua Potable y Alcantarillado Sanitario. "
        "Estado Plurinacional de Bolivia.",
        "Asamblea Legislativa Plurinacional. (2000). Ley N.º 2066 — "
        "Ley modificatoria a la Ley N.º 2029. Estado Plurinacional de "
        "Bolivia.",
        "Asamblea Legislativa Plurinacional. (2004). Ley N.º 2878 — "
        "Ley de Promoción y Apoyo al Sector Riego. Estado Plurinacional "
        "de Bolivia.",
        "Asamblea Legislativa Plurinacional. (2010). Ley N.º 071 — Ley "
        "de Derechos de la Madre Tierra. Estado Plurinacional de "
        "Bolivia.",
        "Asamblea Legislativa Plurinacional. (2011). Ley N.º 144 — Ley "
        "de la Revolución Productiva Comunitaria Agropecuaria. Estado "
        "Plurinacional de Bolivia.",
        "Asamblea Legislativa Plurinacional. (2012). Ley N.º 300 — Ley "
        "Marco de la Madre Tierra y Desarrollo Integral para Vivir "
        "Bien. Estado Plurinacional de Bolivia.",
        "Ministerio de Desarrollo Sostenible y Medio Ambiente. (1995). "
        "Decreto Supremo N.º 24176 — Reglamento de Gestión Ambiental "
        "del Recurso Hídrico. Bolivia.",
        "Ministerio de Medio Ambiente y Agua. (2006). Decreto Supremo "
        "N.º 28817 — Reglamento de la Ley de Promoción y Apoyo al "
        "Sector Riego. Bolivia.",
        "Ministerio de Medio Ambiente y Agua. (2007). Norma Boliviana "
        "NB 688 — Instalaciones sanitarias: alcantarillado sanitario, "
        "pluvial y tratamiento de aguas residuales. IBNORCA.",
        "Ministerio de Medio Ambiente y Agua. (2007). Norma Boliviana "
        "NB 689 — Diseño de sistemas de agua potable. IBNORCA.",
        "Ministerio de Medio Ambiente y Agua. (2010). Norma Boliviana "
        "NB 512 — Agua potable: requisitos de calidad. IBNORCA.",
        "Ministerio de Medio Ambiente y Agua. (2017). Plan Plurinacional "
        "de Cambio Climático para Vivir Bien (2017–2030). MMAyA, "
        "Bolivia.",
        "Ministerio de Medio Ambiente y Agua. (s. f.). Plan Nacional "
        "de Desarrollo de Riego «Para Vivir Bien». Viceministerio de "
        "Recursos Hídricos y Riego, Bolivia.",
        "Ministerio de Obras Públicas, Servicios y Vivienda; "
        "Administradora Boliviana de Carreteras. (s. f.). Manual de "
        "hidrología y drenaje. MOPSV-ABC, Bolivia.",
        "PRONAR — Programa Nacional de Riego. (2005). Norma Boliviana "
        "de Riego. Cooperación GTZ-KfW + Gobierno de Bolivia.",
        "Universidad Autónoma Gabriel René Moreno. (2025). Reglamento "
        "General de Investigación ICU (Res. ICU 019/2025) y Líneas de "
        "Investigación (Res. Vicerrectoral 052/2025). UAGRM.",
        "Universidad Católica Boliviana San Pablo. (s. f.). Reglamento "
        "de Investigación de la UCB. Tarija, Bolivia.",
        "Universidad Privada Domingo Savio. (2025). Reglamento de "
        "Investigación de la UPDS. Santa Cruz, Bolivia.",
        "Viceministerio de Recursos Hídricos y Riego. (2009). "
        "Reglamento de Investigación Científica en Diversidad "
        "Biológica (RM 026/2009). MMAyA, Bolivia.",
    ]),
    # ──────────── B. Estaciones, datos satelitales y reanálisis ────────────
    ("B. Datos hidrometeorológicos y reanálisis", [
        "Funk, C., Peterson, P., Landsfeld, M., Pedreros, D., Verdin, "
        "J., Shukla, S., Husak, G., Rowland, J., Harrison, L., Hoell, "
        "A., & Michaelsen, J. (2015). The climate hazards infrared "
        "precipitation with stations — a new environmental record for "
        "monitoring extremes. Scientific Data, 2, 150066. "
        "https://doi.org/10.1038/sdata.2015.66",
        "Hersbach, H., Bell, B., Berrisford, P., Hirahara, S., Horányi, "
        "A., Muñoz-Sabater, J., Nicolas, J., Peubey, C., Radu, R., "
        "Schepers, D., Simmons, A., Soci, C., Abdalla, S., Abellan, X., "
        "Balsamo, G., Bechtold, P., Biavati, G., Bidlot, J., Bonavita, "
        "M., … Thépaut, J.-N. (2020). The ERA5 global reanalysis. "
        "Quarterly Journal of the Royal Meteorological Society, "
        "146(730), 1999–2049. https://doi.org/10.1002/qj.3803",
        "Huffman, G. J., Bolvin, D. T., Braithwaite, D., Hsu, K., "
        "Joyce, R., Kidd, C., Nelkin, E. J., Sorooshian, S., Tan, J., "
        "& Xie, P. (2020). Integrated Multi-satellite Retrievals for "
        "GPM (IMERG). NASA Goddard Space Flight Center.",
        "Lehner, B., Verdin, K., & Jarvis, A. (2008). New global "
        "hydrography derived from spaceborne elevation data. Eos, "
        "Transactions American Geophysical Union, 89(10), 93–94. "
        "https://doi.org/10.1029/2008EO100001",
        "Yamazaki, D., Ikeshima, D., Sosa, J., Bates, P. D., Allen, G. "
        "H., & Pavelsky, T. M. (2019). MERIT Hydro: A high-resolution "
        "global hydrography map based on latest topography dataset. "
        "Water Resources Research, 55(6), 5053–5073. "
        "https://doi.org/10.1029/2019WR024873",
        "NASA Langley Research Center. (s. f.). NASA POWER — Prediction "
        "of Worldwide Energy Resources. https://power.larc.nasa.gov",
        "Global Runoff Data Centre. (s. f.). Global Runoff Database. "
        "Bundesanstalt für Gewässerkunde (BfG). https://www.bafg.de/GRDC",
        "Project MapBiomas. (2024). MapBiomas Bolivia — Land Use and "
        "Land Cover Mapping, Collection 1 [Dataset]. "
        "https://bolivia.mapbiomas.org",
        "Servicio Nacional de Meteorología e Hidrología de Bolivia. "
        "(s. f.). Boletines Hidrológicos Nacionales (BHN). SENAMHI, "
        "Bolivia. https://senamhi.gob.bo",
        "Zanaga, D., Van De Kerchove, R., Daems, D., De Keersmaecker, "
        "W., Brockmann, C., Kirches, G., Wevers, J., Cartus, O., "
        "Santoro, M., Fritz, S., Lesiv, M., Herold, M., Tsendbazar, "
        "N.-E., Xu, P., Ramoino, F., & Arino, O. (2022). ESA WorldCover "
        "10 m 2021 v200 [Dataset]. Zenodo. "
        "https://doi.org/10.5281/zenodo.7254221",
    ]),
    # ──────────── C. Modelos climáticos ────────────
    ("C. Modelos de cambio climático y escenarios", [
        "Intergovernmental Panel on Climate Change. (2021). Climate "
        "Change 2021: The Physical Science Basis. Contribution of "
        "Working Group I to the Sixth Assessment Report. Cambridge "
        "University Press. https://doi.org/10.1017/9781009157896",
        "Intergovernmental Panel on Climate Change. (2022). Climate "
        "Change 2022: Impacts, Adaptation and Vulnerability. "
        "Contribution of Working Group II to the Sixth Assessment "
        "Report. Cambridge University Press.",
        "Eyring, V., Bony, S., Meehl, G. A., Senior, C. A., Stevens, "
        "B., Stouffer, R. J., & Taylor, K. E. (2016). Overview of the "
        "Coupled Model Intercomparison Project Phase 6 (CMIP6) "
        "experimental design and organization. Geoscientific Model "
        "Development, 9, 1937–1958. "
        "https://doi.org/10.5194/gmd-9-1937-2016",
        "Thrasher, B., Wang, W., Michaelis, A., Melton, F., Lee, T., & "
        "Nemani, R. (2022). NASA Global Daily Downscaled Projections, "
        "CMIP6. Scientific Data, 9, 262. "
        "https://doi.org/10.1038/s41597-022-01393-4",
        "Giorgi, F., & Gutowski, W. J. (2015). Regional dynamical "
        "downscaling and the CORDEX initiative. Annual Review of "
        "Environment and Resources, 40, 467–490. "
        "https://doi.org/10.1146/annurev-environ-102014-021217",
        "Ministerio de Medio Ambiente y Agua. (2010). Atlas de Cambio "
        "Climático para Bolivia. MMAyA, Bolivia.",
    ]),
    # ──────────── D. Análisis de frecuencia y no estacionariedad ────────────
    ("D. Análisis de frecuencia y no estacionariedad", [
        "Cheng, L., AghaKouchak, A., Gilleland, E., & Katz, R. W. "
        "(2014). Non-stationary extreme value analysis in a changing "
        "climate. Climatic Change, 127, 353–369. "
        "https://doi.org/10.1007/s10584-014-1254-5",
        "Coles, S. (2001). An introduction to statistical modeling of "
        "extreme values. Springer Series in Statistics. Springer.",
        "Milly, P. C. D., Betancourt, J., Falkenmark, M., Hirsch, R. M., "
        "Kundzewicz, Z. W., Lettenmaier, D. P., & Stouffer, R. J. "
        "(2008). Stationarity is dead: whither water management? "
        "Science, 319(5863), 573–574. "
        "https://doi.org/10.1126/science.1151915",
        "Read, L. K., & Vogel, R. M. (2015). Reliability, return "
        "periods, and risk under nonstationarity. Water Resources "
        "Research, 51(8), 6381–6398. "
        "https://doi.org/10.1002/2015WR017089",
        "Rigby, R. A., & Stasinopoulos, D. M. (2005). Generalized "
        "additive models for location, scale and shape. Journal of the "
        "Royal Statistical Society: Series C (Applied Statistics), 54, "
        "507–554.",
        "Salas, J. D., & Obeysekera, J. (2014). Revisiting the "
        "concepts of return period and risk for nonstationary "
        "hydrologic extreme events. Journal of Hydrologic Engineering, "
        "19(3), 554–568. "
        "https://doi.org/10.1061/(ASCE)HE.1943-5584.0000820",
        "Sivapalan, M., & Samuel, J. M. (2009). Transcending "
        "limitations of stationarity and the return period: process-"
        "based approach to flood estimation and risk assessment. "
        "Hydrological Processes, 23(11), 1671–1675.",
        "U.S. Geological Survey. (2018). Bulletin 17C — Guidelines for "
        "determining flood flow frequency (Techniques and Methods, "
        "Book 4, Chapter B5). U.S. Department of the Interior. "
        "https://doi.org/10.3133/tm4B5",
        "Vicente-Serrano, S. M., Beguería, S., & López-Moreno, J. I. "
        "(2010). A multiscalar drought index sensitive to global "
        "warming: the standardized precipitation evapotranspiration "
        "index. Journal of Climate, 23(7), 1696–1718.",
        "McKee, T. B., Doesken, N. J., & Kleist, J. (1993). The "
        "relationship of drought frequency and duration to time "
        "scales. Proceedings of the 8th Conference on Applied "
        "Climatology, 17(22), 179–183.",
    ]),
    # ──────────── E. Eventos compuestos ────────────
    ("E. Eventos compuestos hidrometeorológicos", [
        "Aas, K., Czado, C., Frigessi, A., & Bakken, H. (2009). "
        "Pair-copula constructions of multiple dependence. Insurance: "
        "Mathematics and Economics, 44(2), 182–198.",
        "Bevacqua, E., De Michele, C., Manning, C., Couasnon, A., "
        "Ribeiro, A. F. S., Ramos, A. M., … Zscheischler, J. (2021). "
        "Guidelines for studying diverse types of compound weather and "
        "climate events. Earth's Future, 9, e2021EF002340. "
        "https://doi.org/10.1029/2021EF002340",
        "Hao, Z., Singh, V. P., & Hao, F. (2018). Compound extremes in "
        "hydroclimatology: a review. Water, 10(6), 718.",
        "Ridder, N. N., Pitman, A. J., Westra, S., Ukkola, A., Hong, "
        "X. D., Bador, M., … Zscheischler, J. (2020). Global hotspots "
        "for the occurrence of compound events. Nature Communications, "
        "11, 5956. https://doi.org/10.1038/s41467-020-19639-3",
        "Shepherd, T. G., Boyd, E., Calel, R. A., Chapman, S. C., "
        "Dessai, S., Dima-West, I. M., … Zenghelis, D. A. (2018). "
        "Storylines: an alternative approach to representing "
        "uncertainty in physical aspects of climate change. Climatic "
        "Change, 151(3-4), 555–571.",
        "Zscheischler, J., Westra, S., van den Hurk, B. J. J. M., "
        "Seneviratne, S. I., Ward, P. J., Pitman, A., … Zhang, X. "
        "(2018). Future climate risk from compound events. Nature "
        "Climate Change, 8, 469–477. "
        "https://doi.org/10.1038/s41558-018-0156-3",
        "Zscheischler, J., Martius, O., Westra, S., Bevacqua, E., "
        "Raymond, C., Horton, R. M., … Vignotto, E. (2020). A typology "
        "of compound weather and climate events. Nature Reviews Earth "
        "& Environment, 1, 333–347. "
        "https://doi.org/10.1038/s43017-020-0060-z",
    ]),
    # ──────────── F. Modelización hidrológica ────────────
    ("F. Modelización hidrológica y aprendizaje automático", [
        "Beven, K. (2012). Rainfall-runoff modelling: The primer "
        "(2nd ed.). Wiley.",
        "Clark, M. P., Nijssen, B., Lundquist, J. D., Kavetski, D., "
        "Rupp, D. E., Woods, R. A., … Marks, D. G. (2015). A unified "
        "approach for process-based hydrologic modeling. Water "
        "Resources Research, 51(4), 2498–2514.",
        "Kratzert, F., Klotz, D., Brenner, C., Schulz, K., & Herrnegger, "
        "M. (2018). Rainfall-runoff modelling using Long Short-Term "
        "Memory (LSTM) networks. Hydrology and Earth System Sciences, "
        "22, 6005–6022.",
        "Kratzert, F., Klotz, D., Shalev, G., Klambauer, G., Hochreiter, "
        "S., & Nearing, G. (2019). Towards learning universal, "
        "regional, and local hydrological behaviors via machine "
        "learning applied to large-sample datasets. Hydrology and "
        "Earth System Sciences, 23, 5089–5110.",
        "Liang, X., Lettenmaier, D. P., Wood, E. F., & Burges, S. J. "
        "(1994). A simple hydrologically based model of land surface "
        "water and energy fluxes for general circulation models. "
        "Journal of Geophysical Research, 99(D7), 14415–14428.",
        "Reichstein, M., Camps-Valls, G., Stevens, B., Jung, M., "
        "Denzler, J., Carvalhais, N., & Prabhat. (2019). Deep learning "
        "and process understanding for data-driven Earth system "
        "science. Nature, 566, 195–204.",
    ]),
    # ──────────── G. Sistemas de alerta temprana ────────────
    ("G. Sistemas de alerta temprana hidrometeorológica", [
        "Alfieri, L., Salamon, P., Pappenberger, F., Wetterhall, F., & "
        "Thielen, J. (2012). Operational early warning systems for "
        "water-related hazards in Europe. Environmental Science & "
        "Policy, 21, 35–49.",
        "Pappenberger, F., Cloke, H. L., Parker, D. J., Wetterhall, F., "
        "Richardson, D. S., & Thielen, J. (2015). The monetary benefit "
        "of early flood warnings in Europe. Environmental Science & "
        "Policy, 51, 278–291.",
        "United Nations Office for Disaster Risk Reduction. (2015). "
        "Sendai Framework for Disaster Risk Reduction 2015–2030. UN.",
        "Vitart, F., Ardilouze, C., Bonet, A., Brookshaw, A., Chen, "
        "M., Codorean, C., … Zhang, L. (2017). The Subseasonal to "
        "Seasonal (S2S) Prediction Project Database. Bulletin of the "
        "American Meteorological Society, 98(1), 163–173.",
        "World Meteorological Organization. (2015). WMO Guidelines on "
        "Multi-Hazard Impact-Based Forecast and Warning Services "
        "(WMO-No. 1150). WMO.",
        "World Meteorological Organization. (2016). Handbook of "
        "drought indicators and indices (WMO-No. 1173). World "
        "Meteorological Organization & Global Water Partnership.",
        "European Commission, Joint Research Centre. (s. f.). Global "
        "Flood Awareness System (GloFAS). "
        "https://www.globalfloods.eu",
        "European Commission, Joint Research Centre. (s. f.). European "
        "Drought Observatory (EDO). "
        "https://edo.jrc.ec.europa.eu",
    ]),
    # ──────────── H. Marco internacional por uso ────────────
    ("H. Marco internacional por uso del agua", [
        # Agua potable
        "World Health Organization. (2017). Guidelines for "
        "drinking-water quality (4th ed., including the 1st addendum). "
        "WHO. https://www.who.int/publications/i/item/9789241549950",
        "World Health Organization. (2023). Water safety plan manual: "
        "step-by-step risk management for drinking-water suppliers "
        "(2nd ed.). WHO.",
        "United Nations General Assembly. (2010). The human right to "
        "water and sanitation. Resolution A/RES/64/292.",
        "European Parliament and Council. (2020). Directive (EU) "
        "2020/2184 on the quality of water intended for human "
        "consumption (recast). Official Journal of the European "
        "Union, L 435/1.",
        "Health Canada. (2022). Guidelines for Canadian drinking water "
        "quality — summary tables. Federal-Provincial-Territorial "
        "Committee on Drinking Water.",
        # Riego
        "Allen, R. G., Pereira, L. S., Raes, D., & Smith, M. (1998). "
        "Crop evapotranspiration — Guidelines for computing crop "
        "water requirements (FAO Irrigation and Drainage Paper 56). "
        "Food and Agriculture Organization of the United Nations.",
        "Doorenbos, J., & Kassam, A. H. (1979). Yield response to "
        "water (FAO Irrigation and Drainage Paper 33). FAO.",
        "Food and Agriculture Organization of the United Nations. "
        "(2023). Water quality for agriculture (rev.). FAO.",
        "Food and Agriculture Organization of the United Nations. "
        "(2023). Water quality in agriculture: risks and risk "
        "mitigation. FAO.",
        "International Organization for Standardization. (2020). "
        "ISO 16075-1:2020 — Guidelines for treated wastewater use for "
        "irrigation projects (Part 1: The basis of a reuse project for "
        "irrigation). ISO.",
        # Hidroeléctrico y presas
        "International Commission on Large Dams. (s. f.). ICOLD "
        "technical bulletins. ICOLD.",
        "International Electrotechnical Commission. (1999). IEC 60041 "
        "— Field acceptance tests to determine the hydraulic "
        "performance of hydraulic turbines, storage pumps and pump-"
        "turbines. IEC.",
        "International Electrotechnical Commission. (1992). IEC 61116 "
        "— Electromechanical equipment guide for small hydroelectric "
        "installations. IEC.",
        "U.S. Bureau of Reclamation. (1987). Design of small dams "
        "(3rd ed.). U.S. Department of the Interior.",
        # Ecológicos
        "Bovee, K. D. (1982). A guide to stream habitat analysis using "
        "the Instream Flow Incremental Methodology (Instream Flow "
        "Information Paper No. 12, FWS/OBS-82/26). U.S. Fish and "
        "Wildlife Service.",
        "King, J., & Louw, D. (1998). Instream flow assessments for "
        "regulated rivers in South Africa using the Building Block "
        "Methodology. Aquatic Ecosystem Health and Management, 1, "
        "109–124.",
        "Tennant, D. L. (1976). Instream flow regimens for fish, "
        "wildlife, recreation and related environmental resources. "
        "Fisheries, 1(4), 6–10.",
        # Investigación científica
        "Council for International Organizations of Medical Sciences. "
        "(2016). International ethical guidelines for health-related "
        "research involving humans (4th ed.). CIOMS & World Health "
        "Organization.",
        "United Nations Educational, Scientific and Cultural "
        "Organization. (2021). UNESCO Recommendation on Open Science. "
        "UNESCO. https://doi.org/10.54677/MNMH8546",
        "United Nations Educational, Scientific and Cultural "
        "Organization. (2023). Open Science Outlook 1: Status and "
        "trends around the world. UNESCO.",
        "World Medical Association. (2024). WMA Declaration of "
        "Helsinki — Ethical principles for medical research involving "
        "human subjects (revised). WMA.",
    ]),
    # ──────────── I. Cooperación y banca multilateral ────────────
    ("I. Cooperación internacional y banca multilateral", [
        "Banco Interamericano de Desarrollo. (s. f.). Política "
        "Operativa OP-703: Medio Ambiente y Cumplimiento de "
        "Salvaguardas. BID.",
        "Banco Mundial. (2018). Marco Ambiental y Social. Estándar "
        "Ambiental y Social 6 (ESS6): Biodiversidad y servicios "
        "ecosistémicos. Grupo Banco Mundial.",
        "Banco Mundial. (2024). Guía de caudales ecológicos para "
        "Latinoamérica. Corporación Andina de Fomento.",
        "Corporación Andina de Fomento. (2021). Política Ambiental y "
        "Social. CAF.",
        "Cooperación Suiza al Desarrollo. (s. f.). Programa de Cuencas "
        "en Bolivia. COSUDE.",
        "Deutsche Gesellschaft für Internationale Zusammenarbeit. "
        "(s. f.). Manejo integrado de recursos hídricos en los Andes "
        "(PROAGUA II). GIZ.",
        "Hirji, R., & Davis, R. (2009). Environmental flows in water "
        "resources policies, plans, and projects: Findings and "
        "recommendations. The World Bank.",
        "International Union for Conservation of Nature. (2003). "
        "Flow: The essentials of environmental flows (M. Dyson, G. "
        "Bergkamp, & J. Scanlon, Eds.). IUCN.",
    ]),
    # ──────────── J. Hidrología clásica y manuales de referencia ────────────
    ("J. Hidrología clásica y manuales de referencia", [
        "Chow, V. T., Maidment, D. R., & Mays, L. W. (1994). "
        "Hidrología aplicada. McGraw-Hill Interamericana.",
        "Huff, F. A. (1967). Time distribution of rainfall in heavy "
        "storms. Water Resources Research, 3(4), 1007–1019. "
        "https://doi.org/10.1029/WR003i004p01007",
        "Kirpich, Z. P. (1940). Time of concentration of small "
        "agricultural watersheds. Civil Engineering, 10(6), 362.",
        "Organización Meteorológica Mundial. (2009). Guide to "
        "hydrological practices (Vol. II, WMO-No. 168, 6th ed.). WMO.",
        "Sherman, C. W. (1931). Frequency and intensity of excessive "
        "rainfalls at Boston, Massachusetts. Transactions of the "
        "American Society of Civil Engineers, 95(1), 951–960.",
        "Témez, J. R. (1978). Cálculo hidrometeorológico de caudales "
        "máximos en pequeñas cuencas naturales. Ministerio de Obras "
        "Públicas y Urbanismo, España.",
        "U.S. Department of Agriculture, Soil Conservation Service. "
        "(1986). Urban hydrology for small watersheds (Technical "
        "Release 55, 2nd ed.). USDA-SCS.",
        "U.S. Department of Agriculture, Natural Resources "
        "Conservation Service. (2004). National Engineering Handbook, "
        "Part 630 — Hydrology, Chapter 10: Estimation of direct runoff "
        "from storm rainfall. USDA-NRCS.",
        "U.S. Army Corps of Engineers, Hydrologic Engineering Center. "
        "(2022). HEC-HMS User's Manual, Version 4.10. USACE-HEC. "
        "https://www.hec.usace.army.mil/software/hec-hms",
    ]),
    # ──────────── K. Selección y evaluación de modelos de cambio climático ────────────
    ("K. Selección y evaluación de modelos de cambio climático "
      "(Sección 3.1)", [
        "Nash, J. E., & Sutcliffe, J. V. (1970). River flow forecasting "
        "through conceptual models part I — A discussion of principles. "
        "Journal of Hydrology, 10(3), 282–290. "
        "https://doi.org/10.1016/0022-1694(70)90255-6",
        "Taylor, K. E. (2001). Summarizing multiple aspects of model "
        "performance in a single diagram. Journal of Geophysical "
        "Research: Atmospheres, 106(D7), 7183–7192. "
        "https://doi.org/10.1029/2000JD900719",
        "Giorgi, F., & Mearns, L. O. (2002). Calculation of average, "
        "uncertainty range, and reliability of regional climate changes "
        "from AOGCM simulations via the «Reliability Ensemble Averaging» "
        "(REA) method. Journal of Climate, 15(10), 1141–1158. "
        "https://doi.org/10.1175/1520-0442(2002)015<1141:COAURA>2.0.CO;2",
        "Moriasi, D. N., Arnold, J. G., Van Liew, M. W., Bingner, R. L., "
        "Harmel, R. D., & Veith, T. L. (2007). Model evaluation "
        "guidelines for systematic quantification of accuracy in "
        "watershed simulations. Transactions of the ASABE, 50(3), "
        "885–900. https://doi.org/10.13031/2013.23153",
        "Reichler, T., & Kim, J. (2008). How well do coupled models "
        "simulate today's climate? Bulletin of the American "
        "Meteorological Society, 89(3), 303–311. "
        "https://doi.org/10.1175/BAMS-89-3-303",
        "Gleckler, P. J., Taylor, K. E., & Doutriaux, C. (2008). "
        "Performance metrics for climate models. Journal of Geophysical "
        "Research: Atmospheres, 113, D06104. "
        "https://doi.org/10.1029/2007JD008972",
        "Gupta, H. V., Kling, H., Yilmaz, K. K., & Martinez, G. F. "
        "(2009). Decomposition of the mean squared error and NSE "
        "performance criteria: Implications for improving hydrological "
        "modelling. Journal of Hydrology, 377(1–2), 80–91. "
        "https://doi.org/10.1016/j.jhydrol.2009.08.003",
        "Moriasi, D. N., Gitau, M. W., Pai, N., & Daggupati, P. (2015). "
        "Hydrologic and water quality models: Performance measures and "
        "evaluation criteria. Transactions of the ASABE, 58(6), "
        "1763–1785. https://doi.org/10.13031/trans.58.10715",
        "Knoben, W. J. M., Freer, J. E., & Woods, R. A. (2019). "
        "Technical note: Inherent benchmark or not? Comparing Nash–"
        "Sutcliffe and Kling–Gupta efficiency scores. Hydrology and "
        "Earth System Sciences, 23(10), 4323–4331. "
        "https://doi.org/10.5194/hess-23-4323-2019",
        "Pushpalatha, R., Perrin, C., Le Moine, N., & Andréassian, V. "
        "(2012). A review of efficiency criteria suitable for evaluating "
        "low-flow simulations. Journal of Hydrology, 420–421, 171–182. "
        "https://doi.org/10.1016/j.jhydrol.2011.11.055",
        "Santos, L., Thirel, G., & Perrin, C. (2018). Technical note: "
        "Pitfalls in using log-transformed flows within the KGE "
        "criterion. Hydrology and Earth System Sciences, 22(8), "
        "4583–4591. https://doi.org/10.5194/hess-22-4583-2018",
        "Garrick, M., Cunnane, C., & Nash, J. E. (1978). A criterion of "
        "efficiency for rainfall–runoff models. Journal of Hydrology, "
        "36(3–4), 375–381. "
        "https://doi.org/10.1016/0022-1694(78)90155-5",
        "Tebaldi, C., & Knutti, R. (2007). The use of the multi-model "
        "ensemble in probabilistic climate projections. Philosophical "
        "Transactions of the Royal Society A, 365(1857), 2053–2075. "
        "https://doi.org/10.1098/rsta.2007.2076",
        "Whetton, P., Hennessy, K., Clarke, J., McInnes, K., & Kent, D. "
        "(2012). Use of representative climate futures in impact and "
        "adaptation assessment. Climatic Change, 115(3–4), 433–442. "
        "https://doi.org/10.1007/s10584-012-0471-z",
        "Bishop, C. H., & Abramowitz, G. (2013). Climate model "
        "dependence and the replicate Earth paradigm. Climate Dynamics, "
        "41(3–4), 885–900. https://doi.org/10.1007/s00382-012-1610-y",
        "Knutti, R., Sedláček, J., Sanderson, B. M., Lorenz, R., "
        "Fischer, E. M., & Eyring, V. (2017). A climate model "
        "projection weighting scheme accounting for performance and "
        "interdependence. Geophysical Research Letters, 44(4), "
        "1909–1918. https://doi.org/10.1002/2016GL072012",
        "Sanderson, B. M., Wehner, M., & Knutti, R. (2017). Skill and "
        "independence weighting for multi-model assessments. "
        "Geoscientific Model Development, 10(6), 2379–2395. "
        "https://doi.org/10.5194/gmd-10-2379-2017",
        "Abramowitz, G., Herger, N., Gutmann, E., Hammerling, D., "
        "Knutti, R., et al. (2019). ESD Reviews: Model dependence in "
        "multi-model climate ensembles. Earth System Dynamics, 10(1), "
        "91–105. https://doi.org/10.5194/esd-10-91-2019",
        "Brunner, L., Pendergrass, A. G., Lehner, F., Merrifield, A. L., "
        "Lorenz, R., & Knutti, R. (2020). Reduced global warming from "
        "CMIP6 projections when weighting models by performance and "
        "independence. Earth System Dynamics, 11(4), 995–1012. "
        "https://doi.org/10.5194/esd-11-995-2020",
        "Wood, A. W., Maurer, E. P., Kumar, A., & Lettenmaier, D. P. "
        "(2002). Long-range experimental hydrologic forecasting for the "
        "eastern United States. Journal of Geophysical Research: "
        "Atmospheres, 107(D20), 4429. "
        "https://doi.org/10.1029/2001JD000659",
        "Wood, A. W., Leung, L. R., Sridhar, V., & Lettenmaier, D. P. "
        "(2004). Hydrologic implications of dynamical and statistical "
        "approaches to downscaling climate model outputs. Climatic "
        "Change, 62(1–3), 189–216. "
        "https://doi.org/10.1023/B:CLIM.0000013685.99609.9e",
        "Schmidli, J., Frei, C., & Vidale, P. L. (2006). Downscaling "
        "from GCM precipitation: A benchmark for dynamical and "
        "statistical downscaling methods. International Journal of "
        "Climatology, 26(5), 679–689. "
        "https://doi.org/10.1002/joc.1287",
        "Themeßl, M. J., Gobiet, A., & Heinrich, G. (2012). Empirical-"
        "statistical downscaling and error correction of regional "
        "climate models and its impact on the climate change signal. "
        "Climatic Change, 112(2), 449–468. "
        "https://doi.org/10.1007/s10584-011-0224-4",
        "Teutschbein, C., & Seibert, J. (2012). Bias correction of "
        "regional climate model simulations for hydrological climate-"
        "change impact studies: Review and evaluation of different "
        "methods. Journal of Hydrology, 456–457, 12–29. "
        "https://doi.org/10.1016/j.jhydrol.2012.05.052",
        "Hempel, S., Frieler, K., Warszawski, L., Schewe, J., & "
        "Piontek, F. (2013). A trend-preserving bias correction — the "
        "ISI-MIP approach. Earth System Dynamics, 4(2), 219–236. "
        "https://doi.org/10.5194/esd-4-219-2013",
        "Cannon, A. J., Sobie, S. R., & Murdock, T. Q. (2015). Bias "
        "correction of GCM precipitation by quantile mapping: How well "
        "do methods preserve changes in quantiles and extremes? Journal "
        "of Climate, 28(17), 6938–6959. "
        "https://doi.org/10.1175/JCLI-D-14-00754.1",
        "Switanek, M. B., Troch, P. A., Castro, C. L., Leuprecht, A., "
        "Chang, H.-I., Mukherjee, R., & Demaria, E. M. C. (2017). "
        "Scaled distribution mapping: A bias correction method that "
        "preserves raw climate model projected changes. Hydrology and "
        "Earth System Sciences, 21(6), 2649–2666. "
        "https://doi.org/10.5194/hess-21-2649-2017",
        "Cannon, A. J. (2018). Multivariate quantile mapping bias "
        "correction: An N-dimensional probability density function "
        "transform for climate model simulations of multiple variables. "
        "Climate Dynamics, 50(1–2), 31–49. "
        "https://doi.org/10.1007/s00382-017-3580-6",
        "Sedlmeier, K., Feldmann, H., & Schädler, G. (2024). High-"
        "resolution climate projection dataset based on CMIP6 for Peru "
        "and Ecuador: BASD-CMIP6-PE. Scientific Data, 11, 34. "
        "https://doi.org/10.1038/s41597-023-02863-z",
        "Aguayo, R., León-Muñoz, J., Aguayo, M., Baez-Villanueva, "
        "O. M., Zambrano-Bigiarini, M., Araya-Osses, D., & Fernández, A. "
        "(2024). Impact of future climate scenarios and bias correction "
        "methods on the Achibueno River Basin. Water, 16(8), 1138. "
        "https://doi.org/10.3390/w16081138",
        "Seiler, C., Hutjes, R. W. A., & Kabat, P. (2013). Likely ranges "
        "of climate change in Bolivia. Journal of Applied Meteorology "
        "and Climatology, 52(6), 1303–1317. "
        "https://doi.org/10.1175/JAMC-D-12-0224.1",
        "Seiler, C., & Vicente-Serrano, S. M. (2022). Evaluation of "
        "long-term changes in precipitation over Bolivia based on "
        "observations and CMIP models. International Journal of "
        "Climatology, 43(4), 1980–1999. "
        "https://doi.org/10.1002/joc.7924",
        "Vuille, M., Bradley, R. S., Werner, M., & Keimig, F. (2003). "
        "20th century climate change in the tropical Andes: "
        "Observations and model results. Climatic Change, 59, 75–99. "
        "https://doi.org/10.1023/A:1024406427519",
        "Urrutia, R., & Vuille, M. (2009). Climate change projections "
        "for the tropical Andes using a regional climate model. Journal "
        "of Geophysical Research: Atmospheres, 114, D02108. "
        "https://doi.org/10.1029/2008JD011021",
        "Buytaert, W., Vuille, M., Dewulf, A., Urrutia, R., Karmalkar, "
        "A., & Célleri, R. (2010). Uncertainties in climate change "
        "projections and regional downscaling in the tropical Andes. "
        "Hydrology and Earth System Sciences, 14, 1247–1258. "
        "https://doi.org/10.5194/hess-14-1247-2010",
        "Condom, T., Rau, P., & Espinoza, J. C. (2011). Correction of "
        "TRMM 3B43 monthly precipitation data over the mountainous "
        "areas of Peru during 1998–2007. Hydrological Processes, "
        "25(12), 1924–1933. https://doi.org/10.1002/hyp.7949",
        "Solman, S. A. (2013). Regional climate modeling over South "
        "America: A review. Advances in Meteorology, 2013, 504357. "
        "https://doi.org/10.1155/2013/504357",
        "Falco, M., Carril, A. F., Menéndez, C. G., Zaninelli, P. G., & "
        "Li, L. Z. X. (2019). Assessment of CORDEX simulations over "
        "South America. Climate Dynamics, 52, 4771–4786. "
        "https://doi.org/10.1007/s00382-018-4412-z",
        "Marengo, J. A., Duffy, P. B., Sampaio, G., Salazar, L. F., & "
        "Borma, L. S. (2015). Projections of future meteorological "
        "drought and wet periods in the Amazon. Proceedings of the "
        "National Academy of Sciences, 112(43), 13172–13177. "
        "https://doi.org/10.1073/pnas.1421010112",
        "Espinoza, J. C., Garreaud, R., Poveda, G., Arias, P. A., "
        "Molina-Carpio, J., Masiokas, M., Viale, M., & Scaff, L. "
        "(2020). Hydroclimate of the Andes — Part I: Main climatic "
        "features. Frontiers in Earth Science, 8, 64. "
        "https://doi.org/10.3389/feart.2020.00064",
        "Pabón-Caicedo, J. D., Arias, P. A., Carril, A. F., Espinoza, "
        "J. C., Borrel, L. F., Goubanova, K., Lavado-Casimiro, W., "
        "Masiokas, M., Solman, S., & Villalba, R. (2020). Observed and "
        "projected hydroclimate changes in the Andes. Frontiers in "
        "Earth Science, 8, 61. "
        "https://doi.org/10.3389/feart.2020.00061",
        "Llopart, M., Reboita, M. S., Coppola, E., Giorgi, F., da "
        "Rocha, R. P., & de Souza, D. O. (2020). Assessment of multi-"
        "model climate projections of water resources over the South "
        "America CORDEX domain. Climate Dynamics, 54, 99–116. "
        "https://doi.org/10.1007/s00382-019-04990-z",
        "Almazroui, M., Ashfaq, M., Islam, M. N., Rashid, I. U., Kamil, "
        "S., Abid, M. A., et al. (2021). Assessment of CMIP6 "
        "performance and projected temperature and precipitation "
        "changes over South America. Earth Systems and Environment, "
        "5(2), 155–183. "
        "https://doi.org/10.1007/s41748-021-00233-6",
        "Ortega, G., Arias, P. A., Villegas, J. C., Marquet, P. A., & "
        "Nobre, P. (2021). Present-day and future climate over Central "
        "and South America according to CMIP5/CMIP6 models. "
        "International Journal of Climatology, 41(15), 6713–6735. "
        "https://doi.org/10.1002/joc.7221",
        "Reboita, M. S., da Rocha, R. P., Souza, C. A., Baldoni, T. C., "
        "Silva, P. L. L. S., & Ferreira, G. W. S. (2022). Future "
        "projections of extreme precipitation climate indices over "
        "South America based on CORDEX-CORE multimodel ensemble. "
        "Atmosphere, 13(9), 1463. "
        "https://doi.org/10.3390/atmos13091463",
        "Doblas-Reyes, F. J., Sörensson, A. A., Almazroui, M., Dosio, "
        "A., Gutiérrez, J. M., et al. (2021). Linking global to "
        "regional climate change. En Climate Change 2021: The Physical "
        "Science Basis (Cap. 10, pp. 1363–1512). IPCC / Cambridge "
        "University Press. "
        "https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-10/",
        "Ranasinghe, R., Ruane, A. C., Vautard, R., Arnell, N., "
        "Coppola, E., et al. (2021). Climate change information for "
        "regional impact and for risk assessment. En Climate Change "
        "2021: The Physical Science Basis (Cap. 12). IPCC / Cambridge "
        "University Press. "
        "https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-12/",
        "Gutiérrez, J. M., Jones, R. G., Narisma, G. T., Alves, L. M., "
        "et al. (2021). Atlas. IPCC AR6 WGI Interactive Atlas. "
        "Cambridge University Press / IPCC. "
        "https://interactive-atlas.ipcc.ch",
        "Rathjens, H., Bieger, K., Srinivasan, R., Chaubey, I., & "
        "Arnold, J. G. (2016). CMhyd user manual: Documentation for "
        "preparing simulated climate change data for hydrologic impact "
        "studies. Texas A&M AgriLife / SWAT.",
        "Zhang, X., & Yang, F. (2004). RClimDex (1.0) user manual. "
        "Climate Research Branch, Environment Canada / ETCCDI.",
        "Klein Tank, A. M. G., Zwiers, F. W., & Zhang, X. (2009). "
        "Guidelines on analysis of extremes in a changing climate in "
        "support of informed decisions for adaptation (WMO-TD No. 1500, "
        "WCDMP-72). World Meteorological Organization.",
    ]),
]


def total_referencias() -> int:
    """Conteo total de referencias en el catálogo."""
    return sum(len(items) for _, items in REFERENCIAS_APA)


def numerar() -> list[tuple[str, list[tuple[int, str]]]]:
    """Devuelve la lista con cada referencia numerada secuencialmente."""
    n = 1
    out = []
    for grupo, items in REFERENCIAS_APA:
        numeradas = []
        for it in items:
            numeradas.append((n, it))
            n += 1
        out.append((grupo, numeradas))
    return out
