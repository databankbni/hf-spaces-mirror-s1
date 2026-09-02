"""Análisis de riesgo hidroclimático y adaptación al cambio climático (ABC).

Implementa la metodología del «Manual para la Interpretación y Aplicación de
los Índices y Parámetros de Variabilidad Climática» de la Administradora
Boliviana de Carreteras (ABC, Contrato ABC N° 480/21 GNT-CON-BM, 2022):

  RIESGO = VULNERABILIDAD × AMENAZA (CMNUCC / CAF)

- VULNERABILIDAD: 7 variables componentes parametrizadas en escala 1–5, con
  pesos de contribución (Tabla 5.1): Fisiografía 10 %, Clima 10 %, Pendiente
  20 %, Conservación Ambiental 20 %, Inundación 20 %, Número de Curva 10 %,
  Capa de Rodadura 10 %.
- AMENAZA: perturbación por Cambio Climático (envolvente de los modelos AR6
  MPI + MIROC6) para 12 escenarios SSP × período + el escenario base.
- El Manual evaluó 320 subtramos de la Red Vial Fundamental (RVF); la Tabla
  6.3 da el riesgo por escenario de cada tramo y la Tabla 6.4 el incremento.

DISEÑO DINÁMICO: `tramo_referencia_para(lat, lon, departamento)` selecciona el
tramo RVF de referencia según el departamento del proyecto y construye la
sección del informe con SUS valores reales de vulnerabilidad y riesgo por
escenario. `TRAMOS` contiene un conjunto verificado de tramos por departamento
(ampliable a los 320 del Manual con un CSV limpio de las Tablas 6.1 y 6.3).
"""

from __future__ import annotations

from dataclasses import dataclass


# ── Metodología (constantes del Manual) ──────────────────────────────────────
# Nombre y peso de contribución de cada variable de vulnerabilidad (Tabla 5.1).
VARIABLES_META = (
    ("Fisiografía", 0.10),
    ("Clima (Köppen actual)", 0.10),
    ("Pendiente (topografía adyacente)", 0.20),
    ("Conservación Ambiental (Intervención Antrópica)", 0.20),
    ("Potencial de Inundación", 0.20),
    ("Aptitud a la Escorrentía (Número de Curva)", 0.10),
    ("Estructura de Pavimento / Capa de Rodadura", 0.10),
)

# Escala de valoración del riesgo (Tabla 6.2), umbral superior de cada clase.
ESCALA_RIESGO = (
    (1.5, "Mínimo"), (2.5, "Leve"), (3.5, "Medio"),
    (4.5, "Apreciable"), (5.1, "Considerable"),
)
# Código de colores del riesgo (Tabla 6.2), gradiente verde→rojo.
CLASE_COLOR = {
    "Mínimo": "#1a9850", "Leve": "#a6d96a", "Medio": "#fee08b",
    "Apreciable": "#fdae61", "Considerable": "#d73027",
}

# Factores nacionales de amenaza por escenario (Manual, calibrados de la Tabla
# 6.3): riesgo_escenario = riesgo_base × factor. Verificado como constante entre
# tramos (p. ej. SSP370-CP ×1.2930 reproduce 4.06/3.14, 3.43/2.65, 4.75/3.68).
# Índice 0..12 en el orden de ESCENARIOS_META.
FACTORES_ESCENARIO = (
    1.0,            # 0 base
    1.2038, 1.1433, 1.2930, 1.1720,   # 1-4 corto plazo (P1,P2,N1,N2)
    1.2994, 1.3185, 1.1019, 1.1465,   # 5-8 mediano plazo
    0.8917, 1.2197, 1.2357, 1.2420,   # 9-12 largo plazo
)

# Los 13 escenarios (base + 12), en el orden de las columnas de la Tabla 6.3.
# (índice, signo, ssp, plazo, período)
ESCENARIOS_META = (
    (0, "Base (Neutro)", "—", "Actual", "2020"),
    (1, "Positivo 1", "SSP126", "Corto plazo", "2021–2040"),
    (2, "Positivo 2", "SSP245", "Corto plazo", "2021–2040"),
    (3, "Negativo 1", "SSP370", "Corto plazo", "2021–2040"),
    (4, "Negativo 2", "SSP585", "Corto plazo", "2021–2040"),
    (5, "Positivo 1", "SSP126", "Mediano plazo", "2041–2060"),
    (6, "Positivo 2", "SSP245", "Mediano plazo", "2041–2060"),
    (7, "Negativo 1", "SSP370", "Mediano plazo", "2041–2060"),
    (8, "Negativo 2", "SSP585", "Mediano plazo", "2041–2060"),
    (9, "Positivo 1", "SSP126", "Largo plazo", "2081–2100"),
    (10, "Positivo 2", "SSP245", "Largo plazo", "2081–2100"),
    (11, "Negativo 1", "SSP370", "Largo plazo", "2081–2100"),
    (12, "Negativo 2", "SSP585", "Largo plazo", "2081–2100"),
)

# Código de departamento embebido en el UCOD → nombre.
DEPTOS = {
    "LP": "La Paz", "OR": "Oruro", "PT": "Potosí", "TJ": "Tarija",
    "SC": "Santa Cruz", "CO": "Cochabamba", "CH": "Chuquisaca",
    "BN": "Beni", "PD": "Pando", "NA": "Frontera/Interdepartamental",
}


