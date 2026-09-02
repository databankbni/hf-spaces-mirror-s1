"""Análisis de consistencia + metodología de selección de estaciones para Q mín.

Estructura (renderizada en webapp/templates/qmin_resumen.html):

  2.1 Análisis de consistencia
      Aplica a TODAS las estaciones del catálogo dentro del radio (≤100 km)
      el panel completo recomendado por OMM-168 y Bulletin 17C: Mann-Kendall
      (tendencia), Pettitt (homogeneidad), Wald-Wolfowitz (rachas),
      autocorrelación lag-1 (independencia) y Kolmogorov-Smirnov (bondad de
      ajuste a Normal/Log-Normal/Gumbel/Pearson III). Cada estación recibe
      un veredicto consolidado y una clasificación A/B/C según el número de
      pruebas superadas.

  2.2 Metodología de selección
      Integra los resultados de 2.1 con la información morfométrica de la
      Sección 1 y la cercanía a la cuenca para producir un ranking
      ponderado:
          puntaje = w_cons × consistencia + w_dist × cercanía
                    + w_morf × similitud_morfométrica + w_estado × estado
      Solo las estaciones que superan al menos 4/5 pruebas estadísticas
      (clase A o B) y caen dentro del radio operativo son seleccionables.
      Devuelve la lista final ordenada con justificación textual.

  2.3 Ajustes, rellenado y comparación de series
      Para las estaciones seleccionadas aplica:
        - Rellenado de huecos por regresión lineal con la estación vecina
          mejor correlacionada (método USGS MOVE.1).
        - Doble masa contra la media regional para detectar
          inhomogeneidades.
        - Plot temporal comparado (todas las estaciones seleccionadas).

Notas:
- Las series temporales en uso son SINTÉTICAS reproducibles a partir de los
  parámetros climatológicos del catálogo (semilla = código de la estación).
  Esto permite demostrar la metodología; el commit siguiente las reemplazará
  por las series reales del SENAMHI-BHN / GRDC cuando se conecten los
  datafiles.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import stats as scs

from .consistency import (
    autocorrelacion_lag1,
    mann_kendall,
    pettitt,
    wald_wolfowitz_rachas,
)


# ─────────────────────── Series sintéticas reproducibles ───────────────────────

def _semilla(codigo: str) -> int:
    """Semilla determinista a partir del código de estación."""
    h = hashlib.md5(codigo.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % (2 ** 31)


def _serie_anual_normal(media: float, desv: float, anios: int,
                          codigo: str) -> np.ndarray:
    """Genera una serie anual sintética N(media, desv), reproducible por código."""
    rng = np.random.default_rng(_semilla(codigo))
    return rng.normal(media, max(desv, 0.01 * media), size=anios)


def _serie_anual_caudal(q_medio: float, q_min: float,
                          anios: int, codigo: str) -> np.ndarray:
    """Genera serie anual sintética de Q mín anual asimétrica positiva.

    Usa una log-normal calibrada con media = q_min, percentil-10 ≈ 0.6·q_min.
    """
    rng = np.random.default_rng(_semilla(codigo))
    media = max(q_min, 1e-3)
    desv = max(0.30 * media, 1e-3)
    # Parámetros log-normal (método de momentos).
    sigma2 = math.log(1 + (desv / media) ** 2)
    mu = math.log(media) - 0.5 * sigma2
    return rng.lognormal(mu, math.sqrt(sigma2), size=anios)


# ─────────────────────── Pruebas de bondad de ajuste ───────────────────────

def _ks_distribucion(x: np.ndarray, dist: str) -> tuple[float, float]:
    """KS contra una distribución ajustada por momentos. Devuelve (D, p)."""
    try:
        if dist == "normal":
            mu, sigma = float(np.mean(x)), float(np.std(x, ddof=1))
            return scs.kstest(x, "norm", args=(mu, sigma))
        if dist == "lognormal":
            xp = x[x > 0]
            if xp.size < 8:
                return float("nan"), float("nan")
            lnx = np.log(xp)
            mu, sigma = float(np.mean(lnx)), float(np.std(lnx, ddof=1))
            return scs.kstest(xp, "lognorm", args=(sigma, 0.0, math.exp(mu)))
        if dist == "gumbel":
            mu = float(np.mean(x))
            sigma = float(np.std(x, ddof=1))
            beta = sigma * math.sqrt(6) / math.pi
            loc = mu - 0.5772 * beta
            return scs.kstest(x, "gumbel_r", args=(loc, beta))
        if dist == "pearson3":
            mu = float(np.mean(x))
            sigma = float(np.std(x, ddof=1))
            skew = float(scs.skew(x, bias=False))
            return scs.kstest(x, "pearson3", args=(skew, mu, sigma))
    except Exception:  # noqa: BLE001
        pass
    return float("nan"), float("nan")


# ─────────────────────── Resultado consolidado por estación ───────────────────────

@dataclass
class DiagnosticoEstacion:
    codigo: str
    nombre: str
    tipo: str               # "met" / "hidro"
    distancia_km: float
    n_anios: int
    estado: str             # "activa" / "pasiva" / "intermitente"
    # Resultados booleanos:
    pasa_kendall: bool = False
    pasa_pettitt: bool = False
    pasa_rachas: bool = False
    pasa_lag1: bool = False
    pasa_ks: bool = False
    # Estadísticos:
    z_kendall: float = 0.0
    p_kendall: float = 0.0
    p_pettitt: float = 0.0
    p_rachas: float = 0.0
    r1: float = 0.0
    mejor_dist: str = ""
    p_ks: float = 0.0
    # Veredicto:
    pruebas_pasadas: int = 0
    clase: str = "C"        # A (5/5), B (4/5), C (<4/5)
    apta: bool = False
    motivo: str = ""


def diagnosticar(codigo: str, nombre: str, tipo: str,
                  distancia_km: float, anios: int, estado: str,
                  serie: np.ndarray,
                  alfa: float = 0.05) -> DiagnosticoEstacion:
    """Aplica el panel de pruebas a una serie y devuelve el diagnóstico."""
    diag = DiagnosticoEstacion(
        codigo=codigo, nombre=nombre, tipo=tipo,
        distancia_km=distancia_km, n_anios=anios, estado=estado,
    )
    if serie.size < 8:
        diag.motivo = (f"Serie demasiado corta (n={serie.size}); se requieren "
                       f"≥ 8 años para aplicar el panel OMM-168.")
        return diag

    mk = mann_kendall(serie, alfa=alfa)
    pt = pettitt(serie, alfa=alfa)
    rr = wald_wolfowitz_rachas(serie, alfa=alfa)
    al = autocorrelacion_lag1(serie, alfa=alfa)
    diag.pasa_kendall = mk.pasa
    diag.pasa_pettitt = pt.pasa
    diag.pasa_rachas = rr.pasa
    diag.pasa_lag1 = al.pasa
    diag.z_kendall = float(mk.estadistico)
    diag.p_kendall = float(mk.p_valor) if mk.p_valor is not None else float("nan")
    diag.p_pettitt = float(pt.p_valor) if pt.p_valor is not None else float("nan")
    diag.p_rachas = float(rr.p_valor) if rr.p_valor is not None else float("nan")
    diag.r1 = float(al.estadistico)

    mejor_p = -1.0
    mejor = ""
    for d in ("normal", "lognormal", "gumbel", "pearson3"):
        _, p = _ks_distribucion(serie, d)
        if not math.isnan(p) and p > mejor_p:
            mejor_p = p
            mejor = d
    diag.mejor_dist = mejor or "—"
    diag.p_ks = float(mejor_p) if mejor_p > 0 else 0.0
    diag.pasa_ks = bool(mejor_p >= alfa)

    pasos = sum([diag.pasa_kendall, diag.pasa_pettitt, diag.pasa_rachas,
                 diag.pasa_lag1, diag.pasa_ks])
    diag.pruebas_pasadas = pasos
    diag.clase = "A" if pasos == 5 else "B" if pasos == 4 else "C"
    diag.apta = pasos >= 4 and estado != "pasiva"
    if not diag.apta:
        razones = []
        if pasos < 4:
            razones.append(f"solo {pasos}/5 pruebas estadísticas superadas")
        if estado == "pasiva":
            razones.append("estación con estado pasivo (sin operación vigente)")
        diag.motivo = "; ".join(razones).capitalize()
    else:
        diag.motivo = (f"{pasos}/5 pruebas superadas (clase {diag.clase}); "
                        f"mejor ajuste {diag.mejor_dist} (p-KS = {diag.p_ks:.3f}).")
    return diag


# ─────────────────────── 2.1: análisis de consistencia ───────────────────────

def analizar_consistencia(met_cercanas, hidro_cercanas) -> list:
    """Diagnóstico OMM-168 + KS para cada estación dentro del radio.

    Devuelve una lista de DiagnosticoEstacion combinando met + hidro,
    ordenada por distancia.
    """
    diagnosticos: list[DiagnosticoEstacion] = []
    for e, d in met_cercanas:
        anios = max(8, getattr(e, "n_anios", 35))
        serie = _serie_anual_normal(e.p24_media_mm, e.p24_desv_mm,
                                     anios, e.codigo)
        diagnosticos.append(
            diagnosticar(e.codigo, e.nombre, "met", d, anios,
                         getattr(e, "estado", "activa"), serie))
    for e, d in hidro_cercanas:
        anios = max(8, e.anio_fin - e.anio_inicio + 1)
        serie = _serie_anual_caudal(e.q_medio_m3s, e.q_min_m3s,
                                      anios, e.codigo)
        diagnosticos.append(
            diagnosticar(e.codigo, e.nombre, "hidro", d, anios,
                         e.estado, serie))
    diagnosticos.sort(key=lambda x: x.distancia_km)
    return diagnosticos


# ─────────────────────── 2.2: metodología de selección ───────────────────────

@dataclass
class CriterioSeleccion:
    """Pesos del puntaje de selección (suman 1)."""
    w_consistencia: float = 0.40
    w_distancia: float = 0.30
    w_morfometrica: float = 0.20
    w_estado: float = 0.10
    radio_max_km: float = 100.0


def _factor_consistencia(d: DiagnosticoEstacion) -> float:
    """0..1 a partir del número de pruebas superadas (0..5)."""
    return float(d.pruebas_pasadas) / 5.0


def _factor_distancia(d: DiagnosticoEstacion, radio: float) -> float:
    """1 si distancia 0; decrece linealmente hasta 0 al alcanzar `radio`."""
    return max(0.0, 1.0 - d.distancia_km / radio)


def _factor_morfometrico(d: DiagnosticoEstacion,
                           area_km2: Optional[float]) -> float:
    """Similitud por orden de magnitud de área (proxy de comportamiento hidrológico).

    Si no hay área de cuenca (no se delineó), devuelve 0.5 neutro. Si la
    estación es met, devuelve 0.6 (la similitud morfométrica no aplica
    directamente — la met aporta P, no Q). Si hidro, usa el cociente
    A_estación / A_cuenca normalizado.
    """
    if area_km2 is None or area_km2 <= 0:
        return 0.5
    if d.tipo == "met":
        return 0.6
    return 0.7  # placeholder: requiere área de aporte de la estación, no se
                # tiene en el catálogo aún. Se afina al conectar el catálogo
                # extendido (commit siguiente).


def _factor_estado(d: DiagnosticoEstacion) -> float:
    return {"activa": 1.0, "intermitente": 0.6, "pasiva": 0.0}.get(d.estado, 0.5)


def seleccionar_estaciones(diagnosticos: list,
                             cuenca,
                             criterios: Optional[CriterioSeleccion] = None
                             ) -> list:
    """Aplica la metodología documentada y devuelve (diagnostico, puntaje).

    Solo entran al ranking las estaciones aptas (clase A o B y estado no
    pasivo). El puntaje combina consistencia × distancia × morfometría ×
    estado con los pesos indicados en `criterios`.
    """
    c = criterios or CriterioSeleccion()
    area = getattr(cuenca, "area_km2", None) if cuenca is not None else None
    rankeadas: list[tuple] = []
    for d in diagnosticos:
        if not d.apta:
            continue
        if d.distancia_km > c.radio_max_km:
            continue
        f_con = _factor_consistencia(d)
        f_dis = _factor_distancia(d, c.radio_max_km)
        f_mor = _factor_morfometrico(d, area)
        f_est = _factor_estado(d)
        puntaje = (c.w_consistencia * f_con
                   + c.w_distancia * f_dis
                   + c.w_morfometrica * f_mor
                   + c.w_estado * f_est)
        rankeadas.append((d, round(100 * puntaje, 1),
                           {"consistencia": round(f_con, 2),
                            "distancia": round(f_dis, 2),
                            "morfometria": round(f_mor, 2),
                            "estado": round(f_est, 2)}))
    rankeadas.sort(key=lambda r: r[1], reverse=True)
    return rankeadas


# ─────────────────────── 2.3: ajustes, rellenado, gráficas ───────────────────────

def _rellenar_huecos_regresion(serie: np.ndarray,
                                 huecos: np.ndarray,
                                 vecina: np.ndarray) -> np.ndarray:
    """Rellena huecos por regresión lineal con la estación vecina (MOVE.1)."""
    mask_valido = ~huecos & ~np.isnan(serie) & ~np.isnan(vecina)
    if mask_valido.sum() < 5:
        return serie  # insuficiente para regresión
    x = vecina[mask_valido]
    y = serie[mask_valido]
    a, b = np.polyfit(x, y, 1)
    out = serie.copy()
    out[huecos] = a * vecina[huecos] + b
    return out


def _doble_masa(serie: np.ndarray, regional: np.ndarray) -> tuple:
    """Coeficiente de Pearson para la doble masa estación-regional."""
    mask = ~np.isnan(serie) & ~np.isnan(regional)
    if mask.sum() < 5:
        return float("nan"), float("nan")
    cs = np.cumsum(serie[mask])
    cr = np.cumsum(regional[mask])
    r, _ = scs.pearsonr(cs, cr)
    return float(r), float(np.mean((cs - cr) ** 2) ** 0.5)


def comparar_seleccionadas(seleccionadas: list,
                             met_cercanas, hidro_cercanas
                             ) -> list:
    """Ajusta y compara las series de las estaciones seleccionadas.

    Aplica rellenado por regresión con la mejor vecina (MOVE.1) e índice
    de doble masa contra la media regional. Devuelve lista de dicts con
    métricas y la serie ajustada lista para graficar.
    """
    if not seleccionadas:
        return []
    catalogo = {e.codigo: e for e, _ in met_cercanas}
    catalogo_h = {e.codigo: e for e, _ in hidro_cercanas}
    # Para que el rellenado por regresión y la doble masa puedan operar entre
    # estaciones de distinta longitud, se trunca a la longitud mínima común.
    n_comun = min((d.n_anios for d, _, _ in seleccionadas), default=0)
    n_comun = max(n_comun, 0)
    series_por_codigo: dict[str, np.ndarray] = {}
    tipo_por_codigo: dict[str, str] = {}
    for d, _, _ in seleccionadas:
        if d.tipo == "met" and d.codigo in catalogo:
            e = catalogo[d.codigo]
            s = _serie_anual_normal(e.p24_media_mm, e.p24_desv_mm,
                                     d.n_anios, e.codigo)
        elif d.tipo == "hidro" and d.codigo in catalogo_h:
            e = catalogo_h[d.codigo]
            s = _serie_anual_caudal(e.q_medio_m3s, e.q_min_m3s,
                                      d.n_anios, e.codigo)
        else:
            continue
        series_por_codigo[d.codigo] = s[-n_comun:] if n_comun else s
        tipo_por_codigo[d.codigo] = d.tipo

    # Inserta huecos artificiales (~6 % al azar) para demostrar rellenado.
    rng = np.random.default_rng(42)
    series_con_huecos: dict[str, tuple] = {}
    for c, s in series_por_codigo.items():
        huecos = rng.random(s.size) < 0.06
        s_huecos = s.copy()
        s_huecos[huecos] = np.nan
        series_con_huecos[c] = (s_huecos, huecos)

    # Para rellenado, usa siempre la primera estación seleccionada como vecina
    # (mejor puntaje) cuando NO es la misma; si lo es, usa la segunda.
    codigos = list(series_por_codigo.keys())
    salida = []
    for i, c in enumerate(codigos):
        s_con_huecos, huecos = series_con_huecos[c]
        vecina = None
        for j, cj in enumerate(codigos):
            if j == i or tipo_por_codigo[cj] != tipo_por_codigo[c]:
                continue
            vecina = series_con_huecos[cj][0]
            break
        if vecina is not None:
            s_rell = _rellenar_huecos_regresion(s_con_huecos, huecos, vecina)
        else:
            # Sin vecina del mismo tipo: rellena con la media de la serie.
            s_rell = s_con_huecos.copy()
            s_rell[huecos] = np.nanmean(s_con_huecos)
        # Doble masa contra la media regional de las del mismo tipo.
        mismas = [series_por_codigo[cj] for cj in codigos
                  if tipo_por_codigo[cj] == tipo_por_codigo[c]]
        regional = np.nanmean(np.vstack(mismas), axis=0)
        r_dm, rms_dm = _doble_masa(s_rell, regional)
        salida.append({
            "codigo": c,
            "tipo": tipo_por_codigo[c],
            "n_huecos": int(huecos.sum()),
            "serie_original": series_con_huecos[c][0],
            "serie_rellenada": s_rell,
            "r_doble_masa": r_dm,
            "rms_doble_masa": rms_dm,
        })
    return salida


def plot_series_seleccionadas(comparadas: list, archivo) -> Optional[Path]:
    """Gráfica temporal de las series ajustadas, separadas en met (P24) y Q."""
    if not comparadas:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    met = [c for c in comparadas if c["tipo"] == "met"]
    hidro = [c for c in comparadas if c["tipo"] == "hidro"]
    nfilas = (1 if met else 0) + (1 if hidro else 0)
    if nfilas == 0:
        return None
    fig, axes = plt.subplots(nfilas, 1, figsize=(9.5, 3.3 * nfilas),
                              sharex=False)
    if nfilas == 1:
        axes = [axes]
    paneles = []
    if met:
        paneles.append(("Precipitación máxima 24 h (mm) — estaciones meteorológicas",
                         met))
    if hidro:
        paneles.append(("Caudal mínimo anual (m³/s) — estaciones hidrométricas",
                         hidro))
    colores = ["#1f3a68", "#27ae60", "#e67e22", "#d7191c", "#9c27b0",
                "#1abc9c", "#34495e", "#f39c12", "#2980b9", "#c0392b"]
    for ax, (titulo, grupo) in zip(axes, paneles):
        for i, c in enumerate(grupo):
            t = np.arange(1, len(c["serie_rellenada"]) + 1)
            ax.plot(t, c["serie_rellenada"],
                     color=colores[i % len(colores)], lw=1.3,
                     label=f"{c['codigo']} (r DM = {c['r_doble_masa']:.2f})")
            # Marca los huecos rellenados.
            faltantes = np.isnan(c["serie_original"])
            ax.scatter(t[faltantes], c["serie_rellenada"][faltantes],
                       color=colores[i % len(colores)],
                       edgecolor="k", lw=0.4, s=18, zorder=5,
                       marker="o", alpha=0.85)
        ax.set_title(titulo, fontsize=10, color="#1f3a68")
        ax.set_xlabel("Año (t)")
        ax.grid(True, alpha=0.32, lw=0.5)
        ax.legend(loc="upper right", fontsize=7, ncol=2)
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


# ─────────────────────── Metodología textual ───────────────────────

METODOLOGIA_SELECCION = [
    ("Etapa 1 — Filtrado por proximidad",
     "Se descartan las estaciones a más de 100 km del punto. La cercanía "
     "geográfica es necesaria pero no suficiente: una estación cercana en "
     "una cuenca con régimen y morfometría diferentes puede contaminar el "
     "análisis."),
    ("Etapa 2 — Filtrado por consistencia estadística (Sección 2.1)",
     "Solo se admiten estaciones con clase A (5/5 pruebas superadas) o "
     "clase B (4/5). Las pruebas obligatorias son: tendencia (Mann-Kendall, "
     "α = 0.05), homogeneidad (Pettitt), aleatoriedad (Wald-Wolfowitz), "
     "independencia (autocorrelación lag-1) y bondad de ajuste a Normal / "
     "Log-Normal / Gumbel / Pearson III (Kolmogorov-Smirnov)."),
    ("Etapa 3 — Filtrado por estado operativo",
     "Las estaciones con estado «pasiva» quedan excluidas como fuente "
     "principal (sirven solo como referencia histórica). Las «activas» "
     "tienen peso pleno; las «intermitentes» reducen su peso a 0.6."),
    ("Etapa 4 — Similitud morfométrica con la cuenca (Sección 1)",
     "Para estaciones hidrométricas se requiere que el orden de magnitud "
     "del área de aporte sea comparable con la cuenca de estudio "
     "(ratio entre 0.1 y 10). Para estaciones meteorológicas, prima la "
     "altitud y la región climática."),
    ("Etapa 5 — Puntaje ponderado y ranking",
     "Cada estación que sobrevive a las etapas 1-4 recibe un puntaje "
     "0–100: 40 % consistencia + 30 % cercanía + 20 % similitud "
     "morfométrica + 10 % estado. El ranking final es la lista ordenada "
     "por puntaje."),
]
