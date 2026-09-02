"""Marcos normativos, referencias y métodos por tipo de uso del caudal mínimo.

Cada uso del agua tiene su propio cuerpo normativo (nacional Bolivia +
internacional) y un conjunto de métodos y parámetros aplicables al cálculo
del caudal mínimo de diseño. Este módulo centraliza esa información para
que el informe y la vista web se rendericen consistentes según la opción
elegida en el formulario.

Estructura por uso:
    - "marco_nacional": leyes, normas y planes nacionales aplicables.
    - "marco_internacional": estándares y guías de organismos globales.
    - "metodos": métodos de cálculo recomendados para ese uso.
    - "parametros_clave": variables a reportar en el informe.
    - "consideraciones": notas técnicas específicas.
"""

from __future__ import annotations


# Etiquetas legibles para mostrar al usuario.
NOMBRE_USO = {
    "captacion_agua":        "Captación para agua potable",
    "riego":                 "Captación para riego",
    "hidroelectrico":        "Aprovechamiento hidroeléctrico",
    "ecologico":             "Caudal ecológico mínimo",
    "investigacion_cientifica": "Análisis para investigación científica",
}


MARCOS = {
    # ─────────────────────────────────────────────────────────────────────
    "captacion_agua": {
        "titulo": "4. Marco para captación de agua potable",
        "introduccion": (
            "El diseño de captaciones para agua potable en Bolivia se "
            "articula sobre tres ejes: el derecho humano al agua reconocido "
            "por Naciones Unidas, la normativa nacional sectorial "
            "(Ley 2029 modificada por Ley 2066, Ley 1333 del Medio "
            "Ambiente, normas técnicas NB 512 y NB 688) y los estándares "
            "internacionales (OMS/GDWQ, Directiva Marco del Agua de la "
            "Unión Europea, Guidelines de Health Canada, recomendaciones "
            "FAO). El cálculo del caudal mínimo de aprovechamiento debe "
            "garantizar la demanda futura con horizonte de 20 años y "
            "respetar al menos el 80 % del caudal mínimo natural de la "
            "fuente (Ley 1333) para preservar el ecosistema y los usos "
            "aguas abajo."
        ),
        "marco_nacional": [
            ("Ley N° 2029 (29-oct-1999)",
             "Ley de Servicios de Agua Potable y Alcantarillado Sanitario. "
             "Marco institucional, concesiones, licencias, derechos del "
             "usuario y régimen tarifario. Crea la Superintendencia de "
             "Saneamiento Básico (hoy AAPS)."),
            ("Ley N° 2066 (11-abr-2000)",
             "Ley modificatoria a la Ley 2029. Incorpora salvaguardas para "
             "comunidades indígenas y reconoce los sistemas comunitarios "
             "del agua. Vigente y actualizada."),
            ("Ley N° 1333 (27-abr-1992) — Art. 44",
             "Ley del Medio Ambiente. El Art. 44 establece que el Estado "
             "promueve y fomenta el uso racional del agua, declarando de "
             "necesidad pública la conservación de los recursos hídricos. "
             "Toda obra que afecte fuentes de agua requiere licencia "
             "ambiental."),
            ("Ley N° 1333 (27-abr-1992) — Art. 48",
             "Faculta al Estado a clasificar los cuerpos de agua según uso "
             "(consumo humano, riego, recreación, industria) y a establecer "
             "estándares de calidad y caudales mínimos a preservar. Es el "
             "fundamento del DS 24176 y de NB 512."),
            ("Ley N° 071 (21-dic-2010)",
             "Ley de Derechos de la Madre Tierra. Reconoce al agua como "
             "sujeto de derechos. Exige preservar caudales que garanticen "
             "la vida del ecosistema fuente y aguas abajo."),
            ("Ley N° 300 (15-oct-2012)",
             "Ley Marco de la Madre Tierra y Desarrollo Integral para "
             "Vivir Bien. Operativiza la Ley 071 con principios de "
             "complementariedad, equilibrio y responsabilidad."),
            ("DS N° 24176 (08-dic-1995) — Reglamento Ley 1333",
             "Reglamento de Gestión Ambiental del Recurso Hídrico. "
             "Clasifica los cuerpos de agua en clases A, B, C, D según uso "
             "permitido y exige autorización de la Prefectura para captar "
             "más del 20 % del caudal mínimo natural histórico (Q mín)."),
            ("NB 512 (ed. vigente)",
             "Norma Boliviana — Requisitos de calidad para agua potable. "
             "IBNORCA. Clasifica el agua en clase A (máxima calidad: "
             "desinfección bacteriológica), B (tratamiento convencional), "
             "C (tratamiento avanzado) y D (tratamiento intensivo o no "
             "potabilizable). Define los valores máximos admisibles para "
             "parámetros físico-químicos, microbiológicos y radiológicos."),
            ("NB 688 (ed. vigente)",
             "Norma Boliviana — Diseño, construcción y mantenimiento de "
             "sistemas de agua potable. Establece criterios de Q de "
             "diseño, dotación per cápita (de 80 a 250 L/hab·día según "
             "zona y altitud), factores de mayoración K1 y K2, y "
             "horizontes de proyecto."),
            ("NB 689 (ed. vigente)",
             "Norma Boliviana complementaria — Diseño de sistemas de agua "
             "potable. Detalla criterios para captaciones superficiales, "
             "subterráneas, pre-tratamientos y aducciones."),
            ("Plan Nacional de Cuencas (MMAyA / VRHR)",
             "Marco programático que prioriza cuencas estratégicas para "
             "abastecimiento y exige estudios de oferta-demanda con "
             "horizonte de 25 años para proyectos de captación."),
            ("Reglamento de la AAPS (Autoridad de Fiscalización de Agua "
             "Potable y Saneamiento Básico)",
             "Procedimientos para obtener concesiones y licencias de uso "
             "de la fuente; auditorías técnicas y tarifarias."),
        ],
        "marco_internacional": [
            ("Resolución A/RES/64/292 (ONU, 28-jul-2010)",
             "Reconoce el derecho humano al agua potable y al saneamiento "
             "como esencial para la plena realización de la vida y de "
             "todos los demás derechos humanos."),
            ("Resolución A/HRC/RES/15/9 (Consejo DDHH ONU, 2010)",
             "Refuerza la Resolución 64/292 y exige a los Estados "
             "mecanismos progresivos de realización."),
            ("ODS 6 — Agenda 2030 (ONU, 2015)",
             "Agua limpia y saneamiento. Indicadores 6.1 (acceso universal "
             "a agua potable segura), 6.4 (estrés hídrico) y 6.6 "
             "(ecosistemas hídricos) miden la sostenibilidad de la "
             "captación."),
            ("WHO — Guidelines for Drinking-Water Quality (GDWQ, 4.ª ed. "
             "2017 + 1.er addendum 2022)",
             "Estándar internacional de referencia para calidad y "
             "vigilancia del agua potable. Define los Water Safety Plans "
             "(WSP) como herramienta integral de gestión de riesgos desde "
             "la captación hasta el consumidor."),
            ("WHO — Water Safety Plan Manual (2.ª ed. 2023)",
             "Guía operativa para implementar Water Safety Plans en "
             "sistemas urbanos y rurales. Obligatoria para certificación "
             "ISO 24512."),
            ("WHO/UNICEF — Joint Monitoring Programme (JMP)",
             "Define los servicios «gestionados de forma segura» (Safely "
             "Managed): continuidad, calidad, disponibilidad y ubicación. "
             "Indicador oficial de ODS 6.1.1."),
            ("UE — Directiva Marco del Agua 2000/60/CE (DMA)",
             "Establece el marco comunitario europeo para protección de "
             "todas las aguas (superficiales, subterráneas y costeras) y "
             "exige planes de gestión de demarcación hidrográfica con "
             "horizonte de buen estado ecológico al 2027."),
            ("UE — Directiva 98/83/CE (refundida por Directiva 2020/2184)",
             "Calidad del agua destinada al consumo humano. Refuerza el "
             "enfoque de riesgo (basado en GDWQ) y exige cumplimiento "
             "estricto en proveedores de más de 50 personas."),
            ("Health Canada — Guidelines for Canadian Drinking Water "
             "Quality (Summary, actualizado periódicamente)",
             "Referencia internacional usada por OPS para revisión de "
             "estándares en países que no cuentan con cuerpos técnicos "
             "propios. Valores guía para más de 90 parámetros."),
            ("Health Canada — Source-to-Tap Approach",
             "Marco metodológico fuente-grifo que la GDWQ adopta. "
             "Equivalente operativo al Water Safety Plan."),
            ("FAO — Code of Practice on Water Quality and Health for "
             "Drinking Water Sources",
             "Recomendaciones para protección de fuentes de agua potable, "
             "especialmente en cuencas rurales con uso agropecuario."),
            ("FAO AQUASTAT / GLAAS (UN-Water)",
             "Bases de datos de monitoreo del recurso y la prestación del "
             "servicio."),
            ("ISO 24512 (2007)",
             "Gestión de servicios de agua potable. Estándar internacional "
             "de calidad para empresas operadoras."),
            ("ISO 24518 (2015)",
             "Gestión de crisis en servicios de agua y saneamiento. "
             "Aplicable a respuesta ante sequías y emergencias."),
            ("ISO 14001 — Gestión Ambiental",
             "Aplicable a operadores de captación; complementa los Water "
             "Safety Plans con sistema de gestión ambiental certificable."),
        ],
        "metodos": [
            ("Curva de duración de caudales (FDC)",
             "Q90 y Q95 como base del caudal mínimo de diseño. Si la "
             "captación supera el 20 % del Q mínimo se requiere EIA "
             "ambiental (DS 24176, Ley 1333). Recomendado por GDWQ y la "
             "Directiva 2020/2184 de la UE."),
            ("Análisis de frecuencia de caudales mínimos (Q7,10 y Q30,10)",
             "Distribuciones Weibull, LogNormal y Log-Pearson III "
             "invertidas. Q mínimo de 7 días con período de retorno 10 "
             "años (criterio EPA/USA y Health Canada) y de 30 días (uso "
             "europeo)."),
            ("Q mínimo de 5 años — criterio Ley 1333",
             "La Ley 1333 fija el umbral del 20 % del Q mín, 5 años como "
             "frontera para definir si la captación es de impacto menor o "
             "requiere autorización plena de la Prefectura."),
            ("Balance oferta-demanda con proyección poblacional",
             "Demanda proyectada con tasa de crecimiento del INE y "
             "dotación NB 688 (80–250 L/hab·día). Horizonte de 20 años. "
             "Verifica margen de seguridad Q90 / Q_demanda ≥ 1.20."),
            ("Clasificación de la fuente (NB 512 — clases A/B/C/D)",
             "Determina el tren de tratamiento necesario: Clase A (solo "
             "desinfección), B (convencional: coagulación + sedimentación "
             "+ filtración + desinfección), C (avanzado: ozonización, "
             "carbón activado, UV), D (intensivo o no potabilizable)."),
            ("Water Safety Plan (WSP) — WHO/GDWQ",
             "Metodología integral de gestión de riesgos desde la fuente "
             "hasta el consumidor. Obligatoria para certificación ISO "
             "24512. Incluye HACCP hídrico, identificación de peligros y "
             "monitoreo de barreras múltiples."),
            ("Análisis de sequía meteorológica (SPI/SPEI)",
             "Identifica la probabilidad de ocurrencia de eventos secos "
             "críticos en el horizonte del proyecto. Recomendado por WMO "
             "y JMP para evaluación de continuidad del servicio."),
            ("Caudal ecológico residual",
             "Qeco mínimo ≈ Q90 de la FDC o 10 % del caudal medio anual "
             "(criterio Ley 071 y Banco Mundial EFA). Debe quedar "
             "disponible aguas abajo después de la captación."),
        ],
        "flujo_tecnico": [
            ("1. Ubicación y delineación de cuenca",
             "Coordenadas del punto + watershed D8 con MERIT Hydro 90 m "
             "(módulo de Q máximos)."),
            ("2. Obtención de serie histórica",
             "Caudales diarios de SENAMHI / INE-ANDA o serie modelada "
             "CHIRPS·ERA5 si no hay aforo a menos de 50 km."),
            ("3. Cálculo de FDC",
             "Curva de duración → Q5, Q50, Q90, Q95 y Q mínimo de 5 años."),
            ("4. Verificación del 20 % (Ley 1333)",
             "Q captación ≤ 0.20 × Q mín, 5 años → autorización ambiental "
             "simplificada. Si supera el 20 % se exige EIA completa."),
            ("5. Caudal ecológico residual",
             "Q eco ≈ Q90 o 10 % del Q anual (Ley 071 + Banco Mundial)."),
            ("6. Clasificación de la fuente (NB 512)",
             "Asignación de Clase A/B/C/D según los parámetros físico-"
             "químicos y microbiológicos disponibles o estimados."),
            ("7. Estudio de impacto ambiental (si Q > 20 % Q mín)",
             "Procedimiento ante la Prefectura departamental. Requiere "
             "MAE Habilitada y participación social (Ley 071)."),
            ("8. Water Safety Plan (WSP)",
             "Plan integral OMS de gestión de riesgos. Requerido para "
             "sistemas servidos a más de 5 000 habitantes; recomendado "
             "para todos."),
            ("9. Emisión del informe técnico",
             "Documento para tramitar la licencia ambiental (RASIM) y la "
             "concesión de uso de agua ante la AAPS."),
        ],
        "parametros_clave": [
            "Q90 y Q95 de la FDC (m³/s)",
            "Q7,10 — mínimo de 7 días con T = 10 años (m³/s)",
            "Q30,10 — mínimo de 30 días con T = 10 años (m³/s)",
            "Q mínimo de 5 años (m³/s) — umbral Ley 1333",
            "Q captación / Q mín, 5 años (debe ser ≤ 0.20)",
            "Q ecológico residual = max(Q90, 0.10 × Q anual)",
            "Demanda proyectada a 20 años (m³/s) — NB 688",
            "Margen de seguridad Q90 / Q_demanda (≥ 1.20)",
            "Clase de la fuente según NB 512 (A / B / C / D)",
            "Índice de sequía SPI-12 y SPEI-12 promedio",
            "Frecuencia de Q < Q90 por década (días/año)",
            "Parámetros NB 512 monitoreados: turbidez (UNT), pH, "
            "conductividad, coliformes totales, E. coli, hierro, arsénico, "
            "nitratos, color, olor.",
        ],
        "consideraciones": (
            "El procedimiento boliviano se articula en torno a tres umbrales "
            "que el informe debe cuantificar y reportar explícitamente: "
            "(a) el 20 % del Q mínimo histórico de 5 años (Ley 1333 — "
            "frontera entre autorización simplificada y EIA plena ante la "
            "Prefectura), (b) el caudal ecológico residual obligatorio "
            "(Ley 071 — al menos el Q90 o el 10 % del caudal medio anual) "
            "y (c) el margen de seguridad oferta-demanda ≥ 1.20 (NB 688). "
            "Para sistemas mayores a 5 000 habitantes la OMS exige "
            "Water Safety Plan; para todos los sistemas la Directiva UE "
            "2020/2184 ya adoptó este enfoque como obligatorio. Las "
            "cuencas con glaciares en retroceso (Cordillera Real, "
            "Apolobamba, Tunari) requieren ajustar la proyección de oferta "
            "con tendencias de CMIP6 (sección 5 del informe) por la "
            "pérdida estructural de aporte glaciar al 2050."
        ),
    },
    # ─────────────────────────────────────────────────────────────────────
    "riego": {
        "titulo": "4. Marco para captación de agua de riego",
        "introduccion": (
            "El diseño de captaciones para riego en Bolivia se sustenta en "
            "la Ley Nacional de Riego (Ley 2878), su reglamentación, los "
            "instrumentos del SENARI y la experiencia acumulada por el "
            "Programa Nacional de Riego (PRONAR) con cooperación de la "
            "GTZ, HELVETAS, COSUDE y otras agencias. Internacionalmente "
            "se aplican los lineamientos técnicos de la FAO (Crop "
            "Evapotranspiration, Yield Response to Water, Water Quality "
            "for Agriculture), los estándares de calidad ISO 16075 para "
            "reutilización de aguas tratadas y las recomendaciones de "
            "SPANCOLD, USBR e ICOLD para presas de derivación y "
            "captaciones permanentes. El caudal mínimo de diseño debe "
            "asegurar la lámina requerida por la cédula de cultivos en "
            "los meses críticos, respetando la prelación constitucional "
            "de usos (agua potable, riego, otros)."
        ),
        "marco_nacional": [
            ("Ley N° 2878 (08-oct-2004)",
             "Ley de Promoción y Apoyo al Sector Riego. Reconoce el "
             "derecho colectivo al agua y crea el SENARI (Servicio "
             "Nacional de Riego) como autoridad nacional y los SEDERI "
             "departamentales como autoridades operativas."),
            ("DS N° 28817 (02-ago-2006)",
             "Reglamento de la Ley 2878. Define registros, autorizaciones, "
             "procedimientos para Distritos de Riego, derechos colectivos "
             "y mecanismos de gestión participativa de las fuentes."),
            ("Reglamento General para la Gestión de Distritos de Riego",
             "Regula la creación, organización y operación de los "
             "Distritos de Riego como unidades territoriales de gestión "
             "del agua para fines agrícolas. Establece estatutos, "
             "asignación de turnos, operación y mantenimiento de obras."),
            ("Ministerio del Agua / Ministerio de Medio Ambiente y Agua "
             "(MMAyA — Viceministerio de Recursos Hídricos y Riego, VRHR)",
             "Autoridad sectorial. Aplica las políticas nacionales de "
             "riego y articula los programas con la cooperación "
             "internacional."),
            ("Ley N° 071 (2010) y Ley N° 300 (2012)",
             "Marco de la Madre Tierra. Reconocen al agua como sujeto de "
             "derechos y exigen preservar el caudal ecológico aguas abajo "
             "de cualquier derivación."),
            ("Ley N° 1333 (1992) — Art. 44 y 48",
             "Ley del Medio Ambiente. Obliga a la EIA si la captación "
             "supera el 20 % del Q mínimo, 5 años, y clasifica los "
             "cuerpos de agua según uso permitido."),
            ("Ley N° 144 (2011)",
             "Ley de la Revolución Productiva Comunitaria Agropecuaria. "
             "Promueve sistemas de riego tecnificado en agricultura "
             "familiar y prioriza zonas de seguridad alimentaria."),
            ("Plan Nacional de Desarrollo de Riego \"Para Vivir Bien\" "
             "(MMAyA / VRHR)",
             "Marco programático con tipologías de proyectos y "
             "eficiencias exigibles según método (gravedad, aspersión, "
             "goteo). Incluye lineamientos de cofinanciamiento."),
            ("PRONAR — Programa Nacional de Riego (1996–2005)",
             "Programa fundacional ejecutado con apoyo de GTZ (Alemania) "
             "y crédito del KfW; sentó las bases técnicas del sector. "
             "Generó la Norma Boliviana de Riego, guías metodológicas y "
             "más de 800 proyectos. Referencia técnica obligada."),
            ("PRONAREC / MI RIEGO (continuidad PRONAR)",
             "Programas posteriores ejecutados con BID, CAF, COSUDE, "
             "HELVETAS para escalar la cobertura. Mantienen las "
             "metodologías PRONAR como base técnica."),
            ("HELVETAS Swiss Intercooperation — programas en Bolivia",
             "Cooperación técnica histórica en riego campesino, manejo "
             "integral de cuencas y enfoque de género."),
            ("COSUDE — Cooperación Suiza al Desarrollo",
             "Programa de Cuencas y Programa Riego. Lineamientos para "
             "captaciones en cuencas altoandinas."),
            ("Norma Boliviana de Riego (PRONAR / VRHR)",
             "Establece eficiencias mínimas de conducción (E_cond ≥ "
             "0.85 en tubería, 0.70 en canal revestido, 0.60 en canal de "
             "tierra), de distribución y de aplicación según método."),
            ("Plan Sectorial de Desarrollo Agropecuario (PSDA)",
             "Establece metas de riego e intensificación agrícola por "
             "departamento, vinculadas a la seguridad alimentaria."),
        ],
        "marco_internacional": [
            ("FAO Irrigation and Drainage Paper 56 (Allen, Pereira, Raes "
             "& Smith, 1998)",
             "Crop Evapotranspiration — guía estándar internacional para "
             "calcular ET₀ con Penman-Monteith y los coeficientes Kc por "
             "cultivo. Base técnica de todo cálculo de demanda de riego."),
            ("FAO IDP 33 (Doorenbos & Kassam, 1979)",
             "Yield Response to Water. Curvas de respuesta del "
             "rendimiento al estrés hídrico (factor Ky) para 23 "
             "cultivos."),
            ("FAO IDP 24",
             "Crop Water Requirements. Demanda hídrica por etapa "
             "fenológica."),
            ("FAO IDP 22",
             "Effective Rainfall in Irrigated Agriculture. Cálculo USDA-"
             "SCS de precipitación efectiva mensual."),
            ("FAO — Water Quality for Agriculture (2023, actualización)",
             "Guía actualizada que reemplaza al IDP 29 (Ayers & Westcot, "
             "1985). Estándares de conductividad eléctrica (CE), SAR, "
             "alcalinidad, toxicidad iónica para riego y reuso."),
            ("FAO — Water Quality in Agriculture: Risks and Risk "
             "Mitigation (2023)",
             "Marco basado en riesgo para evaluar y mitigar contaminación "
             "química y microbiológica del agua de riego. Define umbrales "
             "para metales pesados (As, Cd, Cr, Pb, Hg), pesticidas y "
             "patógenos."),
            ("ISO 16075-1:2020",
             "Guidelines for treated wastewater use for irrigation "
             "projects — Part 1: The basis of a reuse project for "
             "irrigation. Marco general para proyectos de reuso."),
            ("ISO 16075-2:2020",
             "Part 2: Development of the project. Diseño, evaluación de "
             "riesgos y monitoreo."),
            ("ISO 16075-3:2021 y -4:2016",
             "Components of a reuse project (3) y Monitoring (4). "
             "Especificaciones de infraestructura y vigilancia."),
            ("ISO 16075 series — extensiones",
             "Parts 5 (Risk management), 6 (Distribution and storage), "
             "7 (Maintenance), 8 (Reservoirs, en desarrollo). Cubren todo "
             "el ciclo de un proyecto de reuso."),
            ("FAO AQUASTAT",
             "Base de datos global de uso del agua agrícola. Indicadores "
             "de productividad y estrés."),
            ("FAO WaPOR (Water Productivity Open-access portal)",
             "Datos satelitales de productividad del agua, "
             "evapotranspiración real (ETa) y biomasa. Cobertura para "
             "Bolivia a 250 m."),
            ("ICID — International Commission on Irrigation and Drainage",
             "Marco técnico para diseño, operación y gestión de sistemas "
             "de riego. Publica los IRRIGATION Yearbook con estadísticas "
             "globales y casos de estudio."),
            ("SPANCOLD — Spanish National Committee on Large Dams",
             "Guías técnicas para presas pequeñas y medianas usadas como "
             "obras de toma para riego. Recomendaciones sísmicas y "
             "operativas en zonas mediterráneas comparables a los valles "
             "interandinos."),
            ("USBR — U.S. Bureau of Reclamation",
             "Design of Small Dams (3.ª ed., 1987 + actualizaciones), "
             "Design Standards y Engineering Monographs. Referencia "
             "internacional para presas derivadoras y captaciones de "
             "regulación."),
            ("ICOLD — International Commission on Large Dams",
             "Boletines técnicos para diseño, operación y seguridad de "
             "presas. Aplicables a presas de riego mayores a 15 m de "
             "altura o vaso > 3 hm³ (definición ICOLD de gran presa)."),
            ("UE — Reglamento 2020/741",
             "Requisitos mínimos para la reutilización del agua en riego "
             "agrícola (entró en vigor en 2023). Referencia comparativa."),
            ("WHO — Guidelines for the Safe Use of Wastewater, Excreta "
             "and Greywater (2006)",
             "Estándares OMS para reuso seguro en agricultura. Complemento "
             "obligatorio para proyectos que combinan riego con aguas "
             "tratadas."),
        ],
        "metodos": [
            ("Balance hídrico mensual con ET₀ Penman-Monteith (FAO 56)",
             "Calcula la demanda neta y bruta de riego para cada mes y "
             "cultivo. Estándar internacional sin discusión."),
            ("Cédula de cultivos + Kc por etapa fenológica",
             "Establece la demanda agregada del sistema y los meses pico. "
             "La cédula define la frontera técnica del proyecto."),
            ("Demanda hídrica neta del cultivo (m³/ha)",
             "Calculada como ET₀ × Kc × superficie del cultivo, "
             "descontando la precipitación efectiva. Base del "
             "dimensionamiento."),
            ("Q70 y Q75 de la FDC para diseño",
             "Práctica frecuente para riego: aceptar déficit en años "
             "secos (Q75 garantiza 75 % del tiempo). Para riego "
             "comunitario en cuencas altoandinas se usa Q80–Q85."),
            ("Análisis de frecuencia de mínimos de estiaje",
             "Distribuciones Weibull, LogNormal y LP3 invertidas. "
             "Determina la oferta segura en los meses críticos."),
            ("Q mín 5 años — criterio Ley 1333",
             "Verificación del umbral 20 % de la Ley 1333. Si supera, "
             "se requiere licencia ambiental ante la Prefectura."),
            ("Eficiencia global E = E_cond · E_distr · E_aplic",
             "Norma Boliviana de Riego. Determina el caudal bruto en "
             "captación a partir de la demanda neta."),
            ("Calidad del agua de riego — FAO 2023",
             "Análisis de conductividad eléctrica (CE), Relación de "
             "Adsorción de Sodio (SAR), pH, alcalinidad, toxicidad iónica "
             "y metales pesados. Clasificación FAO según riesgo de "
             "salinización, sodificación y toxicidad."),
            ("Caudal ecológico residual (Ley 071)",
             "Q eco ≈ Q90 o 10 % Q anual debe permanecer en el cauce "
             "después de la captación."),
            ("Diseño de presa derivadora — USBR / SPANCOLD",
             "Para captaciones permanentes con obra de toma + "
             "desripiador. Criterios sísmicos y de seguridad ICOLD si la "
             "obra califica como presa."),
        ],
        "flujo_tecnico": [
            ("1. Definir sitio, cuenca y cédula de cultivos",
             "Coordenadas del punto + delineación de cuenca por watershed "
             "MERIT Hydro 90 m + cédula de cultivos con superficies, "
             "etapas fenológicas y Kc."),
            ("2. Obtener serie histórica de caudales diarios",
             "Aforo SENAMHI / INE-ANDA / SEDERI más cercano (< 50 km) o "
             "balance modelado CHIRPS·ERA5 sobre la cuenca."),
            ("3. Calcular curva de duración (FDC)",
             "Q5, Q10, Q50, Q70, Q75, Q80, Q90, Q95, Q mínimo de 5 "
             "años."),
            ("4. Verificar umbral Ley 1333 (20 % del Q mín, 5 años)",
             "Q captación ≤ 0.20 × Q mín, 5 años → autorización ambiental "
             "simplificada. Si supera, se exige EIA plena ante la "
             "Prefectura."),
            ("5. Estimar caudal ecológico residual",
             "Q eco ≈ Q90 o 10 % Q anual (Ley 071 + lineamientos BM/CAF). "
             "Caudal que debe quedar en el cauce siempre."),
            ("6. Informe para la Licencia ambiental ante la Prefectura "
             "(si > 20 % Q mín)",
             "Elaborar el informe técnico-ambiental que sustenta la "
             "Licencia ambiental (RASIM) cuando Q captación supera el "
             "20 % del Q mín, 5 años. Para presas grandes (ICOLD) se "
             "exige EIA categoría 1."),
            ("7. Informe de Q mín para el diseño + Implementar obra + "
             "capacitación + monitoreo continuo",
             "Entrega del informe técnico de Q mín que sustenta el diseño "
             "de la obra de toma y la asignación de turnos, seguido de la "
             "construcción + acompañamiento técnico a la Asociación de "
             "Regantes + monitoreo de calidad (FAO 2023) y eficiencia "
             "operativa. Reporte anual al SENARI/SEDERI."),
        ],
        "parametros_clave": [
            "Q70, Q75, Q80 y Q90 de la FDC (m³/s)",
            "Q mín 5 años (m³/s) — umbral Ley 1333",
            "Q captación / Q mín, 5 años (debe ser ≤ 0.20)",
            "Q ecológico residual = max(Q90, 0.10 × Q anual)",
            "Demanda hídrica neta del cultivo (m³/ha y m³/s pico)",
            "Demanda bruta del sistema (m³/s) — incluye eficiencia",
            "ET₀ Penman-Monteith promedio mensual (mm/día)",
            "Kc ponderado por cédula y mes pico",
            "Precipitación efectiva mensual (USDA-SCS, mm)",
            "Eficiencia global E = E_cond · E_distr · E_aplic (%)",
            "Conductividad eléctrica CE (dS/m) y SAR — clasificación FAO",
            "pH, alcalinidad, toxicidad iónica (Cl⁻, Na⁺, B)",
            "Metales pesados (mg/L): As, Cd, Cr, Pb, Hg",
            "Tipo de derecho de uso: Registro o Autorización (Ley 2878)",
            "Déficit hídrico aceptable (años con falla) — típicamente 5–10 %",
        ],
        "consideraciones": (
            "La planificación de un proyecto de riego en Bolivia debe "
            "respetar tres prelaciones simultáneas: la jurídica del Art. "
            "373 de la Constitución (agua potable > riego > otros usos), "
            "la metodológica del SENARI (Registro para comunidades "
            "tradicionales vs Autorización para riego tecnificado) y la "
            "ambiental de la Ley 071 (caudal ecológico no negociable). "
            "Para presas de derivación mayores a 15 m de altura o con "
            "vaso > 3 hm³ se aplican los boletines técnicos ICOLD y los "
            "estándares de seguridad USBR/SPANCOLD; las obras menores "
            "pueden basarse en las guías PRONAR/HELVETAS. La FAO "
            "recomienda dimensionar con probabilidad de excedencia del "
            "75 % (Q75) o 80 % (Q80) para riego de subsistencia y verificar "
            "con al menos 25 años de serie para incorporar variabilidad "
            "ENSO. Para sistemas con reuso de aguas tratadas se aplica "
            "íntegramente la serie ISO 16075:2020 y la WHO Guidelines for "
            "the Safe Use of Wastewater (2006)."
        ),
    },
    # ─────────────────────────────────────────────────────────────────────
    "hidroelectrico": {
        "titulo": "4. Marco para aprovechamiento hidroeléctrico",
        "introduccion": (
            "Bolivia no cuenta con una norma técnica específica para el "
            "cálculo del caudal mínimo de diseño en aprovechamientos "
            "hidroeléctricos. El estado de la práctica nacional combina la "
            "Ley General del Medio Ambiente (1333), la Ley de Electricidad "
            "(1604), los reglamentos de concesiones (DS 28817) y la "
            "experiencia de ENDE en proyectos emblemáticos como Misicuni, "
            "Ivirizu (San José), Miguillas y Cachuela Esperanza, apoyados "
            "en los marcos regulatorios de Brasil, Chile, Perú, Colombia y "
            "Ecuador, los estándares IEC y los lineamientos de seguridad "
            "ICOLD, IHA, USBR y banca multilateral. Por la sensibilidad "
            "técnica, ambiental y económica del cálculo, se exige precisión "
            "y respaldo documental al máximo nivel."
        ),
        "limites_captacion": [
            ("Bolivia — Ley 1333, Art. 48°",
             "≤ 20 % × Q mín, 5 años (promedio diario)",
             "Umbral nacional para clasificar la captación; sobre el "
             "20 % se exige EEIA categoría 1 ante la Prefectura."),
            ("Bolivia — DS 28817 (Reglamento Ley 2878)",
             "Sin límite específico (Concesión autorizada)",
             "El caudal aprobado se fija en la concesión hidroeléctrica "
             "otorgada por el ente competente."),
            ("Bolivia — Ley 1333, Art. 44°",
             "≤ 33 % × Q river (instantáneo, regulado)",
             "Criterio de uso racional para captaciones reguladas con "
             "vaso de almacenamiento."),
            ("Bolivia — Ley 2066",
             "Sin límite específico (EEIA obligatorio)",
             "La modificatoria de la Ley 2029 exige Estudio de Evaluación "
             "de Impacto Ambiental sin fijar techo de captación."),
            ("UE — Directiva Marco del Agua (WFD 2000/60/CE)",
             "Sostenible + no deterioro + E-flows (33–50 % Q medio bajo)",
             "Referencia comparativa internacional; exige flujos "
             "ambientales en cuencas de aprovechamiento."),
            ("ICOLD",
             "Seguridad de presas + no deterioro ecológico",
             "Boletines técnicos ICOLD para presas > 15 m o vaso > 3 hm³."),
        ],
        "marco_nacional": [
            ("Ley N° 1604 (1994) — Ley de Electricidad",
             "Marco regulatorio general del sector eléctrico boliviano. "
             "Define concesiones y autorizaciones para generación."),
            ("Plan Eléctrico del Estado Plurinacional 2025–2050 (ENDE / "
             "Viceministerio de Electricidad y EER)",
             "Establece el horizonte de generación y la priorización de "
             "proyectos hidroeléctricos."),
            ("Manuales internos de ENDE Corporación",
             "Procedimientos de diseño aplicados en Misicuni (Q firme con "
             "P95 = 95 %), Ivirizu (San José), Miguillas y proyectos en "
             "curso. Referencia documental nacional."),
            ("Estudios de factibilidad de proyectos:",
             "Misicuni (1996/2009), Ivirizu (2016), Cachuela Esperanza "
             "(2008/2014), Río Madera (2008), Carrizal, Banda Azul — "
             "documentos públicos parcialmente disponibles via "
             "transparencia."),
        ],
        "marco_internacional": [
            ("Brasil — ANEEL Resolução Normativa N° 396/2010",
             "Define caudal firme (energía firme) con probabilidad del 95 %. "
             "Referencia para cuencas tropicales sudamericanas."),
            ("Chile — DGA Manual de Cálculo de Caudales (2011)",
             "Procedimientos para caudales de diseño en aprovechamientos "
             "hidroeléctricos. Aplica criterio Q90/Q95."),
            ("Perú — DS N° 009-93-EM (Reglamento Ley Concesiones Eléctricas)",
             "Procedimiento para evaluación de caudales firmes y energía "
             "firme en sistemas interconectados."),
            ("Colombia — UPME Guía para PCH (2014)",
             "Guía oficial para Pequeñas Centrales Hidroeléctricas; "
             "criterio Q95/Q90 según tamaño."),
            ("Ecuador — Regulación ARCONEL 005/14",
             "Determinación de la energía firme con Q90/Q95."),
            ("IEC 61116 (Small hydroelectric installations)",
             "Estándar internacional para pequeñas centrales hidroeléctricas. "
             "Define metodologías de evaluación del recurso."),
            ("IEC 60041 (Field acceptance tests)",
             "Pruebas de aceptación en campo para turbinas hidráulicas, "
             "Pelton, Francis y Kaplan."),
            ("World Bank — Hydroelectric Power: A Guide for Developers and "
             "Investors (2015)",
             "Manual de la banca para evaluación de recursos y riesgos en "
             "aprovechamientos hidroeléctricos."),
            ("IHA — Hydropower Sustainability Standard (2021)",
             "Estándar internacional de sostenibilidad para hidroeléctricas "
             "(reemplaza al HSAP)."),
            ("ESHA — European Small Hydropower Association",
             "Guías técnicas para PCH en Europa, adaptadas en proyectos "
             "menores a 10 MW."),
        ],
        "metodos": [
            ("Caudal firme con probabilidad Q95 (criterio brasileño/peruano)",
             "Caudal disponible el 95 % del tiempo. Es la base más conservadora "
             "para dimensionar energía firme."),
            ("Caudal de diseño Qd (40–60 % del tiempo)",
             "Caudal que optimiza la energía total generada según la curva "
             "de duración."),
            ("Caudal medio anual y curva potencia–caudal",
             "Determina la potencia instalada óptima y el factor de planta "
             "esperado."),
            ("Análisis de sequías hidrológicas plurianuales",
             "Crítico para presas con regulación: garantiza la energía "
             "firme en años hidrológicamente desfavorables."),
            ("Estudio probabilístico Monte-Carlo de generación",
             "Recomendado por la banca multilateral (BID/Banco Mundial) "
             "para proyectos mayores a 50 MW."),
            ("Curva de regulación estacional / interanual",
             "Para embalses con vaso de regulación, traduce la "
             "disponibilidad hidrológica a producción asegurada."),
        ],
        "flujo_tecnico": [
            ("1. Definir sitio + cuenca + caudal aprovechable",
             "Coordenadas del punto, watershed MERIT Hydro 90 m, y "
             "definición del esquema de aprovechamiento (a filo de agua "
             "o con regulación) y el caudal aprovechable preliminar."),
            ("2. Obtener serie histórica de caudales diarios",
             "Aforo SENAMHI / INE-ANDA / ENDE más cercano (< 50 km y "
             "cuenca homologable) o balance modelado CHIRPS·ERA5 sobre la "
             "cuenca delineada cuando no exista aforo válido."),
            ("3. Calcular FDC",
             "Curva de duración: Q90, Q95, Q mínimo de 5 años y Q anual. "
             "Caudal firme Q95 = base conservadora para energía firme; "
             "Q40–Q60 = rango del caudal de diseño según tipo de central."),
            ("4. Verificar umbral Ley 1333 (Art. 48°)",
             "Q captación ≤ 0.20 × Q mín, 5 años (promedio diario). Si "
             "supera, se exige EEIA categoría 1 ante la Prefectura. Para "
             "captaciones reguladas verificar también ≤ 33 % × Q river "
             "instantáneo (Art. 44°)."),
            ("5. Estimar caudal ecológico",
             "Q eco ≈ Q90 o 10 % × Q anual (Ley 071 + lineamientos BM/CAF "
             "+ E-flows 33–50 % Q medio bajo de la WFD UE). Caudal "
             "aprovechable = Q diseño − Q ecológico − pérdidas."),
            ("6. Informe de Q mín para elaborar el EEIA",
             "Estudio de Evaluación de Impacto Ambiental (Ley 2066 + DS "
             "24176). Incluye balance hídrico, caudal ecológico, "
             "afectación a usuarios aguas abajo, plan de monitoreo y "
             "compensaciones. Categoría según envergadura."),
            ("7. Informe de Q mín para construir la obra",
             "Memoria técnica para obra de toma + presa (criterios USBR "
             "y SPANCOLD; ICOLD si > 15 m o vaso > 3 hm³) + conducción "
             "+ casa de máquinas + selección de turbina (Pelton, Francis "
             "o Kaplan según salto y caudal)."),
            ("8. Tests de aceptación según normas internacionales",
             "Pruebas de aceptación en campo conforme a IEC 60041 "
             "(modelos hidráulicos y termodinámicos) e IEC 60193, IEC "
             "60193:2019 + IEC 61116 para pequeñas centrales. "
             "Verificación de eficiencia, cavitación y curvas de "
             "potencia con el caudal certificado."),
        ],
        "parametros_clave": [
            "Q95 — caudal firme (m³/s)",
            "Q90 — caudal de referencia ambiental (m³/s)",
            "Q50 — caudal mediano (m³/s)",
            "Q diseño — entre Q40 y Q60 según tipo (m³/s)",
            "Q mín, 5 años (m³/s) — umbral Ley 1333 Art. 48°",
            "Q captación / Q mín, 5 años (debe ser ≤ 0.20)",
            "Q captación / Q river instantáneo (debe ser ≤ 0.33)",
            "Caudal mínimo ecológico (m³/s, ver bloque ecológico)",
            "Caudal aprovechable: Q diseño − Q ecológico − pérdidas",
            "Salto neto efectivo (m)",
            "Energía firme anual (GWh)",
            "Factor de planta esperado (%)",
        ],
        "consideraciones": (
            "Al no existir normativa boliviana específica, se recomienda "
            "explicitar en la memoria técnica los criterios adoptados de "
            "Brasil (caudal firme P95), Chile (DGA) y Perú (DS 009-93-EM), "
            "alineados con IEC 61116 y los estándares de la IHA. Para la "
            "evaluación de impacto y bankability del proyecto se exige "
            "siempre verificar contra los criterios del Banco Mundial y la "
            "CAF, que financian la mayoría de los proyectos hidroeléctricos "
            "en Bolivia. El caudal ecológico aguas abajo es no negociable "
            "según la Ley 071."
        ),
    },
    # ─────────────────────────────────────────────────────────────────────
    "ecologico": {
        "titulo": "4. Marco para el caudal ecológico mínimo",
        "introduccion": (
            "El caudal ecológico es el agua que debe permanecer en el cauce "
            "para mantener la integridad del ecosistema acuático y las "
            "funciones ambientales del río. La Ley boliviana de Derechos de "
            "la Madre Tierra (071) y la Ley del Medio Ambiente (1333) lo "
            "exigen como condición sine qua non de cualquier aprovechamiento; "
            "los financiadores multilaterales (BM, CAF, BID) lo establecen "
            "como salvaguarda ambiental obligatoria; y la cooperación europea "
            "(GIZ, COSUDE) aporta marcos metodológicos para cuencas andinas. "
            "Existen más de 280 métodos documentados en la literatura "
            "internacional (CAF Guía 2024), agrupados en hidrológicos, "
            "hidráulicos, holísticos y de simulación de hábitat."
        ),
        "limites_captacion": [
            ("Bolivia — DS 28817 (Reglamento Ley 2878)",
             "\"Cantidad que permita la preservación\" (sin número específico)",
             "Concepto cualitativo: el caudal debe ser suficiente para "
             "preservar el ecosistema fuente y los usuarios aguas abajo."),
            ("Bolivia — Ley 1333, Art. 48°",
             "Q eco ≥ 80 % × Q mín (implícito por el límite del 20 %)",
             "Al limitar la captación al 20 % del Q mín 5 años, el caudal "
             "ecológico residual queda implícitamente en al menos el 80 %."),
            ("Chile — DGA / DS 2026",
             "≤ 20 % del Q medio anual (mínimo para preservar la naturaleza)",
             "Norma chilena referencia regional para el caudal ecológico "
             "mínimo permitido en concesiones."),
            ("UE — Directiva Marco del Agua (WFD)",
             "33–50 % del Q medio anual bajo (para río > 1 m³/s)",
             "Estándar comunitario; preserva el «buen estado ecológico» "
             "exigido por la Directiva 2000/60/CE."),
            ("Perú — Reglamento Ley de Recursos Hídricos, Art. 153°",
             "Sin número específico (metodología ANA)",
             "La Autoridad Nacional del Agua define la metodología caso "
             "por caso según tipo de cuerpo de agua y uso."),
            ("CAF — Guía de Caudales Ecológicos (2024)",
             "> 280 métodos documentados (sin número único)",
             "Compendio de la Corporación Andina de Fomento que clasifica "
             "los métodos en hidrológicos, hidráulicos, holísticos y de "
             "simulación de hábitat."),
        ],
        "marco_nacional": [
            ("Ley N° 071 (2010) — Derechos de la Madre Tierra",
             "Reconoce el derecho del agua a mantener su ciclo natural y "
             "exige preservar las funciones ecológicas en cualquier "
             "aprovechamiento."),
            ("Ley N° 300 (2012) — Marco de la Madre Tierra y Desarrollo "
             "Integral para Vivir Bien",
             "Operativiza la Ley 071 con principios y mecanismos de "
             "salvaguarda."),
            ("Ley N° 1333 (1992) — Ley del Medio Ambiente",
             "Marco general de protección ambiental, exige evaluación de "
             "impacto en cualquier obra hidráulica."),
            ("DS N° 24176 (1995) — Reglamento de Gestión Ambiental del "
             "Recurso Hídrico",
             "Define los procedimientos de evaluación de impacto ambiental "
             "y los criterios mínimos para descarga, captación y derivación."),
            ("Reglamento de la Ley de Riego (DS 28817)",
             "Establece que toda captación de riego debe garantizar el "
             "caudal ecológico aguas abajo."),
            ("Plan Plurinacional de Cambio Climático y Vivir Bien",
             "Vincula el caudal ecológico con la resiliencia hídrica de "
             "cuencas estratégicas."),
        ],
        "marco_internacional": [
            ("Banco Mundial — Environmental Flow Assessment Guidelines "
             "(Hirji & Davis, 2009)",
             "Marco técnico oficial para evaluar caudales ambientales en "
             "proyectos financiados por BM."),
            ("Banco Mundial — Marco Ambiental y Social (ESF, 2018)",
             "Estándar Ambiental 6 (ESS6): biodiversidad y servicios "
             "ecosistémicos, incluye caudales ecológicos."),
            ("CAF — Política Ambiental y Social (2021)",
             "Salvaguardas obligatorias para proyectos financiados por la "
             "Corporación Andina de Fomento."),
            ("BID — Política Operativa OP-703 (Política de Medio Ambiente "
             "y Cumplimiento de Salvaguardas)",
             "Directrices ambientales obligatorias para proyectos de "
             "infraestructura hídrica."),
            ("Cooperación Suiza COSUDE — Programa de Cuencas",
             "Proyectos de manejo integrado de cuencas en Bolivia. "
             "Define metodologías de caudal ecológico para cuencas "
             "altoandinas."),
            ("GIZ Alemania — Manejo Integrado de Recursos Hídricos en los "
             "Andes (PROAGUA II)",
             "Lineamientos para integrar caudales ecológicos en planes "
             "directores de cuenca."),
            ("Unión Europea — Directiva Marco del Agua 2000/60/CE",
             "Referencia metodológica internacional para estado ecológico "
             "y caudales ambientales."),
            ("IUCN — Flow: The Essentials of Environmental Flows "
             "(Dyson, Bergkamp & Scanlon, 2003)",
             "Marco conceptual global de caudales ambientales."),
            ("Convención de Ramsar",
             "Para humedales bolivianos (sitios Ramsar: Llanos de Moxos, "
             "Pantanal, Pampas del Yacuma, Bañados del Izozog)."),
        ],
        "metodos": [
            ("Método del 10 % de Q anual (Tennant simplificado)",
             "Q eco = 0.10 × Q medio anual. Uso general y rápido para "
             "evaluaciones preliminares y cuencas sin aforo detallado."),
            ("Método Q90 — FDC ambiental (NGPRP, 1974)",
             "Q eco = Q90 (caudal excedido el 90 % del tiempo). Apropiado "
             "para estiaje, plantas de tratamiento (PTAR) y referencia "
             "regulatoria estándar."),
            ("Método Q85 — seguridad hídrica",
             "Q eco = Q85 (caudal excedido el 85 %). Mayor margen de "
             "seguridad que Q90; recomendado cuando hay alta variabilidad "
             "interanual o ecosistemas sensibles."),
            ("Método UE 33 % Q medio bajo (río < 1 m³/s)",
             "Q eco = 0.33 × Q medio bajo. Aplicación de la Directiva "
             "Marco del Agua para cuerpos de agua menores."),
            ("Método UE 50 % Q medio bajo (río > 1 m³/s)",
             "Q eco = 0.50 × Q medio bajo. Aplicación más conservadora "
             "para ríos principales según la WFD."),
            ("Riesgo medio — Q75 a Q80",
             "Q eco entre Q75 y Q80 según uso humano-ecológico. Balance "
             "entre disponibilidad para el aprovechamiento y preservación "
             "ambiental."),
            ("Tennant / Montana (1976)",
             "10 % mínimo aceptable, 30 % bueno, 60 % excelente. Método "
             "rápido para evaluaciones preliminares en cuencas templadas."),
            ("Tessman (1980)",
             "Caudal mínimo mensual: 40 % del caudal medio mensual cuando "
             "Qmes < Qanual; el menor entre 40 % del Qanual y Qmes en "
             "otro caso. Captura variabilidad estacional."),
            ("Tasa de recesión",
             "Basado en la curva de recesión natural del hidrograma. "
             "Estima el caudal base sostenido durante el estiaje."),
            ("Flujo dinámico (20 % del flujo actual)",
             "Considera migración de peces, transporte de sedimentos y "
             "variabilidad temporal. Apropiado para ecosistemas dinámicos."),
            ("Distribución Weibull de mínimos",
             "Análisis estadístico de la cola inferior de la distribución "
             "de caudales. Estima percentiles bajos con incertidumbre."),
            ("Smakhtin et al. (2004)",
             "Combina FDC con la curva de duración del caudal base; útil "
             "para cuencas con sequías marcadas."),
            ("IFIM — Instream Flow Incremental Methodology (Bovee, 1982)",
             "Análisis hábitat-caudal basado en especies indicadoras. "
             "Recomendado por la IUCN para estudios detallados."),
            ("BBM — Building Block Methodology (King & Louw, 1998)",
             "Caudal ambiental holístico construido en bloques "
             "estacionales. Estándar sudafricano adoptado por el BM."),
            ("DRIFT — Downstream Response to Imposed Flow Transformations "
             "(King et al., 2003)",
             "Enfoque holístico que incluye dimensión social. Recomendado "
             "por la banca multilateral para grandes proyectos."),
        ],
        "flujo_tecnico": [
            ("1. Definir sitio + cuenca + objetivo del análisis",
             "Coordenadas del punto, watershed MERIT Hydro 90 m, "
             "identificación del uso aguas arriba que motiva el "
             "requerimiento del caudal ecológico (riego, hidroeléctrica, "
             "captación, presa)."),
            ("2. Obtener serie histórica de caudales diarios",
             "Aforo SENAMHI / INE-ANDA / SEDERI más cercano (< 50 km) o "
             "balance modelado CHIRPS·ERA5 sobre la cuenca delineada."),
            ("3. Calcular curva de duración (FDC)",
             "Q50, Q75, Q85, Q90, Q95 y demás percentiles. Base de los "
             "métodos hidrológicos clásicos de caudal ecológico."),
            ("4. Calcular Q mín, 5 años (probabilidad de excedencia 80 %)",
             "Caudal mínimo medio diario con período de retorno 5 años. "
             "Umbral de referencia para la verificación de la Ley 1333."),
            ("5. Estimar el caudal ecológico por múltiples métodos",
             "Aplicar al menos cuatro métodos: Q eco = 10 % Q anual "
             "(rápido), Q eco = Q90 (FDC), Q eco = Q85 (seguridad), "
             "Q eco = 33–50 % Q medio bajo (UE, según tamaño del río). "
             "Reportar la dispersión entre métodos."),
            ("6. Verificar disponibilidad: Q captación ≤ Q available − Q eco",
             "Q available = Q mín, 5 años; Q captación máx ≤ 0.80 × Q mín "
             "5 años (por límite del 20 % de la Ley 1333); Q eco implícito "
             "= 0.20 × Q mín 5 años (residual ambiental garantizado)."),
            ("7. Verificar máxima captación por Ley 1333",
             "Q captación ≤ 0.20 × Q mín, 5 años (promedio diario, "
             "Art. 48°). Si supera, se exige EEIA categoría 1 ante la "
             "Prefectura departamental."),
            ("8. Verificar caudal ecológico residual",
             "Q residual = Q river − Q captación ≥ Q eco. Este es el "
             "criterio operativo no negociable: cualquier escenario debe "
             "garantizar el caudal ecológico aguas abajo."),
            ("9. Calcular demanda hídrica del cultivo / del uso (m³/ha)",
             "Para riego: balance Penman-Monteith × Kc − P efectiva. "
             "Para captación urbana: dotación NB 688 × población "
             "proyectada. Para hidroeléctrica: Q diseño según curva "
             "potencia-caudal."),
            ("10. Verificación triple",
             "(a) Q demanda ≤ Q captación disponible; (b) Q residual "
             "≥ Q eco; (c) calidad de agua FAO 2023 (CE, SAR, pH, metales) "
             "compatible con el uso final."),
            ("11. Determinar tipo de derecho ante el SENARI",
             "Registro (comunidad indígena o campesina con uso "
             "tradicional) o Autorización (persona natural/jurídica con "
             "uso tecnificado). Documenta caudal asignado, prelación y "
             "obligaciones."),
            ("12. Informe para elaborar el proyecto técnico",
             "Memoria técnica con la obra de toma, aducción, distribución "
             "y operación. Incluye los criterios USBR/SPANCOLD/ICOLD "
             "cuando aplique a presas o grandes obras."),
            ("13. Informe para complementar el EEIA ante la Prefectura",
             "Documento técnico-ambiental que sustenta la Licencia "
             "Ambiental (RASIM) bajo la Ley 1333. Incluye el balance "
             "hídrico, los métodos de caudal ecológico aplicados y el "
             "plan de monitoreo."),
            ("14. Metodología para reportar caudal ecológico mensual",
             "Define el cronograma de medición y reporte mensual al "
             "SENARI/SEDERI/AAPS. Especifica el método adoptado, los "
             "umbrales de alerta (Q ecológico mensual histórico, P10 a "
             "P90) y las acciones correctivas ante incumplimiento."),
        ],
        "parametros_clave": [
            "Q anual medio (m³/s)",
            "Q medio bajo (m³/s) — referencia UE",
            "Q mín, 5 años (m³/s) — umbral Ley 1333",
            "Q50, Q75, Q85, Q90, Q95 de la FDC (m³/s)",
            "Q ecológico — 10 % Q anual (método rápido)",
            "Q ecológico — Q90 (FDC ambiental)",
            "Q ecológico — Q85 (seguridad hídrica)",
            "Q ecológico — 33–50 % Q medio bajo (UE)",
            "Q ecológico — Tennant 30 % (cooperación europea)",
            "Q ecológico — Tessman mensual (12 valores)",
            "Q captación máxima permitida = 0.80 × Q mín, 5 años",
            "Q ecológico implícito = 0.20 × Q mín, 5 años",
            "Q residual = Q river − Q captación (debe ≥ Q eco)",
            "Régimen mensual: percentiles P10–P90",
            "Caudal de pulso ecológico requerido (eventos)",
        ],
        "consideraciones": (
            "El caudal ecológico es de cumplimiento obligatorio en "
            "cualquier aprovechamiento aguas arriba (captación, presa, "
            "derivación, central hidroeléctrica) y debe reportarse con al "
            "menos cuatro métodos para evidenciar la dispersión entre "
            "enfoques. Para cuencas altoandinas el método Tennant 30 % es "
            "el estándar de la cooperación europea (GIZ, COSUDE); el "
            "Banco Mundial requiere análisis holístico (BBM o DRIFT) para "
            "proyectos mayores a 50 MW o presas con vaso > 10 hm³; la "
            "CAF (Guía 2024) acepta el uso combinado de varios métodos "
            "del compendio de >280 documentados. Para cuencas con "
            "humedales Ramsar aguas abajo (Llanos de Moxos, Pantanal, "
            "Pampas del Yacuma, Bañados del Izozog) la Convención exige "
            "preservar las funciones del humedal mediante caudales de "
            "pulso que reproduzcan el régimen estacional. La verificación "
            "operativa es triple: Q demanda ≤ Q disponible, Q residual "
            "≥ Q eco, y calidad de agua compatible con el uso final."
        ),
    },
    # ─────────────────────────────────────────────────────────────────────
    "investigacion_cientifica": {
        "titulo": "4. Marco para análisis científico (cambio climático, "
                  "sequías e investigación)",
        "introduccion": (
            "El análisis con fines de investigación científica articula "
            "tres marcos: el reglamentario nacional para la presentación "
            "y ejecución de proyectos científicos (Reglamento AACN para "
            "biodiversidad, reglamentos universitarios UCB / UPDS / "
            "UAGRM-ICU), los compromisos internacionales con la "
            "comunidad científica global (UNESCO Recomendación de "
            "Ciencia Abierta 2021, IPCC AR6, WMO, CMIP6) y la "
            "metodología científica clásica aplicada al riesgo hídrico "
            "y a las sequías. El foco temático prioritario es cuantificar "
            "el riesgo de sequías y proyectar la disponibilidad hídrica "
            "bajo diferentes escenarios climáticos, comparando los "
            "resultados con estudios en otras cuencas andinas y europeas "
            "para establecer correspondencias regionales."
        ),
        "limites_titulo": "Límites y vigencia de proyectos de investigación",
        "limites_captacion": [
            ("Bolivia — AACN (Autoridad Administrativa en Biodiversidad)",
             "Vigencia 5 años máx · intransferible · indelegable",
             "Proyectos sobre diversidad biológica. La aprobación otorga "
             "derecho de investigación en el territorio nacional."),
            ("Bolivia — Plazo administrativo AACN",
             "15 días hábiles para aprobación",
             "Desde la presentación oficial, siempre que no haya "
             "observaciones insubsanables."),
            ("Bolivia — Sistema Universitario",
             "Vigencia anual (Plan de Investigación Anual)",
             "Proyectos seleccionados del Banco de Proyectos universitario "
             "(UCB, UPDS, UAGRM-ICU y otros)."),
            ("UNESCO — Recomendación Ciencia Abierta (2021)",
             "Reporte cada 4 años a la UNESCO",
             "Obligación de los Estados miembros de informar progresos "
             "en la implementación."),
            ("Ética — Investigación con seres humanos",
             "Variable según protocolo",
             "Aprobación por Comité de Ética Institucional independiente "
             "del equipo investigador."),
            ("Ciencia Abierta — Publicación",
             "Acceso abierto inmediato",
             "Publicaciones, datos, protocolos, código y software deben "
             "estar disponibles bajo licencia abierta (UNESCO 2021)."),
        ],
        "marco_nacional": [
            ("Reglamento de Investigación Científica en Diversidad "
             "Biológica (RM 026/2009)",
             "Regula la presentación y ejecución de proyectos de "
             "investigación sobre biodiversidad en Bolivia. La AACN "
             "(Autoridad Administrativa en Biodiversidad) aprueba los "
             "proyectos en 15 días hábiles, con vigencia de 5 años, "
             "intransferible e indelegable. Solo las ICA (Instituciones "
             "de Investigación Científica) reconocidas pueden presentar "
             "proyectos."),
            ("Reglamento de Investigación — UCB (Universidad Católica "
             "Boliviana San Pablo)",
             "Producción científica generada según normativa vigente UCB, "
             "leyes nacionales e internacionales. Aplica a los Institutos "
             "de Investigación de la UCB."),
            ("Reglamento de Investigación — UPDS (Universidad Privada "
             "Domingo Savio, 2025)",
             "Establece naturaleza y desarrollo de la investigación "
             "científica universitaria: Banco de Proyectos, Plan de "
             "Investigación Anual, líneas de investigación, equipo "
             "(docentes + estudiantes + externos), Jefe de Proyecto y "
             "fuentes de recursos (propios, contrapartes, concursos "
             "públicos, donaciones)."),
            ("Reglamento General de Investigación ICU — UAGRM "
             "(Res. ICU 019/2025 + Líneas Vicerrectoral 052/2025)",
             "Marco normativo de la Universidad Autónoma Gabriel René "
             "Moreno para la creación, organización y funcionamiento de "
             "unidades de investigación."),
            ("Proyecto de Ley para el Fortalecimiento del Sistema "
             "Universitario (PL 283/2024-2025)",
             "Iniciativa para fortalecer la investigación científica y "
             "tecnológica en el sistema universitario boliviano."),
            ("Plan Plurinacional de Cambio Climático para Vivir Bien "
             "(2017–2030, MMAyA)",
             "Define las prioridades de investigación climática nacional, "
             "incluida la cuantificación del riesgo de sequías."),
            ("Estrategia Nacional de Implementación del Acuerdo de París "
             "(2016)",
             "Marco para los compromisos NDC de Bolivia ante la CMNUCC."),
            ("Atlas de Cambio Climático para Bolivia (MMAyA, 2010)",
             "Proyecciones nacionales de P y T a 2030/2050/2080."),
            ("Comunicaciones Nacionales a la CMNUCC (1.ª, 2.ª y 3.ª)",
             "Inventarios y proyecciones oficiales bolivianas."),
            ("PRECIS-IBHI / PIDAASSA — IHH-UMSA",
             "Proyectos del Instituto de Hidráulica e Hidrología de la "
             "UMSA con downscaling regional para Bolivia."),
            ("Estudios del CASA-UMSS (Cochabamba) sobre cuencas andinas",
             "Tesis e investigaciones sobre régimen de caudales en cuencas "
             "del valle alto y la cordillera Tunari."),
            ("Investigaciones del LH-UMSA (La Paz)",
             "Estudios de glaciares y caudales en la Cordillera Real."),
        ],
        "marco_internacional": [
            # ----- UNESCO: Ciencia Abierta -----
            ("UNESCO — Recomendación sobre Ciencia Abierta (23-nov-2021)",
             "Adoptada por los 193 países de la Conferencia General. "
             "Define la ciencia abierta como constructo inclusivo de "
             "movimientos y prácticas para hacer el conocimiento "
             "científico abiertamente disponible, accesible y reutilizable, "
             "incrementando colaboraciones y abriendo los procesos a la "
             "sociedad."),
            ("UNESCO — Kit de Herramientas de Ciencia Abierta (oct-2023)",
             "Disponible en castellano, inglés y francés. Apoya a los "
             "Estados en la implementación mediante políticas públicas, "
             "construcción de capacidades, infraestructura y "
             "financiación."),
            ("UNESCO — 4 Pilares de la Ciencia Abierta",
             "(1) Conocimiento científico abierto (publicaciones, datos, "
             "protocolos, código, software); (2) Infraestructuras de "
             "ciencia abierta (plataformas no comerciales); (3) "
             "Participación abierta de agentes sociales (ciencia "
             "ciudadana); (4) Diálogo abierto con otros sistemas de "
             "conocimiento (saberes tradicionales e indígenas)."),
            ("UNESCO — 7 Áreas de Acción Prioritaria",
             "(1) Definición común; (2) Entorno normativo; "
             "(3) Infraestructuras; (4) Formación y alfabetización "
             "digital; (5) Cultura e incentivos armonizados; "
             "(6) Enfoques innovadores por etapa del proceso científico; "
             "(7) Cooperación internacional y reducción de brechas."),
            ("UNESCO — Principios de Ciencia Abierta",
             "Bibliodiversidad, multilingüismo, modelos no comerciales, "
             "infraestructuras compartidas, incentivos armonizados, "
             "evaluación con indicadores no bibliométricos, alineación con "
             "la Declaración de San Francisco DORA (calidad sobre "
             "cantidad)."),
            ("CIOMS / WHO — Pautas Éticas Internacionales para la "
             "Investigación Biomédica en Seres Humanos (2016)",
             "Estándar internacional para protocolos con seres humanos. "
             "Aplicable a investigación hidrológica vinculada a "
             "comunidades (encuestas, percepción, talleres)."),
            ("Declaración de Helsinki (AMM, revisión 2024)",
             "Principios éticos universales para la investigación con "
             "seres humanos."),
            ("Convenio sobre la Diversidad Biológica (CBD, Río 1992) + "
             "Protocolo de Nagoya (2010)",
             "Acceso a recursos genéticos y reparto de beneficios. "
             "Aplicable a investigación en cuencas con flora y fauna "
             "acuática."),
            # ----- Clima y cambio climático -----
            ("IPCC AR6 — Working Groups I, II y III (2021–2023)",
             "Estado del arte global. Capítulos sobre Sudamérica (12) y "
             "sistemas hídricos (4). Incluye anexos regionales."),
            ("IPCC Atlas Interactivo",
             "Proyecciones espaciales de CMIP6 con cobertura para Bolivia "
             "y los Andes tropicales."),
            ("WMO State of the Global Climate (anual)",
             "Reporte anual de la Organización Meteorológica Mundial."),
            ("WCRP CMIP6",
             "Coupled Model Intercomparison Project, fase 6. Base de "
             "modelos GCM y SSPs."),
            ("NASA NEX-GDDP-CMIP6",
             "Downscaling estadístico a 25 km para 35 GCM y 4 escenarios "
             "SSP. Listo para usar en GEE."),
            ("CORDEX-SAM",
             "Coordinated Regional Climate Downscaling Experiment para "
             "Sudamérica. Modelos regionales RCA4, REMO, Eta a 50 km."),
            ("CRU TS y ERA5",
             "Reanálisis climático global de referencia (1901–presente y "
             "1940–presente respectivamente)."),
            ("WMO Drought Indicators Handbook (2016, WMO-1173)",
             "Guía oficial OMM para el cálculo de SPI, SPEI, PDSI y otros "
             "índices."),
            ("CIIFEN — Centro Internacional para Investigación del "
             "Fenómeno El Niño",
             "Pronósticos y análisis ENSO para la región andina."),
            ("CRRH SICA — Comité Regional de Recursos Hídricos",
             "Coordinación de la investigación hídrica en América Latina "
             "y el Caribe."),
            ("EU JRC — European Drought Observatory (EDO)",
             "Sistema europeo de monitoreo de sequías. Metodologías "
             "exportables a Bolivia."),
            ("EU Copernicus Climate Change Service (C3S)",
             "Datos y servicios climáticos globales libres."),
            ("LPDAAC / NSIDC / GLEAM",
             "Datasets de evapotranspiración, humedad de suelo, balance "
             "hídrico global."),
            ("UN Sendai Framework for Disaster Risk Reduction (2015–2030)",
             "Marco global de reducción del riesgo de desastres "
             "(sequías incluidas)."),
        ],
        "metodos": [
            ("SPI — Standardized Precipitation Index (McKee et al., 1993)",
             "Índice estandarizado de precipitación a 1, 3, 6, 12, 24 "
             "meses. Estándar OMM para sequía meteorológica."),
            ("SPEI — Standardized Precipitation-Evapotranspiration Index "
             "(Vicente-Serrano et al., 2010)",
             "Incorpora la temperatura via ET₀. Recomendado para "
             "evaluaciones de cambio climático."),
            ("PDSI — Palmer Drought Severity Index (Palmer, 1965)",
             "Índice clásico de sequía meteorológica e hidrológica."),
            ("RDI — Reconnaissance Drought Index (Tsakiris et al., 2007)",
             "Variante de SPEI con menores requisitos de datos."),
            ("Análisis de cambio climático con ensemble CMIP6",
             "Estadística multi-modelo (mediana, percentiles, IQR) sobre "
             "los 35 GCM de NEX-GDDP para los escenarios SSP."),
            ("Análisis de tendencia con Mann-Kendall + Sen",
             "Detección y cuantificación de tendencias en series "
             "históricas y proyectadas."),
            ("Análisis bivariado caudal-déficit (copulas)",
             "Para riesgo de sequía hidrológica con dependencia entre "
             "variables (Salvadori & De Michele, 2010)."),
            ("Bias correction de proyecciones (quantile mapping)",
             "Corrección de sesgo de los GCM con datos observados "
             "SENAMHI antes del análisis de riesgo."),
            ("Modelos hidrológicos forzados (HBV, GR4J, SWAT)",
             "Forzados con la lluvia y temperatura proyectada para "
             "evaluar el cambio en caudales mínimos."),
            ("Método científico clásico (observación → publicación)",
             "Ciclo metodológico aplicado al análisis hidrológico: "
             "observar (identificar el fenómeno), formular pregunta (qué, "
             "quién, cómo, por qué, dónde, cuándo), construir hipótesis "
             "(variable independiente + dependiente, comprobable), "
             "experimentar, analizar y comunicar."),
            ("Ciencia ciudadana / participativa",
             "Involucra a comunidades locales (regantes, comités de agua) "
             "en el monitoreo y validación de datos. Recomendado por "
             "UNESCO 2021 (Pilar 3)."),
        ],
        "flujo_tecnico": [
            ("1. Observar el fenómeno e identificar el tema",
             "Define el problema hidrológico que se quiere investigar "
             "(régimen del Q mínimo, sequías, cambio climático en la "
             "cuenca seleccionada)."),
            ("2. Formular la pregunta de investigación",
             "¿Qué? ¿Quién? ¿Cómo? ¿Por qué? ¿Dónde? ¿Cuándo? — Acotar "
             "espacial y temporalmente la pregunta."),
            ("3. Construir hipótesis comprobable",
             "Hipótesis = Variable Independiente + Variable Dependiente. "
             "Ejemplo: «Si Q eco = 10 % Q anual, entonces conservación de "
             "biodiversidad acuática ≥ 80 %.»"),
            ("4. Seleccionar el método de investigación",
             "Combina deductivo (de la teoría a los datos) e inductivo "
             "(de los datos a la teoría) según el alcance."),
            ("5. Preparar la investigación de campo",
             "Definir protocolos de medición, instrumentos, plan "
             "estadístico, salvaguardas éticas (CIOMS / Declaración de "
             "Helsinki si aplica)."),
            ("6. Verificar si la investigación involucra biodiversidad",
             "SÍ → ruta AACN (Reglamento RM 026/2009). NO → ruta general "
             "universitaria (UCB / UPDS / UAGRM-ICU / Banco de Proyectos)."),
            ("7-A. Ruta AACN (biodiversidad)",
             "Obtener reconocimiento como ICA, presentar proyecto a la "
             "AACN, revisión técnica y jurídica (15 días hábiles), "
             "aprobación (vigencia 5 años, intransferible) y ejecución "
             "en territorio nacional."),
            ("7-B. Ruta general (universitaria)",
             "Presentar perfil al Banco de Proyectos, selección para el "
             "Plan Anual, conformar equipo (docentes + estudiantes + "
             "externos), designar Jefe de Proyecto, acreditar recursos "
             "(propios / concursados / donaciones), ejecutar."),
            ("8. Recolección de información",
             "Trabajo de campo, descarga satelital (CHIRPS, ERA5, NEX-GDDP, "
             "CORDEX-SAM), consultas SENAMHI / INE-ANDA, encuestas "
             "comunitarias. Aplicar ética científica y consentimiento "
             "informado."),
            ("9. Análisis de la información",
             "Depurar datos, validar con fuentes originales, aplicar SPI, "
             "SPEI, PDSI, Mann-Kendall, ensemble CMIP6, modelos "
             "hidrológicos forzados, bias correction."),
            ("10. Redacción de resultados",
             "Informe técnico + artículo científico con estructura IMRyD "
             "(Introducción, Métodos, Resultados, Discusión) y referencias "
             "actualizadas."),
            ("11. Publicación científica",
             "Revistas indexadas (Scopus, WoS), conferencias, repositorios "
             "institucionales y nacionales."),
            ("12. Aplicación de Ciencia Abierta (UNESCO 2021)",
             "Publicación en acceso abierto, compartir datos en "
             "repositorios FAIR, código y protocolos abiertos, usar "
             "infraestructuras no comerciales, involucrar agentes "
             "sociales (Pilar 3) y reportar progresos cada 4 años a la "
             "UNESCO."),
            ("13. Evaluación de impacto",
             "Indicadores no exclusivamente bibliométricos (DORA): "
             "transferencia tecnológica, uso por políticas públicas, "
             "adopción comunitaria, alimentación de sistemas regionales "
             "(CRRH SICA, CIIFEN, EU JRC)."),
            ("14. Comparación regional y socialización",
             "Comparar con estudios análogos en cuencas andinas (Mantaro, "
             "Rímac, Paute, Aconcagua, Maipo) y europeas (Pirineos, "
             "Alpes), publicar bajo licencia abierta y socializar con "
             "las comunidades de la cuenca."),
        ],
        "parametros_clave": [
            "Tendencia histórica de Q mínimos (Mann-Kendall, Sen)",
            "SPI-1, SPI-3, SPI-6, SPI-12 (índice estandarizado)",
            "SPEI-3, SPEI-12 (con evapotranspiración)",
            "Frecuencia de eventos de sequía SPI < −1.5 por década",
            "Duración promedio y máxima de sequía hidrológica",
            "Cambio proyectado en Q mínimo medio anual (% vs 1991–2020)",
            "Cambio proyectado en frecuencia de sequía hidrológica",
            "Incertidumbre del ensemble (IQR de los 35 GCM)",
            "Período de retorno actual y futuro de Q7,10",
            "Variable independiente y dependiente de la hipótesis",
            "Tipo de proyecto: AACN (biodiversidad) o universitario",
            "Vigencia de aprobación del proyecto (≤ 5 años AACN)",
            "Cumplimiento de Ciencia Abierta (4 pilares UNESCO)",
            "Indicadores de impacto no bibliométrico (DORA)",
        ],
        "consideraciones": (
            "Para la investigación científica se recomienda reportar SIEMPRE "
            "la incertidumbre del ensemble (no solo la mediana) y comparar "
            "explícitamente con estudios análogos en cuencas andinas "
            "(Perú: Mantaro, Rímac; Ecuador: Paute; Chile: Aconcagua, Maipo) "
            "y europeas en climas similares (Pirineos, Alpes Centrales). La "
            "cooperación entre Bolivia y la Unión Europea (programa EUROCLIMA+) "
            "ofrece datos y metodologías comparables. Para investigaciones "
            "sobre biodiversidad acuática es obligatoria la autorización "
            "previa de la AACN (vigencia 5 años, intransferible, plazo de "
            "aprobación 15 días hábiles) según el Reglamento RM 026/2009. "
            "Los proyectos universitarios siguen las normativas internas "
            "(UCB, UPDS, UAGRM-ICU) con su Banco de Proyectos y Plan Anual. "
            "Los resultados deben publicarse bajo licencia abierta "
            "conforme a la Recomendación UNESCO 2021 (4 pilares: "
            "conocimiento, infraestructuras, participación, diálogo) para "
            "alimentar el sistema de "
            "alerta temprana de sequías regional (CRRH SICA, CIIFEN)."
        ),
    },
}


def obtener_marco(uso: str) -> dict:
    """Devuelve el marco normativo correspondiente al uso, con fallback."""
    return MARCOS.get(uso, MARCOS["investigacion_cientifica"])