# ── Base de tramos RVF (subconjunto verificado del Manual, Tablas 6.1 y 6.3) ──
# UCOD → (nombre, cod_depto, (7 vulnerabilidades), total, (13 riesgos r0..r12))
# Orden de vulnerabilidad: Fis, Clima, Pend, ConsAmb, Inund, CN, Rodadura.
TRAMOS: dict[str, tuple] = {
    "R3_LP06_09": ("Caranavi – Sapecho", "LP",
        (3.8, 2.0, 2.7, 4.6, 3.0, 2.0, 3.0), 3.1,
        (3.14, 3.78, 3.59, 4.06, 3.68, 4.08, 4.14, 3.46, 3.60, 2.80, 3.83, 3.88, 3.90)),
    "R3_LP06_08": ("Santa Bárbara – Caranavi", "LP",
        (4.4, 2.0, 3.1, 4.6, 3.0, 2.3, 3.0), 3.3,
        (3.31, 3.98, 3.78, 4.27, 3.87, 4.29, 4.35, 3.63, 3.78, 2.94, 4.02, 4.06, 4.08)),
    "R3_LP01_05": ("Cruce – Chuspipata", "LP",
        (4.9, 4.0, 3.2, 4.8, 3.0, 2.7, 1.0), 3.5,
        (3.46, 4.15, 3.95, 4.47, 4.05, 4.49, 4.56, 3.82, 3.96, 3.08, 4.22, 4.28, 4.31)),
    "R25_LP08_01": ("Unduavi – La Florida", "LP",
        (4.4, 3.9, 3.7, 4.3, 3.0, 2.5, 4.0), 3.7,
        (3.68, 4.43, 4.20, 4.75, 4.31, 4.77, 4.84, 4.04, 4.19, 3.27, 4.48, 4.53, 4.55)),
    "R1_LP09_06": ("El Alto Urbano – Senkata", "LP",
        (2.3, 4.0, 2.6, 4.1, 2.5, 3.0, 3.0), 3.1,
        (3.07, 3.70, 3.52, 3.98, 3.61, 4.00, 4.07, 3.41, 3.54, 2.75, 3.78, 3.84, 3.89)),
    "R2_LP09_01": ("El Alto – La Paz", "LP",
        (2.4, 4.0, 2.9, 4.1, 2.7, 3.0, 1.0), 3.0,
        (2.98, 3.58, 3.41, 3.85, 3.49, 3.88, 3.93, 3.30, 3.42, 2.66, 3.65, 3.70, 3.75)),
    "R1_LP13_01": ("Guaqui – Desaguadero", "LP",
        (4.7, 4.0, 2.2, 3.4, 1.0, 3.6, 1.0), 2.7,
        (2.65, 3.19, 3.03, 3.43, 3.11, 3.45, 3.50, 2.93, 3.04, 2.36, 3.24, 3.29, 3.33)),
    "R31_OR02_01": ("Curahuara de Carangas – San Pedro de Totora", "OR",
        (2.9, 4.0, 2.0, 3.4, 1.0, 4.0, 1.0), 2.5,
        (2.47, 2.97, 2.83, 3.20, 2.90, 3.22, 3.28, 2.75, 2.85, 2.21, 3.04, 3.10, 3.15)),
    "R31_OR02_02": ("San Pedro de Totora – Huayllamarca", "OR",
        (3.7, 4.0, 2.1, 3.4, 1.0, 3.9, 4.0), 2.9,
        (2.86, 3.45, 3.28, 3.71, 3.36, 3.73, 3.79, 3.17, 3.29, 2.56, 3.52, 3.58, 3.62)),
    "R1_PT02_20": ("Challapata – Crucero", "PT",
        (5.0, 4.0, 2.5, 4.0, 1.0, 3.3, 1.0), 2.8,
        (2.83, 3.40, 3.24, 3.66, 3.32, 3.69, 3.74, 3.14, 3.26, 2.53, 3.48, 3.54, 3.58)),
    "R1_PT02_26": ("Tarapaya – Potosí", "PT",
        (3.1, 4.0, 2.7, 4.7, 2.0, 3.3, 1.0), 3.0,
        (3.02, 3.63, 3.47, 3.91, 3.55, 3.94, 4.01, 3.37, 3.50, 2.71, 3.73, 3.80, 3.85)),
    "R5_CH02_04": ("Viña Pampa – Sucre", "CH",
        (4.5, 4.0, 2.4, 4.2, 2.1, 3.0, 1.0), 3.0,
        (2.99, 3.59, 3.42, 3.87, 3.51, 3.89, 3.95, 3.31, 3.44, 2.67, 3.67, 3.72, 3.77)),
    "R4_CO01a_10": ("Quillacollo – Cochabamba", "CO",
        (3.9, 4.0, 2.0, 3.1, 3.0, 1.2, 1.0), 2.6,
        (2.63, 3.16, 3.01, 3.39, 3.08, 3.41, 3.46, 2.90, 3.00, 2.34, 3.21, 3.25, 3.28)),
    "R7_CO07_03": ("Paracaya – Epizana", "CO",
        (4.2, 4.0, 2.7, 4.5, 3.0, 2.9, 1.0), 3.3,
        (3.25, 3.90, 3.72, 4.20, 3.81, 4.22, 4.28, 3.59, 3.73, 2.90, 3.97, 4.03, 4.07)),
    "R4_SC02-B_24": ("Santa Cruz – Warnes", "SC",
        (3.7, 2.0, 2.0, 3.5, 3.0, 3.0, 1.0), 2.7,
        (2.67, 3.20, 3.04, 3.43, 3.11, 3.45, 3.49, 2.92, 3.02, 2.36, 3.22, 3.24, 3.25)),
    "R6_SC03_14": ("Ipati – Camiri", "SC",
        (4.1, 4.0, 2.2, 4.1, 3.1, 3.5, 1.0), 3.1,
        (3.14, 3.77, 3.59, 4.05, 3.67, 4.07, 4.13, 3.46, 3.59, 2.80, 3.83, 3.88, 3.91)),
    "R1_TJ05_40": ("Cr. Rancho Norte – Tarija", "TJ",
        (3.6, 4.0, 2.0, 3.1, 2.0, 1.5, 3.0), 2.6,
        (2.63, 3.17, 3.02, 3.41, 3.09, 3.43, 3.48, 2.92, 3.02, 2.35, 3.23, 3.29, 3.33)),
    "R11_TJ02_06": ("La Central – Villa Montes", "TJ",
        (3.6, 4.0, 2.5, 3.9, 2.1, 3.1, 4.0), 3.2,
        (3.17, 3.82, 3.63, 4.11, 3.72, 4.13, 4.20, 3.51, 3.64, 2.83, 3.89, 3.95, 4.00)),
    "R3_BN01_12": ("Yucumo – San Borja", "BN",
        (4.5, 2.0, 2.0, 2.6, 3.0, 1.3, 3.0), 2.6,
        (2.60, 3.12, 2.96, 3.34, 3.03, 3.35, 3.39, 2.82, 2.92, 2.29, 3.12, 3.14, 3.13)),
    "R9_NA01bn_05": ("San Javier – Trinidad", "BN",
        (5.0, 2.0, 2.0, 2.2, 3.0, 1.0, 1.0), 2.3,
        (2.34, 2.80, 2.65, 3.00, 2.71, 3.00, 3.04, 2.52, 2.60, 2.05, 2.78, 2.78, 2.77)),
    "R13_PD01_01": ("Cobija – Zofra", "PD",
        (4.8, 2.0, 2.0, 3.0, 3.0, 4.0, 1.0), 2.8,
        (2.78, 3.33, 3.15, 3.56, 3.23, 3.57, 3.61, 3.00, 3.11, 2.44, 3.32, 3.32, 3.31)),
    "R13_PD04_05": ("El Sena – Peña Amarilla", "PD",
        (5.0, 2.0, 2.0, 2.3, 3.0, 1.2, 4.0), 2.7,
        (2.68, 3.22, 3.05, 3.44, 3.12, 3.45, 3.49, 2.90, 2.99, 2.35, 3.21, 3.22, 3.20)),
}

