"""Metodología para la selección de modelos de cambio climático — Sección 3.1.

Sintetiza la mejor práctica documentada en la literatura peer-reviewed para
escoger, entre los modelos CMIP6, CORDEX-SAM y NEX-GDDP disponibles para
Bolivia, el subconjunto que mejor reproduce el comportamiento observado en
las estaciones SELECCIONADAS por la metodología de la Sección 2 (que pasan
las pruebas de consistencia OMM-168). El módulo entrega:

- `metodologia_pasos()` — lista de 7 etapas numeradas (texto + descripción).
- `metricas_desempeno()` — tabla con métrica, fórmula, umbral satisfactorio
  y referencia primaria.
- `metricas_bajo_caudal()` — subconjunto de métricas críticas para Q mínimos.
- `metodos_correccion_sesgo()` — opciones de bias correction con su
  recomendación de uso.
- `metodos_ensemble()` — esquemas para combinar múltiples modelos.
- `region_bolivia(lat, lon)` — clasifica el punto en Altiplano / Valles /
  Amazonía / Chaco usando umbrales latitud-longitud-altitud aproximados.
- `modelos_recomendados(region)` — devuelve el subconjunto de modelos con
  mejor desempeño documentado para esa región.

Síntesis basada en: Almazroui et al. (2021), Seiler et al. (2013), Seiler &
Vicente-Serrano (2022), Pabón-Caicedo et al. (2020), Llopart et al. (2020),
Reboita et al. (2022), Buytaert et al. (2010), Olmo et al. (2024 — BASD-
CMIP6-PE), Brunner et al. (2020 — ClimWIP), Cannon et al. (2015 — QDM),
Cannon (2018 — MBCn), Switanek et al. (2017 — SDM), Pushpalatha et al.
(2012), Gupta et al. (2009 — KGE), Moriasi et al. (2015), IPCC AR6 WG1
Capítulos 10 y 12, FAO CCAFS-Climate, WMO Guide N.º 168.
"""

from __future__ import annotations

from typing import Literal


# ─────────────────────── 1. Metodología en 7 etapas ───────────────────────

def metodologia_pasos() -> list[tuple[str, str]]:
    """Pasos numerados para reportar en la subsección 3.1."""
    return [
        ("Etapa 1 — Pool inicial de modelos disponibles",
         "Listar todos los modelos CMIP6 (NASA NEX-GDDP-CMIP6, ~25 km), "
         "regionales CORDEX-SAM (Eta-CORDEX, RegCM4, REMO2015 a 22–50 km) "
         "y nacionales (Atlas MMAyA, HadRM3P/PRECIS 25 km) con cobertura "
         "espacial sobre la cuenca delineada y al menos un escenario "
         "SSP/RCP de referencia (SSP2-4.5 obligatorio + SSP5-8.5 "
         "recomendado, alineado con IPCC AR6 WG1 Cap. 12)."),
        ("Etapa 2 — Anclaje observacional con las estaciones de la Sección 2",
         "Extraer del histórico de cada modelo (1981–2014) la serie "
         "interpolada al punto de cada estación seleccionada en la "
         "Sección 2 (que ya superaron las pruebas Mann-Kendall, Pettitt, "
         "rachas, autocorrelación y KS). Estas estaciones constituyen la "
         "verdad terreno para evaluar el desempeño."),
        ("Etapa 3 — Corrección de sesgo (bias correction)",
         "Aplicar a cada modelo una corrección estadística previa a la "
         "comparación: en cuencas tropicales-andinas se documenta "
         "preferencia por Quantile Delta Mapping (Cannon et al., 2015) o "
         "Scaled Distribution Mapping (Switanek et al., 2017) — ambos "
         "preservan la señal de cambio del GCM —. Para variables "
         "acopladas P-T-evapotranspiración se recomienda MBCn (Cannon, "
         "2018), que conserva la dependencia inter-variable crítica para "
         "balance hidrológico de mínimos."),
        ("Etapa 4 — Métricas de desempeño multi-criterio",
         "Calcular para cada estación-modelo: NSE (Nash & Sutcliffe, "
         "1970), KGE (Gupta et al., 2009) con su descomposición r/α/β, "
         "PBIAS (Moriasi et al., 2015), RSR y la métrica I² de Reichler "
         "& Kim (2008). Adicionalmente para mínimos: KGE_log y NSE_1/Q "
         "(Pushpalatha et al., 2012) que penalizan errores en estiaje. "
         "Resumir con diagrama de Taylor (Taylor, 2001) y portrait "
         "diagram (Gleckler et al., 2008)."),
        ("Etapa 5 — Ranking ponderado por modelo",
         "Aplicar Reliability Ensemble Averaging — REA (Giorgi & Mearns, "
         "2002) o el esquema ClimWIP (Brunner et al., 2020) que combina "
         "desempeño + independencia entre miembros del ensemble. El "
         "puntaje por modelo se calcula promediando los rankings por "
         "métrica de la Etapa 4 sobre todas las estaciones de la "
         "Sección 2; modelos con menor sesgo y mayor independencia "
         "reciben pesos más altos."),
        ("Etapa 6 — Selección del subconjunto representativo",
         "Retener los modelos del cuartil superior del ranking + los "
         "modelos del Climate Futures Framework (Whetton et al., 2012) "
         "que representan escenarios extremos (cálido-seco, cálido-húmedo, "
         "frío-seco, frío-húmedo) para preservar la dispersión "
         "estructural y no subestimar la incertidumbre futura "
         "(advertencia de Buytaert et al., 2010)."),
        ("Etapa 7 — Validación cruzada e informe de incertidumbre",
         "Verificar el ensemble seleccionado en un período independiente "
         "(p. ej. 2015–2020 si la calibración fue 1981–2014) y reportar "
         "explícitamente: (i) los pesos REA/ClimWIP por modelo; "
         "(ii) la dispersión inter-modelo del cambio proyectado de Pann, "
         "ETann y Q90 a 2050/2080; (iii) la confianza por horizonte "
         "siguiendo el marco IPCC AR6 (acuerdo + evidencia)."),
    ]