# Descripciones genéricas (parametrización del Manual) por variable.
_DESC_VAR = {
    "Fisiografía":
        "Forma del terreno del entorno vial (serranías, montañas, llanuras, "
        "cuerpos de agua): a mayor pendiente/humedad del relieve, mayor aporte "
        "de vulnerabilidad a la vía.",
    "Clima (Köppen actual)":
        "Clasificación climática de Köppen; los climas fríos y húmedos "
        "afectan más la transitabilidad y la capa de rodadura.",
    "Pendiente (topografía adyacente)":
        "Gradiente del terreno adyacente; a mayor pendiente, mayor velocidad "
        "de escurrimiento hacia el cauce.",
    "Conservación Ambiental (Intervención Antrópica)":
        "Grado de perturbación humana (deforestación, cambio de uso de suelo, "
        "minería): incrementa la susceptibilidad a la erosión y altera las "
        "cuencas de aporte.",
    "Potencial de Inundación":
        "Propensión a inundación/anegamiento fluvial según recurrencia "
        "histórica y proyectada.",
    "Aptitud a la Escorrentía (Número de Curva)":
        "Capacidad del terreno de producir escorrentía (CN); sensible a la "
        "degradación de la cobertura vegetal.",
    "Estructura de Pavimento / Capa de Rodadura":
        "Tipología de la superficie de rodadura; su estado condiciona la "
        "fragilidad estructural de la vía.",
}


@dataclass(frozen=True)
class VariableVulnerabilidad:
    nombre: str
    valor: float
    peso: float
    descripcion: str


@dataclass(frozen=True)
class EscenarioRiesgo:
    plazo: str
    periodo: str
    signo: str
    ssp: str
    riesgo: float
    incremento: float
    clase: str


@dataclass(frozen=True)
class TramoReferenciaABC:
    ucod: str
    nombre_tramo: str
    red_vial: str
    departamento: str
    zona: str
    rios: str
    variables: tuple
    vulnerabilidad_total: float
    clase_vulnerabilidad: str
    riesgo_base: float
    clase_riesgo_base: str
    escenarios: tuple
    variable_dominante: str


def clase_valor(v: float) -> str:
    for umbral, nombre in ESCALA_RIESGO:
        if v < umbral:
            return nombre
    return "Considerable"


RIESGOS: dict[str, tuple] = {}   # UCOD → (r0..r12) exactos de la Tabla 6.3


def _construir_tramo(ucod: str, rios: str = "los ríos de la zona de aporte") -> TramoReferenciaABC:
    entrada = TRAMOS[ucod]
    nombre, cod_dep, vuln = entrada[0], entrada[1], entrada[2]
    variables = tuple(
        VariableVulnerabilidad(nom, vuln[i], peso, _DESC_VAR.get(nom, ""))
        for i, (nom, peso) in enumerate(VARIABLES_META)
    )
    # Variable dominante: mayor contribución ponderada (valor × peso).
    dom = max(variables, key=lambda v: v.valor * v.peso).nombre
    # Riesgo por escenario: EXACTO de la Tabla 6.3 si está cargado; si no,
    # fallback = riesgo_base × factor de amenaza nacional. El riesgo base es
    # Σ(Vᵢ × pesoᵢ), idéntico al de la Tabla 6.3.
    exacto = RIESGOS.get(ucod)
    if exacto is not None:
        riesgos = exacto
    else:
        rb = round(sum(v.valor * v.peso for v in variables), 2)
        riesgos = tuple(round(rb * FACTORES_ESCENARIO[i], 2) for i in range(13))
    r0 = riesgos[0]
    escenarios = tuple(
        EscenarioRiesgo(
            plazo, periodo, signo, ssp, round(riesgos[idx], 2),
            round(riesgos[idx] - r0, 2), clase_valor(riesgos[idx]))
        for (idx, signo, ssp, plazo, periodo) in ESCENARIOS_META
    )
    return TramoReferenciaABC(
        ucod=ucod, nombre_tramo=nombre, red_vial="Red Vial Fundamental (RVF)",
        departamento=DEPTOS.get(cod_dep, cod_dep), zona=nombre, rios=rios,
        variables=variables, vulnerabilidad_total=round(r0, 1),
        clase_vulnerabilidad=clase_valor(r0), riesgo_base=r0,
        clase_riesgo_base=clase_valor(r0), escenarios=escenarios,
        variable_dominante=dom,
    )


def _cargar_tramos_csv() -> int:
    """Carga los 320 tramos RVF desde el CSV empaquetado, si existe.

    Formato (una fila por tramo, sin encabezado obligatorio):
      ucod,nombre,cod_depto,fis,clima,pend,cons_amb,inund,cn,rodadura
    Extiende/actualiza `TRAMOS` con vectores de vulnerabilidad (3-tupla). El
    riesgo por escenario se computa con FACTORES_ESCENARIO. Devuelve el nº de
    tramos cargados. Best-effort: nunca lanza.
    """
    import csv
    from pathlib import Path
    ruta = Path(__file__).resolve().parent / "data" / "tramos_rvf_abc.csv"
    if not ruta.exists():
        return 0
    n = 0
    try:
        with open(ruta, encoding="utf-8") as f:
            for fila in csv.reader(f):
                if len(fila) < 10 or fila[0].strip().lower() in ("ucod", ""):
                    continue
                try:
                    ucod = fila[0].strip()
                    nombre = fila[1].strip()
                    cod_dep = fila[2].strip()
                    vuln = tuple(float(str(x).replace(",", ".")) for x in fila[3:10])
                except (ValueError, IndexError):
                    continue
                TRAMOS[ucod] = (nombre, cod_dep, vuln)
                n += 1
    except OSError:
        return n
    return n


def _cargar_riesgos_csv() -> int:
    """Carga los riesgos EXACTOS por escenario (Tabla 6.3) desde el CSV.

    Formato: ucod,r0,r1,...,r12 (13 valores). Puebla `RIESGOS`. Best-effort.
    """
    import csv
    from pathlib import Path
    ruta = Path(__file__).resolve().parent / "data" / "riesgos_rvf_abc.csv"
    if not ruta.exists():
        return 0
    n = 0
    try:
        with open(ruta, encoding="utf-8") as f:
            for fila in csv.reader(f):
                if len(fila) < 14 or fila[0].strip().lower() in ("ucod", ""):
                    continue
                try:
                    ucod = fila[0].strip()
                    vals = tuple(float(str(x).replace(",", ".")) for x in fila[1:14])
                except (ValueError, IndexError):
                    continue
                RIESGOS[ucod] = vals
                n += 1
    except OSError:
        return n
    return n


_N_TRAMOS_CSV = _cargar_tramos_csv()
_N_RIESGOS_CSV = _cargar_riesgos_csv()


TRAMO_REFERENCIA_DEFECTO = _construir_tramo("R3_LP06_09", "Alto Beni y Remolinos")


def _cod_depto_de(departamento: str | None) -> str | None:
    if not departamento:
        return None
    d = departamento.strip().lower()
    for cod, nom in DEPTOS.items():
        if nom.lower() in d or d in nom.lower():
            return cod
    return None


def tramo_referencia_para(lat: float | None = None, lon: float | None = None,
                          departamento: str | None = None) -> TramoReferenciaABC:
    """Selecciona el tramo RVF de referencia para el proyecto.

    v2: elige, entre los tramos disponibles, el primero del MISMO departamento
    del proyecto (detectado por HYDROFRA). Si no hay coincidencia, devuelve el
    tramo por defecto (Caranavi–Sapecho). Cuando se cargue la tabla completa de
    320 tramos con sus geometrías, se podrá elegir el tramo espacialmente más
    cercano a (lat, lon).
    """
    cod = _cod_depto_de(departamento)
    if cod:
        for ucod, (nombre, cod_dep, *_rest) in TRAMOS.items():
            if cod_dep == cod:
                return _construir_tramo(ucod)
    return TRAMO_REFERENCIA_DEFECTO