# ─────────────────────── 2. Tabla de métricas ───────────────────────

def metricas_desempeno() -> list[dict]:
    """Métricas pointwise + multi-modelo con fórmula, umbral, referencia."""
    return [
        {"metrica": "NSE",
         "formula": "1 − Σ(O−S)² / Σ(O−Ō)²",
         "umbral": "> 0.50 satisfactorio (mensual)",
         "ref": "Nash & Sutcliffe (1970); Moriasi et al. (2015)"},
        {"metrica": "KGE",
         "formula": "1 − √[(r−1)² + (α−1)² + (β−1)²]",
         "umbral": "> −0.41 supera benchmark de la media; > 0.50 bueno",
         "ref": "Gupta et al. (2009); Knoben et al. (2019)"},
        {"metrica": "PBIAS",
         "formula": "100·Σ(O−S)/Σ O",
         "umbral": "|PBIAS| ≤ 15 % (estricto) — ≤ 25 % (aceptable)",
         "ref": "Moriasi et al. (2007, 2015)"},
        {"metrica": "RSR",
         "formula": "RMSE / σ_obs",
         "umbral": "≤ 0.70 (mensual)",
         "ref": "Moriasi et al. (2007)"},
        {"metrica": "Diagrama de Taylor",
         "formula": "E'² = σ_f² + σ_r² − 2·σ_f·σ_r·R",
         "umbral": "Punto-objetivo: R≈1, σ_f/σ_r≈1, E'≈0",
         "ref": "Taylor (2001)"},
        {"metrica": "I² (model performance index)",
         "formula": "Σ_var w_v · (e_v² / σ_obs²)",
         "umbral": "Menor I² = mejor (ranking relativo)",
         "ref": "Reichler & Kim (2008)"},
        {"metrica": "Portrait diagram / E'_rel",
         "formula": "(E²_modelo − E²_mediana) / E²_mediana",
         "umbral": "E'_rel < 0 = supera la mediana del ensemble",
         "ref": "Gleckler et al. (2008)"},
        {"metrica": "Peso REA",
         "formula": "R = [(R_B)^m · (R_D)^n]^(1/(mn))",
         "umbral": "Mayor R = mayor contribución al ensemble medio",
         "ref": "Giorgi & Mearns (2002)"},
        {"metrica": "Peso ClimWIP",
         "formula": "w_i ∝ exp(−D²/σ_D²) / [1 + Σ exp(−S²/σ_S²)]",
         "umbral": "Pondera por desempeño (D) y similitud (S)",
         "ref": "Brunner et al. (2020); Knutti et al. (2017)"},
    ]