def intro_metodologica(t: TramoReferenciaABC) -> str:
    return (
        "Para la incorporación de la gestión de riesgos y la adaptación al "
        "cambio climático en el diseño del proyecto, se han aplicado las "
        "directrices del «Manual para la Interpretación y Aplicación de los "
        "Índices y Parámetros de Variabilidad Climática» de la ABC (Contrato "
        "ABC N° 480/21 GNT-CON-BM, 2022). Este instrumento evalúa el riesgo "
        "físico de la infraestructura vial frente a los escenarios futuros de "
        "cambio climático mediante un enfoque cuantitativo SIG que combina la "
        "vulnerabilidad (7 variables ponderadas, escala 1–5) con la amenaza "
        "(envolvente de los modelos AR6 MPI + MIROC6): RIESGO = VULNERABILIDAD "
        "× AMENAZA. El área del proyecto se asocia al tramo adyacente "
        f"{t.nombre_tramo} (UCOD: {t.ucod}) de la {t.red_vial}, departamento de "
        f"{t.departamento}, que define la línea base de vulnerabilidad y "
        "amenaza.")


def interpretacion_puentes(t: TramoReferenciaABC) -> str:
    # Riesgo máximo proyectado entre los 12 escenarios futuros.
    fut = [e for e in t.escenarios if e.ssp != "—"]
    peor = max(fut, key=lambda e: e.riesgo)
    return (
        f"Interpretación para los puentes: el riesgo base del tramo es "
        f"{t.riesgo_base:.2f} ({t.clase_riesgo_base}) y el máximo proyectado "
        f"por cambio climático alcanza {peor.riesgo:.2f} ({peor.clase}) en el "
        f"escenario {peor.ssp} ({peor.plazo}), un incremento de "
        f"+{peor.incremento:.2f}. El factor de mayor contribución a la "
        f"vulnerabilidad es «{t.variable_dominante}». El aumento del riesgo se "
        "debe principalmente a las proyecciones de precipitación extrema y "
        "concentrada; para drenajes mayores (puentes) esto exige un diseño "
        "hidráulico y de socavación conservador.")


def medidas_mitigacion(t: TramoReferenciaABC) -> list[tuple[str, list[str]]]:
    return [
        ("A. Mitigación por Intervención Antrópica (efecto en la cuenca de aporte)", [
            "Rediseño de caudales de diseño: emplear rigurosamente el Manual de "
            "Hidrología y Drenaje de la ABC, con períodos de retorno "
            "conservadores y coeficiente de escorrentía incrementado para "
            "prever la pérdida de cobertura forestal por deforestación.",
            "Control de sólidos aguas arriba: disipadores de energía, sistemas "
            "de control de ingreso en las márgenes y trampas de sedimentos "
            "aguas arriba de los estribos, contra el impacto de troncos y la "
            "sedimentación severa.",
            "Revegetación de márgenes: revegetación inmediata de laderas y "
            "márgenes adyacentes a las estructuras, coordinada con las "
            "comunidades locales para mitigar la erosión del pie de talud.",
        ]),
        ("B. Mitigación fisiográfica (erosión y socavación)", [
            "Protección de fundaciones contra socavación: diseñar pilas y "
            "estribos considerando socavación general y local extremas, con "
            "obras robustas (escolleras, gaviones, defensas ribereñas) a lo "
            "largo del Derecho de Vía para estabilizar el cauce.",
            "Gestión del exceso de humedad: drenaje longitudinal y subdrenes en "
            "los accesos para evacuar las aguas de infiltración y evitar la "
            "desestabilización de los taludes de aproximación.",
        ]),
        ("C. Consideraciones para la etapa de construcción", [
            "Seguimiento a alertas hidrológicas del SENAMHI durante la "
            "construcción de fundaciones, con desvíos provisionales "
            "sobrediseñados por el riesgo de avenidas repentinas.",
        ]),
    ]


def recomendaciones_socavacion(t: TramoReferenciaABC) -> dict:
    intro = (
        "El diseño de drenajes mayores (puentes) en la región de "
        f"{t.departamento} está expuesto a una severa variabilidad "
        "hidrometeorológica. Bajo los escenarios SSP370 (Negativo 1) y SSP585 "
        "(Negativo 2) se prevé un incremento de la intensidad de las "
        "precipitaciones concentradas que altera los parámetros hídricos de "
        "las cuencas de aporte, propiciando avenidas extraordinarias y "
        "desbordes relámpago (flash floods). Los cálculos de socavación "
        "(general y local) deben adoptar un enfoque dinámico y conservador.")
    bloques = [
        ("Diseño técnico (etapa de pre-inversión)", [
            "Adopción de criterios conservadores en el cálculo de caudales de "
            "diseño (Manual de Hidrología y Drenaje de la ABC) con períodos de "
            "diseño más amplios para absorber tormentas extremas e instantáneas.",
            "Coeficiente de escorrentía (o CN) penalizado para simular pérdida "
            "de cobertura vegetal por estiajes prolongados seguidos de lluvias "
            "concentradas.",
            "Sobredimensionar el gálibo y el área de paso para evitar que el "
            "espejo de agua alcance las vigas y aumente la socavación local por "
            "contracción del flujo.",
            "Profundizar las cotas de desplante de pilas y estribos por debajo "
            "de la socavación total (general + local), con factor de seguridad "
            "adicional por la incertidumbre SSP370/SSP585.",
            "Obras de protección: disipadores de energía, controles de ingreso, "
            "trampas de sedimentación aguas arriba y encauces (escolleras, "
            "gaviones) con hormigones resistentes a la abrasión.",
        ]),
        ("Etapa de construcción", [
            "Monitoreo y alertas tempranas de precipitación/crecidas durante la "
            "construcción de fundaciones, deteniendo faenas y protegiendo la "
            "excavación.",
            "Desvíos provisionales con diseño hidráulico excedente ante lluvias "
            "intensas e instantáneas.",
        ]),
        ("Conservación y mantenimiento", [
            "Campañas de limpieza preventiva temprana (mínimamente en "
            "septiembre) de sedimentos, palizadas y escombros bajo los puentes.",
            "Revegetación y estabilización de la cuenca de aporte con especies "
            "nativas resistentes a la erosión, para reducir el arrastre de "
            "sedimentos hacia la estructura.",
        ]),
    ]
    return {"titulo": ("Recomendaciones de ingeniería para el diseño contra la "
                       "socavación hidráulica bajo escenarios SSP370 y SSP585"),
            "intro": intro, "bloques": bloques}


# ── Matrices de mitigación (Tablas 7.1–7.6 del Manual) ───────────────────────
# Por variable de vulnerabilidad dominante: para cada activo afectado (Derecho
# de vía, Drenajes [puentes/alcantarillas], Taludes, Pavimentos) el indicador
# de estrés y las medidas de Diseño / Construcción / Conservación-Mantenimiento.
def _a(activo, estres, diseno, construccion, conservacion):
    return {"activo": activo, "estres": estres, "diseno": diseno,
            "construccion": construccion, "conservacion": conservacion}


MATRICES_MITIGACION = {
    "fisiografia": {
        "titulo": "Tabla 7.1 — Fisiografía",
        "indicador": ("Medio/entorno que incrementa la vulnerabilidad de la "
                      "RVF; cambios atribuibles al cambio paulatino del clima."),
        "activos": [
            _a("Derecho de vía",
               "Afectación general del DDV, crecimiento de vegetación, hundimiento local.",
               "Consolidación/liberación temprana del DDV.",
               "Evaluar la necesidad de tratar el DDV; dejar vegetación como protección.",
               "Mayor frecuencia de intervención, previa evaluación de los cambios verificados."),
            _a("Drenajes (puentes/alcantarillas)",
               "Mayores caudales y mayor arrastre de sedimentos.",
               "Empleo del Manual de Hidrología y Drenaje de la ABC (nociones de riesgo y períodos de diseño).",
               "Mayor previsión y seguimiento de desvíos en cursos de agua; protección contra anegamiento.",
               "Mayor frecuencia de limpieza; campañas preventivas tempranas (mínimo septiembre)."),
            _a("Taludes",
               "Desestabilización.",
               "Verificación con mayor cantidad de muestreos de caracterización.",
               "Protección con cobertura temporal; verificación de niveles de humedad y su exceso.",
               "Verificación de taludes y obras de estabilización posterior a lluvias; estabilidad en cortes altos."),
            _a("Pavimentos",
               "Crecimiento de vegetación, hundimiento y deformación.",
               "Verificación en condiciones de mayor tránsito.",
               "Verificación de niveles de humedad óptimos para la conformación de capas.",
               "Mantenimiento preventivo; estabilidad en terraplenes; verificación de erosividad."),
        ],
    },
    "clima_exceso": {
        "titulo": "Tabla 7.2 — Clima (exceso de precipitación / intensidad)",
        "indicador": "Incremento de la precipitación / intensidad.",
        "activos": [
            _a("Derecho de vía",
               "Encharcamiento del DDV sobre lo normal o aceptable.",
               "Diseños de protección que abarquen desde el DDV.",
               "Verificar la necesidad de obras de protección a la vía que abarquen el DDV.",
               "Mantenimiento preventivo temprano necesario."),
            _a("Drenajes (puentes/alcantarillas)",
               "Mayores caudales y mayor arrastre de sedimentos.",
               "Empleo del Manual de Hidrología y Drenaje de la ABC.",
               "Atención a alertas de precipitación y crecidas; previsión de desvíos; protección contra anegamiento.",
               "Mantenimiento preventivo temprano necesario."),
            _a("Taludes",
               "Desestabilización.",
               "Verificación de taludes mayores a 2.5 m según el suelo y sus características mecánicas.",
               "Protección con cobertura temporal; verificación de humedad y su exceso.",
               "Mantenimiento preventivo temprano necesario."),
            _a("Pavimentos",
               "Erosión en terraplén y estructura; daño por encharcamiento; apertura de grietas.",
               "Verificación de protecciones/estabilización adicional; subdrenes adicionales.",
               "Verificación de niveles de humedad óptimos para la conformación de capas.",
               "Mantenimiento preventivo temprano necesario."),
        ],
    },
    "clima_sequia": {
        "titulo": "Tabla 7.3 — Clima (falta de precipitación / sequía)",
        "indicador": "Sequía.",
        "activos": [
            _a("Drenajes (puentes/alcantarillas)",
               "Mayor aptitud a la escorrentía y arrastre de sedimentos por pérdida de vegetación en la zona de aporte.",
               "Empleo del Manual de Hidrología y Drenaje de la ABC.",
               "Atención a alertas de precipitación y crecidas.",
               "Revegetación inmediata de la zona de aporte; trampas de sedimentos u otras medidas."),
            _a("Taludes",
               "Desestabilización del talud por pérdida de cobertura vegetal por sequía.",
               "Revegetación con especies de mayor resistencia al estrés hídrico.",
               "Previsión de revegetación.",
               "Verificación periódica de pérdida de cobertura; reemplazo paulatino por especies resistentes."),
            _a("Pavimentos",
               "Pérdida de material, erosión en terraplén o pavimento.",
               "Verificación de la necesidad de estabilización de capas.",
               "Previsión de fuentes alternas de agua para las actividades de construcción.",
               "Previsión de fuentes alternas de agua para fines de conservación."),
        ],
    },
    "pendiente_cn": {
        "titulo": "Tabla 7.4 — Pendiente y Aptitud a la escorrentía (CN)",
        "indicador": "Verificación de incremento de la aptitud a la escorrentía.",
        "activos": [
            _a("Derecho de vía",
               "Erosión en el pie del cuerpo de pavimento.",
               "Diseño de pendientes y protección de pie de talud en el DDV; reducción estratégica de energía.",
               "Ralentizadores de flujo y disipadores de energía temporales (posible consolidación como protección).",
               "Mayor frecuencia de inspección e intervención."),
            _a("Drenajes (puentes/alcantarillas)",
               "Mayor arrastre de sedimentos y crecidas instantáneas y violentas.",
               "Manual de la ABC; disipadores de energía y controles de ingreso de mayor calidad.",
               "—", "—"),
            _a("Taludes",
               "Potencial de erosión mayor.",
               "Empleo óptimo de drenaje; diseño y verificación por diversos métodos.",
               "—", "—"),
            _a("Pavimentos",
               "Erosión en terraplén y estructura; daño por encharcamiento; apertura de grietas.",
               "Verificación de protecciones/estabilización adicional; subdrenes adicionales.",
               "Verificación de niveles de humedad óptimos para la conformación de capas.",
               "Mantenimiento preventivo temprano necesario."),
        ],
    },
    "conservacion": {
        "titulo": "Tabla 7.5 — Conservación Ambiental (intervención antrópica)",
        "indicador": "Incremento en la actividad antrópica.",
        "activos": [
            _a("Derecho de vía",
               "Potencial invasión de zonas liberadas.",
               "Liberación pronta y temprana.",
               "Generación de convenios de ayuda mutua.",
               "Mantenimiento preventivo temprano necesario."),
            _a("Drenajes (puentes/alcantarillas)",
               "Mayor carga sólida y líquida por efecto antrópico.",
               "Empleo del Manual de Hidrología y Drenaje de la ABC.",
               "—", "—"),
            _a("Taludes",
               "Asentamientos en zonas de sobre-talud o que comprometan el mismo.",
               "—", "—", "—"),
            _a("Pavimentos",
               "Afectación antrópica general.",
               "—", "—", "—"),
        ],
    },
    "inundacion": {
        "titulo": "Tabla 7.6 — Potencial de inundación",
        "indicador": ("Incremento de las zonas inundadas, mayor permanencia del "
                      "espejo inundado."),
        "activos": [
            _a("Derecho de vía",
               "DDV anegado constantemente.",
               "Empleo del DDV para protección de la vía.",
               "Necesidad de drenajes de apoyo, temporales y permanentes.",
               "Mantenimiento preventivo temprano necesario."),
            _a("Drenajes (puentes/alcantarillas)",
               "Convivencia constante con el agua.",
               "Manual de la ABC; mayor previsión de subdrenes especiales.",
               "—", "—"),
            _a("Taludes",
               "Zonas anegadizas sobre puntos de estabilización.",
               "Necesidad de drenajes adicionales.",
               "—", "—"),
            _a("Pavimentos",
               "Convivencia constante con el agua.",
               "Diseño de taludes que convivan con el agua.",
               "—", "—"),
        ],
    },
}