def metricas_bajo_caudal() -> list[dict]:
    """Métricas críticas para reproducir caudales mínimos / estiaje."""
    return [
        {"metrica": "NSE_1/Q",
         "formula": "NSE sobre 1/(Q+ε), ε = Q̄_obs/100",
         "umbral": "> 0.50 satisfactorio para bajos",
         "ref": "Pushpalatha et al. (2012)"},
        {"metrica": "KGE_log",
         "formula": "KGE sobre log(Q+ε)",
         "umbral": "> 0.50 (cuidar ε)",
         "ref": "Santos et al. (2018); Pushpalatha et al. (2012)"},
        {"metrica": "Sesgo Q90 / Q95",
         "formula": "(Q90_sim − Q90_obs)/Q90_obs",
         "umbral": "|sesgo| < 20 %",
         "ref": "Smakhtin (2001)"},
        {"metrica": "Sesgo BFI (baseflow index)",
         "formula": "|BFI_sim − BFI_obs|",
         "umbral": "< 0.10 aceptable",
         "ref": "Smakhtin (2001)"},
        {"metrica": "Constante de recesión k",
         "formula": "Q(t) = Q₀·exp(−t/k)",
         "umbral": "Error relativo < 15 %",
         "ref": "Smakhtin (2001)"},
        {"metrica": "Sesgo PP estación seca",
         "formula": "(P_sim − P_obs)/P_obs en JJA",
         "umbral": "|sesgo| < 20 %",
         "ref": "Pushpalatha et al. (2012); Almazroui et al. (2021)"},
    ]


# ─────────────────────── 3. Bias correction ───────────────────────

def metodos_correccion_sesgo() -> list[dict]:
    """Métodos disponibles ordenados de menor a mayor sofisticación."""
    return [
        {"metodo": "Linear Scaling",
         "principio": "Factor multiplicativo (P) / aditivo (T) mensual sobre la media",
         "preserva_tendencia": "No",
         "multivariado": "No",
         "recomendado": "Línea base / referencia",
         "ref": "Schmidli et al. (2006)"},
        {"metodo": "LOCI",
         "principio": "Ajusta umbral de día húmedo + intensidad media",
         "preserva_tendencia": "No",
         "multivariado": "No",
         "recomendado": "Eliminar drizzle en RCMs",
         "ref": "Schmidli et al. (2006)"},
        {"metodo": "Power Transformation",
         "principio": "Corrección no lineal de media y varianza",
         "preserva_tendencia": "Parcial",
         "multivariado": "No",
         "recomendado": "Andes de altura (validado en Cachi, Perú)",
         "ref": "Teutschbein & Seibert (2012); Olsson et al. (Cachi)"},
        {"metodo": "Empirical QM",
         "principio": "Mapeo no paramétrico CDF modelo → CDF observada",
         "preserva_tendencia": "No (puede distorsionar)",
         "multivariado": "No",
         "recomendado": "Downscaling estacional con muchos años de obs",
         "ref": "Themeßl et al. (2011, 2012)"},
        {"metodo": "BCSD",
         "principio": "QM mensual + desagregación espacial + temporal",
         "preserva_tendencia": "Parcial",
         "multivariado": "No",
         "recomendado": "Modelos hidrológicos macroescala (VIC)",
         "ref": "Wood et al. (2002, 2004)"},
        {"metodo": "QDM (Quantile Delta Mapping)",
         "principio": "QM sobre cambios relativos por cuantil",
         "preserva_tendencia": "Sí",
         "multivariado": "No",
         "recomendado": "Cambio climático, extremos de P",
         "ref": "Cannon et al. (2015)"},
        {"metodo": "SDM",
         "principio": "Distribuciones paramétricas escaladas + freq día húmedo",
         "preserva_tendencia": "Sí",
         "multivariado": "No",
         "recomendado": "Frecuencia eventos; cuencas montañosas",
         "ref": "Switanek et al. (2017)"},
        {"metodo": "ISI-MIP / BASD",
         "principio": "Trend-preserving multiplicativo (P) / aditivo (T)",
         "preserva_tendencia": "Sí",
         "multivariado": "No",
         "recomendado": "Disponible para Perú/Ecuador a 10 km (BASD-CMIP6-PE)",
         "ref": "Hempel et al. (2013); Sedlmeier et al. (2024)"},
        {"metodo": "MBCn",
         "principio": "N-dim probability density transform iterativo",
         "preserva_tendencia": "Sí",
         "multivariado": "Sí (P-T-viento)",
         "recomendado": "Eventos compuestos; modelado nival/glaciar; balance "
                         "hidrológico acoplado P-ETP",
         "ref": "Cannon (2018)"},
    ]