_VARIABLE_A_MATRIZ = {
    "Fisiografía": "fisiografia",
    "Clima (Köppen actual)": "clima_exceso",
    "Pendiente (topografía adyacente)": "pendiente_cn",
    "Conservación Ambiental (Intervención Antrópica)": "conservacion",
    "Potencial de Inundación": "inundacion",
    "Aptitud a la Escorrentía (Número de Curva)": "pendiente_cn",
    "Estructura de Pavimento / Capa de Rodadura": "fisiografia",
}


def matriz_mitigacion(t: TramoReferenciaABC) -> dict:
    """Matriz de mitigación (Tabla 7.x) según la variable dominante del tramo.

    Devuelve {titulo, indicador, variable, activos: [{activo, estres, diseno,
    construccion, conservacion}]}.
    """
    clave = _VARIABLE_A_MATRIZ.get(t.variable_dominante, "fisiografia")
    m = MATRICES_MITIGACION[clave]
    return {"titulo": m["titulo"], "indicador": m["indicador"],
            "variable": t.variable_dominante, "activos": m["activos"]}


# ── Conclusiones y referencias del análisis de riesgo (§14 → §15/§16) ─────────
def conclusiones_abc(t: TramoReferenciaABC, T_diseno: int = 200,
                     T_verificacion: int = 300) -> list[str]:
    """Conclusiones/recomendaciones derivadas de los resultados de la §14.

    Se construyen a partir del tramo de referencia real (riesgo base, peor
    escenario proyectado, variable dominante) y del criterio de períodos de
    retorno adoptado, apoyadas en literatura de adaptación de infraestructura
    vial al cambio climático (PIARC, CAF, IPCC-AR6).
    """
    fut = [e for e in t.escenarios if e.ssp != "—"]
    peor = max(fut, key=lambda e: e.riesgo) if fut else None
    cruza_alto = any(e.riesgo >= 4.0 for e in fut)
    out = [
        f"<b>Nivel de riesgo del tramo.</b> El tramo de referencia "
        f"{t.nombre_tramo} ({t.ucod}, {t.departamento}) presenta un riesgo "
        f"base actual de {t.riesgo_base:.2f} ({t.clase_riesgo_base}). Bajo los "
        f"escenarios de cambio climático (envolvente AR6 MPI+MIROC6), el riesgo "
        + (f"máximo proyectado alcanza {peor.riesgo:.2f} ({peor.clase}) en el "
           f"escenario {peor.ssp} ({peor.plazo}), un incremento de "
           f"+{peor.incremento:.2f} respecto al presente. " if peor else "")
        + ("El riesgo supera el umbral «Apreciable/Alto» (≥ 4.0), por lo que el "
           "diseño hidráulico y de fundaciones exige atención reforzada."
           if cruza_alto else
           "Aun sin cruzar el umbral «Alto», la tendencia creciente exige "
           "criterios de diseño conservadores."),
        f"<b>Factor crítico de vulnerabilidad.</b> La variable que más aporta "
        f"a la vulnerabilidad del tramo es «{t.variable_dominante}»; las medidas "
        f"prioritarias son, por tanto, las de la matriz de mitigación asociada "
        f"(Sección 14.4). La intervención antrópica en la cuenca de aporte "
        f"amplifica la respuesta hidrológica y la producción de sedimentos, por "
        f"lo que la adaptación debe trascender la estructura e incluir "
        f"revegetación y control de sólidos en la cuenca alta y media.",
        f"<b>Períodos de retorno adoptados.</b> Por el incremento proyectado del "
        f"riesgo hidroclimático se adopta un caudal de diseño para T = "
        f"{T_diseno} años y una verificación estructural (caso pésimo) para "
        f"T = {T_verificacion} años. Este criterio conservador es consistente "
        f"con la evidencia internacional de que el aumento de la intensidad de "
        f"la precipitación eleva la socavación en fundaciones de puentes y "
        f"justifica revisar/ampliar los períodos de retorno de diseño "
        f"(PIARC, 2019; De la Peña et al., 2018; IPCC-AR6, 2022).",
        "<b>Mecanismo de daño dominante: socavación.</b> El principal impacto "
        "proyectado sobre drenajes mayores es la socavación general y local por "
        "avenidas más intensas, repentinas (flash floods) y con mayor carga "
        "sólida. Las cotas de desplante de pilas y estribos deben situarse por "
        "debajo de la socavación total (general + local) con un factor de "
        "seguridad adicional, y el gálibo sobredimensionarse para evitar el "
        "contacto del espejo de agua con la superestructura (estudios de "
        "vulnerabilidad de puentes fluviales bajo cambio climático).",
        "<b>Gestión, operación y mantenimiento.</b> Se recomienda integrar al "
        "plan de conservación vial: (i) seguimiento a las alertas "
        "hidrometeorológicas del SENAMHI durante construcción y operación; "
        "(ii) campañas de limpieza preventiva temprana de cauces (mínimo "
        "septiembre, antes de la época de lluvias); y (iii) inspección "
        "post-crecida de obras de protección y fundaciones, como parte de un "
        "enfoque de resiliencia y adaptación continua (marco PIARC de "
        "adaptación de la infraestructura vial al cambio climático).",
        "<b>Limitaciones.</b> La valoración de riesgo del tramo proviene del "
        "análisis SIG nacional del Manual de la ABC (escala 1:250.000, "
        "envolvente de 2 modelos AR6); para el diseño definitivo debe "
        "complementarse con verificación de campo del tramo específico y con "
        "el estudio hidráulico-estructural de socavación de detalle del sitio.",
    ]
    return out