# ─────────────────────── 4. Métodos de ensemble ───────────────────────

def metodos_ensemble() -> list[dict]:
    return [
        {"metodo": "Media equiponderada",
         "pesos": "w_i = 1/N",
         "reduce": "Incertidumbre aleatoria interna (parcial)",
         "ref": "Línea base — reportada por IPCC AR6"},
        {"metodo": "Bayesian Model Averaging (BMA)",
         "pesos": "w_i ∝ p(obs|model_i)",
         "reduce": "Sesgo de modelo; entrega envolvente probabilística",
         "ref": "Tebaldi & Knutti (2007)"},
        {"metodo": "REA (Reliability Ensemble Averaging)",
         "pesos": "R_B (sesgo) × R_D (convergencia futura)",
         "reduce": "Sesgo + dispersión inter-modelo",
         "ref": "Giorgi & Mearns (2002)"},
        {"metodo": "Knutti 2017 (performance + independence)",
         "pesos": "w_i ∝ exp(−D²/σ_D²) / [1+Σ exp(−S²/σ_S²)]",
         "reduce": "Sesgo y dependencia genealógica (CMIP siblings)",
         "ref": "Knutti et al. (2017)"},
        {"metodo": "ClimWIP",
         "pesos": "Diagnósticos múltiples; σ_D, σ_S calibrados perfect-model",
         "reduce": "Sesgo + dependencia + «hot models» CMIP6",
         "ref": "Brunner et al. (2020)"},
        {"metodo": "Sanderson 2017",
         "pesos": "Matriz distancia + skill; unique-model count",
         "reduce": "Dependencia genealógica entre miembros",
         "ref": "Sanderson et al. (2017)"},
        {"metodo": "Replicate Earth (B&A)",
         "pesos": "Pesos por correlación de errores",
         "reduce": "Dependencia estadística (errores comunes)",
         "ref": "Bishop & Abramowitz (2013)"},
        {"metodo": "Climate Futures Framework",
         "pesos": "Sin promedio: agrupa miembros en escenarios representativos",
         "reduce": "Preserva incertidumbre estructural para adaptación",
         "ref": "Whetton et al. (2012)"},
    ]


# ─────────────────────── 5. Región Bolivia + modelos recomendados ───────

RegionBolivia = Literal["altiplano", "valles", "amazonia", "chaco"]


def region_bolivia(lat: float, lon: float,
                     altitud_msnm: float | None = None) -> RegionBolivia:
    """Clasifica el punto en una de las 4 macro-regiones climáticas bolivianas.

    Reglas operacionales (Seiler 2013; MMAyA Atlas; Espinoza 2020):
    - Altiplano: altitud ≥ 3000 m en cualquier punto, o longitud ≤ −67°
      con latitud entre −22° y −15° (corresponde aproximadamente a La
      Paz / Oruro / occidente de Potosí).
    - Amazonía: latitud ≥ −15° (Beni, Pando, norte de La Paz) o
      latitud ≥ −17° con longitud ≤ −64° (Yungas / NW de Cochabamba).
    - Chaco: latitud ≤ −19° con longitud ≥ −64° y altitud < 1500 m
      (Yacuiba, Villa Montes, sur del Bermejo).
    - Valles interandinos: el resto (transición Cochabamba-Sucre-Tarija
      a altitudes intermedias 1500–2800 m).
    """
    if altitud_msnm is not None and altitud_msnm >= 3000:
        return "altiplano"
    if -22 <= lat <= -15 and lon <= -67.0:
        return "altiplano"
    if lat >= -15:
        return "amazonia"
    if lat >= -17 and lon <= -64:
        return "amazonia"
    if lat <= -19 and lon >= -64 and (altitud_msnm is None or altitud_msnm < 1500):
        return "chaco"
    return "valles"


def nombre_region(region: RegionBolivia) -> str:
    return {
        "altiplano": "Altiplano (La Paz, Oruro, Potosí)",
        "valles": "Valles interandinos (Cochabamba, Chuquisaca, Tarija)",
        "amazonia": "Amazonía boliviana (Beni, Pando, Norte de La Paz)",
        "chaco": "Chaco (Santa Cruz sur, Tarija este)",
    }[region]


MODELOS_POR_REGION: dict[RegionBolivia, dict] = {
    "altiplano": {
        "cmip6_curados": ["MPI-ESM1-2-HR", "EC-Earth3", "NorESM2-MM",
                            "MIROC6", "CESM2"],
        "cordex_core": ["Eta-MIROC5 (25 km)", "Eta-HadGEM2 (25 km)",
                          "REMO2015-MPI-ESM (25 km)"],
        "sesgo": ("Sesgo frío de −1 a −3 °C y exceso de precipitación; "
                    "convección excesiva sobre la cordillera; ciclo "
                    "anual mal simulado en estación seca."),
        "fuentes": ["Seiler et al. (2013)", "Seiler & Vicente-Serrano (2022)",
                     "Almazroui et al. (2021)", "Ortega et al. (2021)"],
    },
    "valles": {
        "cmip6_curados": ["MIROC6", "CESM2", "MPI-ESM1-2-HR", "EC-Earth3-Veg"],
        "cordex_core": ["RegCM4-MPI-ESM (25 km)", "REMO2015-MPI-ESM (25 km)"],
        "sesgo": ("Subestimación de la lluvia orográfica en ladera "
                    "oriental; sesgo seco en estación lluviosa."),
        "fuentes": ["Falco et al. (2019)", "Llopart et al. (2020)",
                     "Pabón-Caicedo et al. (2020)"],
    },
    "amazonia": {
        "cmip6_curados": ["CESM2", "MIROC6", "EC-Earth3-Veg",
                            "BCC-CSM2-MR", "ACCESS-CM2"],
        "cordex_core": ["REMO2015 (25 km)", "RegCM4 (25 km)",
                          "Eta-INPE (20 km)"],
        "sesgo": ("Subestimación de lluvia en NW amazónico; problema de "
                    "«doble-ITCZ»; sesgo seco al inicio de estación seca; "
                    "alta dispersión inter-modelo en el piedmont andino."),
        "fuentes": ["Marengo et al. (2015)", "Almazroui et al. (2021)",
                     "Reboita et al. (2022)", "Espinoza et al. (2020)"],
    },
    "chaco": {
        "cmip6_curados": ["MPI-ESM1-2-HR", "EC-Earth3", "ACCESS-CM2",
                            "NorESM2-MM"],
        "cordex_core": ["Eta-HadGEM2 (25 km)", "RegCM4-MPI-ESM (25 km)"],
        "sesgo": ("Sobreestimación de la precipitación de verano; "
                    "subestimación de la duración de las sequías; "
                    "sesgo cálido moderado."),
        "fuentes": ["Solman (2013)", "Llopart et al. (2020)",
                     "Reboita et al. (2022)"],
    },
}


def modelos_recomendados(region: RegionBolivia) -> dict:
    """Devuelve el bloque de modelos curados + sesgo + fuentes para la región."""
    return MODELOS_POR_REGION[region]


# ─────────────────────── 6. Conclusión y recomendaciones operacionales ───

RECOMENDACIONES_BOLIVIA = [
    "Bolivia no prescribe legalmente un GCM/RCP/SSP específico. La elección "
    "técnica recae en el operador (SENAMHI, MMAyA, consultor). HYDROFRA "
    "alinea su selección con la Política Plurinacional de Cambio Climático "
    "2023 (RM 369/2023), la NDC Bolivia 2022 (8 metas hídricas) y los "
    "lineamientos IPCC AR6 WG1 Cap. 10 y Cap. 12.",
    "MMAyA reconoce que en los próximos ~10 años no habrá RCMs de alta "
    "resolución para Bolivia, lo que valida el uso de CMIP6 + downscaling "
    "estadístico (CMhyd, BASD, RClimDex/ETCCDI) como aproximación "
    "técnicamente defendible.",
    "Para caudales mínimos se prioriza KGE_log y NSE_1/Q sobre NSE puro, "
    "con el sesgo de Q90/Q95 < 20 % como criterio de aceptación, siguiendo "
    "Pushpalatha et al. (2012) y Smakhtin (2001).",
    "El ensemble final debe incluir al menos un modelo por escenario del "
    "Climate Futures Framework (cálido-seco, cálido-húmedo, frío-seco, "
    "frío-húmedo) para no subestimar la incertidumbre de adaptación "
    "(Whetton et al. 2012; Buytaert et al. 2010).",
    "Reportar explícitamente: lista de modelos retenidos, peso por modelo, "
    "métrica usada, período histórico de validación, dispersión inter-"
    "modelo del cambio proyectado de Pann, ETann y Q90 a 2050 y 2080, y "
    "nivel de confianza por horizonte (alto/medio/bajo) siguiendo el "
    "marco IPCC AR6.",
]