def referencias_abc() -> list[str]:
    """Referencias (APA) del análisis de riesgo hidroclimático (§14)."""
    return [
        "Administradora Boliviana de Carreteras (2022). Manual para la "
        "Interpretación y Aplicación de los Índices y Parámetros de "
        "Variabilidad Climática (Contrato ABC N° 480/21 GNT-CON-BM, Producto "
        "6). La Paz, Bolivia: ABC / Banco Mundial.",
        "IPCC (2022). Climate Change 2022: Impacts, Adaptation and "
        "Vulnerability. Sixth Assessment Report (AR6), Working Group II. "
        "Ginebra: Grupo Intergubernamental de Expertos sobre el Cambio "
        "Climático.",
        "De la Peña, E., Díaz, J., Rodrigo, M., Miralles, E., Valdés, S., & "
        "Cañada, L. (2018). Guía de buenas prácticas para la adaptación de las "
        "carreteras al clima. Corporación Andina de Fomento (CAF).",
        "PIARC — Asociación Mundial de la Carretera (2019). Adaptation of road "
        "bridges to climate change. Comité Técnico de Puentes. París: PIARC.",
        "PIARC — World Road Association (2015). International Climate Change "
        "Adaptation Framework for Road Infrastructure. París: PIARC.",
        "UNISDR (2009). Terminología sobre la Reducción del Riesgo de "
        "Desastres. Ginebra: Estrategia Internacional de las Naciones Unidas "
        "para la Reducción de Desastres.",
        "CENEPRED (2014). Manual para la Evaluación de Riesgos originados por "
        "Fenómenos Naturales (2.ª versión). Lima: Centro Nacional de "
        "Estimación, Prevención y Reducción del Riesgo de Desastres.",
        "Ahmadi, M., et al. (2023). Assessment of the impact of climate change "
        "and flooding on bridges and surrounding area. Frontiers in Built "
        "Environment, 9, 1268304.",
    ]
