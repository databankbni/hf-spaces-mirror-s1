"""Orquestación completa del análisis CURVAS IDF v1.2.

`ejecutar_pipeline` corre todo el flujo (estación, satelital, comparación,
frecuencias, IDF múltiple, Tc, hietogramas, HEC-HMS), genera los gráficos y el
PDF, y devuelve un bundle `ResultadoCompleto`. Lo usan webapp, GUI y CLI para
garantizar lógica idéntica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

import pandas as pd

from .comparacion import DecisionFuente, comparar_y_decidir
from .concentracion import TcAdoptado, adoptar_tc, calcular_todas as _calc_tc
from .data import estacion_mas_cercana, serie_anual_maxima_sintetica
from .disaggregation import (DURACIONES_DEFAULT_MIN, desagregar_dyck_peschke,
                                exponente_dyck_peschke)
from .hechms import resumen_hec_hms
from .hietograma import bloques_alternos, chicago, scs_tipo2
from .idf import ajustar_sherman
from .idf_models import ajustar_todos_los_modelos, recomendar_modelo_por_datos
from .morfologia import estimar_morfologia_desde_coordenadas
from .obras import obtener_tipo_obra
from .plotting import (
    plot_ajuste_distribucion,
    plot_correlacion,
    plot_hietograma_comparado,
    plot_modelo_idf_curvas,
    plot_modelos_idf,
    plot_serie_anual_maxima,
    plot_series_satelitales,
    plot_tiempo_concentracion,
)
from .proyecto import DatosProyecto
from .report import generar_pdf
from .satelital import obtener_series_satelitales
from .stats import (
    PERIODOS_RETORNO_DEFAULT,
    ajustar_todas,
    cuantiles_para_periodos_retorno,
    seleccionar_mejor_ajuste,
)
from .summary import estadisticos_descriptivos


@dataclass
class ResultadoCompleto:
    proyecto: DatosProyecto
    tipo_obra: object
    T_diseno: int
    lat: float
    lon: float
    estacion: object
    dist_km: float
    serie_estacion: pd.DataFrame
    series_satelitales: list
    decision: DecisionFuente
    serie: pd.DataFrame          # serie adoptada
    desc: object
    pruebas: list
    ajustes: list
    mejor_ajuste: object
    cuantiles: pd.DataFrame
    exp_dp: float
    idf_largo: pd.DataFrame
    modelos: list
    modelo_recomendado: object
    justificacion_modelo: str
    modelos_preferidos: list
    resolucion_datos: str
    modo_ligero: bool
    modelo_sherman: object
    morfologia: object
    tc_resultados: list
    tc_adoptado: TcAdoptado
    hietogramas: dict
    hechms: object
    # Polígono de cuenca delineado (Nx2 array [lon, lat]) cuando el watershed
    # MERIT Hydro tuvo éxito. None si se cayó a HydroBASINS o sintético.
    cuenca_poligono: object = None
    # Análisis morfológico completo (AnalisisMorfologico) o None.
    analisis_morf: object = None
    # CN y C ponderados de los mapas reales; C del evento de diseño (SCS Q/P).
    cn_ponderado: float | None = None
    c_ponderado: float | None = None
    c_evento: float | None = None
    p24_diseno_mm: float | None = None
    # Susceptibilidad a la inundación (mapa 9.9, índice HAND): % del área de
    # cuenca con susceptibilidad alta/muy alta y HAND medio (m).
    inund_area_alta_pct: float | None = None
    hand_medio_m: float | None = None
    # Período de retorno de verificación estructural (caso pésimo), p. ej. el
    # tipo de obra «Análisis de riesgo ABC»: T_diseno=200, T_verificacion=300.
    T_verificacion: int | None = None
    # Caudal máximo Q(T) por 5 métodos × 9 períodos de retorno (§11).
    qmax_tabla: object = None
    qmax_entrada: object = None
    # Cálculo de tirante (calado) tipo HEC-RAS 1D (hidraulica_fluvial.ResultadoTirante).
    tirante: object = None
    # Hietogramas por TODOS los períodos de retorno (§12): {T: {metodo: Hietograma}}.
    # Métodos: bloques, scs, chicago, y huff cuando A > 25 km².
    hietogramas_por_T: dict = field(default_factory=dict)
    aplica_huff: bool = False
    metodos_hieto: list = field(default_factory=list)
    # Modelación HEC-HMS-like (§13): hietograma seleccionado + hidrogramas por T.
    hec_params: object = None
    hec_metodo_hieto: str = ""
    hec_justificacion: str = ""
    hec_hidrogramas_por_T: dict = field(default_factory=dict)
    graficos: dict = field(default_factory=dict)
    # Pendiente media de LADERA (terreno) del mapa 9.6 (Terrain.slope
    # COP-DEM). Descriptiva — NO se usa para el Tc (eso usa la pendiente
    # del cauce en morfologia.pendiente_media_mm).
    pendiente_ladera_pct: float | None = None
    # Años de P24max descartados por depuración de outliers (errores de dato).
    anios_descartados: list = field(default_factory=list)
    # Exponente de Dyck-Peschke usado y región climática que lo determinó.
    exp_dyck_peschke: float = 0.25
    region_dyck_peschke: str = ""
    # Advertencia si el P24(T=100) cae fuera del rango físico regional (o None).
    p24_validacion_regional: dict | None = None
    # True si se aplicó la corrección de Hershfield ×1.13 (fuente terrestre).
    hershfield_aplicado: bool = False
    # Corrección de piso regional: dict {region, rango_mm, p24_100_observado,
    # p24_100_corregido, factor} cuando el P24(100) satelital cae por debajo
    # del rango físico regional y se escaló la serie; None si no se aplicó.
    correccion_regional: dict | None = None
    # Duración (min) de la tormenta de diseño usada en la modelación HEC-HMS
    # (§13): 24 h (1440 min) con distribución SCS Tipo II, estándar TR-55.
    hec_duracion_min: float = 1440.0
    # Análisis de sensibilidad ±20 % (CN, Tc, n) → Q y tirante (sensibilidad.py).
    sensibilidad: object = None
    # Sensibilidad hidráulica-socavación ±20/40 % (Q, n, S, D50) → y, V, ys, viga.
    sensibilidad_hidraulica: object = None
    # Prueba de Smirnov-Grubbs de valores atípicos sobre la serie (dict) o None.
    grubbs: dict | None = None
    # Análisis de doble masa (consistencia de la fuente) — ResultadoDobleMasa.
    doble_masa: object = None
    # Red de estaciones SENAMHI de referencia concurrentes (consistencia).
    red_estaciones: object = None
    # Dimensionamiento preliminar de obras de protección fluvial (§14.8).
    proteccion: object = None
    # Diseño de alcantarillas de drenaje vial menor (FHWA HDS-5), solo cuando
    # el tipo de obra es "drenaje_vial_menor".
    alcantarillas: object = None
    # Resultados reales de HEC-RAS leídos de un HDF subido por el usuario
    # (ras-commander / h5py). None si no se aportó modelo externo.
    hecras_resultados: object = None
    # Captación de riego menor (canal, desarenador, bocatomas, protección),
    # solo cuando el tipo de obra es "riego_pequeno".
    riego: object = None
    # Sensibilidad del caudal de diseño al cambio climático (todos los informes).
    sensibilidad_cc: object = None
    # Corrección del CN por pendiente (Williams 1995): {cn2, cn2s, cn3, pend}.
    cn_correccion: dict | None = None
    # Reconciliación morfométrica a fuente única (relieve y pendiente de cauce).
    reconciliacion_morf: dict | None = None
    # Cuantiles y serie ANTES de la corrección de piso regional (trazabilidad).
    cuantiles_sin_correccion: object = None
    serie_sin_correccion: object = None
    # Intervalos de confianza de los cuantiles por bootstrap (DataFrame).
    ic_cuantiles: object = None
    # True si el análisis se hizo sobre la serie OBSERVADA cargada por el usuario.
    serie_observada_usada: bool = False
    pdf: Path | None = None


class _SaltarPisoRegional(Exception):
    """Sentinela interna: omite la corrección de piso regional (serie observada)."""


def ejecutar_pipeline(
    out_dir,
    *,
    proyecto: DatosProyecto,
    lat: float,
    lon: float,
    tipo_obra_clave: str = "carretera_puente",
    T_diseno: int | None = None,
    anios: int = 35,
    semilla: int = 42,
    exp_dp: float = 0.25,
    criterio: str = "ks",
    resolucion_datos: str = "diaria",
    anio_ini_sat: int = 1991,
    anio_fin_sat: int = 2020,
    cn_disponible: bool = False,
    modo_ligero: bool = False,
    generar_archivos: bool = True,
    params_puente: dict | None = None,
    params_alcantarilla: dict | None = None,
    params_riego: dict | None = None,
    serie_observada: object = None,
    hecras_hdf: str | None = None,
) -> ResultadoCompleto:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    tipo_obra = obtener_tipo_obra(tipo_obra_clave)
    T_diseno = int(T_diseno) if T_diseno else tipo_obra.t_recomendado

    # 1. Estación (vecino más cercano)
    estacion, dist = estacion_mas_cercana(lat, lon)

    # 2. Series satelitales REALES (CHIRPS / NASA POWER / Open-Meteo / GHCN-D).
    #    HYDROFRA v1.3: SIEMPRE se descargan (incluso en modo ligero, que solo
    #    afecta a las simulaciones HEC-HMS y plots pesados, no a los datos de
    #    precipitación). La serie sintética de la estación se genera solo como
    #    referencia de correlación, nunca como fuente de cálculo.
    serie_estacion = serie_anual_maxima_sintetica(estacion, anios, semilla=semilla)
    series_sat = obtener_series_satelitales(
        lat, lon, anio_ini_sat, anio_fin_sat,
        estacion.p24_media_mm, estacion.p24_desv_mm,
    )

    # 3. Comparación / decisión -> serie REAL adoptada.
    decision = comparar_y_decidir(serie_estacion, series_sat)
    # 3.0 SERIE OBSERVADA APORTADA POR EL USUARIO (prioridad máxima). Si el
    #     ingeniero cargó su serie certificada de SENAMHI, se adopta como fuente
    #     y se SALTA la comparación satelital: el análisis pasa a ser sobre
    #     datos observados (cierra las observaciones §3.1/§5 del dictamen). Las
    #     métricas satelitales se conservan solo como contraste informativo.
    serie_observada_usada = False
    if serie_observada is not None:
        try:
            _dfobs = serie_observada
            if not isinstance(_dfobs, pd.DataFrame):
                from .serie_usuario import parsear_serie_observada
                _dfobs = parsear_serie_observada(str(serie_observada))
            if (_dfobs is not None and len(_dfobs) >= 10
                    and {"anio", "p24_mm"}.issubset(_dfobs.columns)):
                decision = DecisionFuente(
                    fuente_adoptada="SENAMHI observado (serie cargada por el "
                                    "usuario)",
                    serie_adoptada=_dfobs.copy(),
                    justificacion=(
                        "Se adoptó la serie de P24max OBSERVADA aportada por el "
                        "proyectista (registro de SENAMHI). El análisis de "
                        "frecuencia, la IDF, los caudales, el tirante y la "
                        "socavación se calculan sobre estos datos observados, "
                        "no sobre productos satelitales. Debe adjuntarse la "
                        "certificación de SENAMHI y los metadatos de la(s) "
                        "estación(es) en el Anexo A."),
                    metricas=list(getattr(decision, "metricas", []) or []),
                    mejor_satelital=getattr(decision, "mejor_satelital", ""),
                    tiene_dato_real=True)
                serie_observada_usada = True
                print(f"[pipeline] serie OBSERVADA del usuario adoptada: "
                      f"{len(_dfobs)} años ({int(_dfobs['anio'].min())}–"
                      f"{int(_dfobs['anio'].max())})", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] serie observada inválida, se ignora: {e}",
                  flush=True)
    if not getattr(decision, "tiene_dato_real", True):
        raise RuntimeError(
            "No se obtuvo ninguna fuente de precipitación REAL (CHIRPS, NASA "
            "POWER, Open-Meteo ERA5, SENAMHI) para este sitio. HYDROFRA no "
            "genera análisis con series sintéticas. Reintentá en unos minutos "
            "— suele ser un problema transitorio de las APIs de datos. También "
            "podés cargar tu propia serie observada de SENAMHI.")
    serie = decision.serie_adoptada.reset_index(drop=True)

    # 3b. Depuración de outliers: descarta P24max anuales físicamente
    #     imposibles (errores de dato de la fuente), usando la climatología
    #     oficial SENAMHI de la estación como referencia. NO completa ni
    #     inventa datos — solo elimina errores groseros que inflarían los
    #     cuantiles P24(T) y, en cascada, los caudales. (Caso real: un
    #     P24max de 307 mm en Tarija, cuya P24 media es ~45 mm.)
    from .depuracion import depurar_serie_maximos
    serie, anios_descartados = depurar_serie_maximos(
        serie, getattr(estacion, "p24_media_mm", None),
        getattr(estacion, "p24_desv_mm", None))
    if anios_descartados:
        print(f"[pipeline] depuración P24max: descartados "
               f"{len(anios_descartados)} año(s) con valores aberrantes: "
               + ", ".join(f"{d['anio']}={d['p24_mm']}mm"
                            for d in anios_descartados), flush=True)

    # 3c. Corrección de Hershfield (intervalo fijo). Los máximos anuales de
    #     acumulados diarios leídos a hora fija (08:00, caso de las estaciones
    #     terrestres SENAMHI/GHCN-D) subestiman el verdadero máximo de 24 h
    #     móvil en ~13 % (Weiss 1964; skill hidrología Bolivia). Se aplica
    #     ×1.13 SOLO a fuentes de estación terrestre — NO a productos grillados
    #     (CHIRPS/ERA5/NASA), cuya estructura temporal es distinta.
    hershfield_aplicado = False
    fuente_adop = getattr(decision, "fuente_adoptada", "") or ""
    if any(t in fuente_adop for t in ("GHCN", "Estación", "estación")):
        serie = serie.copy()
        serie["p24_mm"] = (serie["p24_mm"] * 1.13).round(2)
        hershfield_aplicado = True
        print(f"[pipeline] corrección de Hershfield ×1.13 aplicada "
               f"(fuente terrestre a hora fija: {fuente_adop})", flush=True)

    # 3d. Corrección de PISO REGIONAL. Las fuentes grilladas/satelitales
    #     (CHIRPS/ERA5/IMERG) suavizan los extremos y subestiman el Pmax24h de
    #     cola alta, sobre todo en Yungas y tierras bajas. Se ajusta un modelo
    #     preliminar; si el P24(T=100) cae POR DEBAJO del límite inferior del
    #     rango físico regional (skill hidrología Bolivia), se escala TODA la
    #     serie por el factor que lleva el P24(100) a ese piso. Como el escalado
    #     es multiplicativo, toda la cadena (estadísticos, ajuste, cuantiles,
    #     IDF, hietogramas, HEC-HMS, Q, tirante y socavación) queda corregida de
    #     forma consistente. El factor se acota a 3.0× para no sobrecorregir.
    correccion_regional = None
    cuantiles_sin_correccion = None
    serie_sin_correccion = None
    # Con SERIE OBSERVADA aportada por el usuario NO se aplica el piso regional:
    # los datos observados son la verdad y no deben escalarse. La corrección
    # existe solo para compensar la subestimación de los productos satelitales.
    try:
        if serie_observada_usada:
            raise _SaltarPisoRegional
        from .depuracion import RANGO_P24_T100_REGION
        from .pisos_ecologicos import clasificar as _clasificar_piso
        _aj_prelim = ajustar_todas(serie["p24_mm"].to_numpy())
        _mejor_prelim = seleccionar_mejor_ajuste(_aj_prelim, criterio=criterio)
        _cuant_prelim = cuantiles_para_periodos_retorno(
            _mejor_prelim, PERIODOS_RETORNO_DEFAULT)
        _f100 = _cuant_prelim.loc[_cuant_prelim["T_anios"] == 100]
        if len(_f100):
            _p24_100_obs = float(_f100["p24_mm"].iloc[0])
            _alt = float(getattr(estacion, "altitud_msnm", 0)) or None
            _piso = _clasificar_piso(lat, lon, _alt)
            _rango = RANGO_P24_T100_REGION.get(getattr(_piso, "clave", ""))
            if _rango and _p24_100_obs > 0 and _p24_100_obs < float(_rango[0]):
                _lo = float(_rango[0])
                _factor = min(_lo / _p24_100_obs, 3.0)
                if _factor > 1.001:
                    # Se conserva la serie y los cuantiles SIN corregir para
                    # publicar la comparación completa antes/después que exige
                    # la revisión técnica (trazabilidad del factor).
                    cuantiles_sin_correccion = _cuant_prelim.copy()
                    serie_sin_correccion = serie.copy()
                    serie = serie.copy()
                    serie["p24_mm"] = (serie["p24_mm"] * _factor).round(2)
                    correccion_regional = {
                        "region": getattr(_piso, "nombre", ""),
                        "clave_region": getattr(_piso, "clave", ""),
                        "altitud_m": _alt,
                        "distribucion_prelim": _mejor_prelim.nombre,
                        "rango_mm": [float(_rango[0]), float(_rango[1])],
                        "p24_100_observado": round(_p24_100_obs, 1),
                        "p24_100_corregido": round(_p24_100_obs * _factor, 1),
                        "media_serie_antes": round(
                            float(serie_sin_correccion["p24_mm"].mean()), 2),
                        "media_serie_despues": round(
                            float(serie["p24_mm"].mean()), 2),
                        "max_serie_antes": round(
                            float(serie_sin_correccion["p24_mm"].max()), 2),
                        "max_serie_despues": round(
                            float(serie["p24_mm"].max()), 2),
                        "factor": round(_factor, 3),
                    }
                    print(f"[pipeline] corrección de piso regional "
                           f"×{_factor:.2f} aplicada: P24(100) {_p24_100_obs:.0f}"
                           f"→{_p24_100_obs*_factor:.0f} mm (piso {_rango[0]} mm, "
                           f"{getattr(_piso, 'nombre', '')})", flush=True)
    except _SaltarPisoRegional:
        pass   # serie observada: no se aplica piso regional (a propósito)
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] corrección de piso regional falló: {e}", flush=True)

    # 4. Estadísticos + consistencia (sobre la serie ya corregida)
    from .consistency import correr_todas as _consist
    desc = estadisticos_descriptivos(serie["p24_mm"].to_numpy())
    pruebas = _consist(serie["p24_mm"].to_numpy())

    # 5. Frecuencias + cuantiles
    ajustes = ajustar_todas(serie["p24_mm"].to_numpy())
    mejor = seleccionar_mejor_ajuste(ajustes, criterio=criterio)
    cuantiles = cuantiles_para_periodos_retorno(mejor, PERIODOS_RETORNO_DEFAULT)
    # Prueba de Smirnov-Grubbs de valores atípicos (bondad de datos, EDTP-ABC).
    try:
        from .stats import prueba_grubbs
        grubbs = prueba_grubbs(serie["p24_mm"].to_numpy())
    except Exception:  # noqa: BLE001
        grubbs = None
    # Intervalos de confianza de los cuantiles por bootstrap. Con n ≈ 30 años la
    # extrapolación a T altos tiene incertidumbre elevada y no puede publicarse
    # como valor determinista (observación §3.2 de la revisión técnica).
    ic_cuantiles = None
    try:
        from .stats import intervalos_confianza_cuantiles
        _T_ic = sorted({10, 25, 50, 100, int(T_diseno)}
                       | ({int(T_verif_ic)} if (T_verif_ic := getattr(
                           tipo_obra, "t_verificacion", None)) else set()))
        ic_cuantiles = intervalos_confianza_cuantiles(
            serie["p24_mm"].to_numpy(), _T_ic, criterio=criterio,
            n_boot=int(os.environ.get("HYDROFRA_BOOTSTRAP_N", "200")))
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] intervalos de confianza fallaron: {e}", flush=True)
    # Red de estaciones SENAMHI de referencia concurrentes (consistencia
    # multiestación, EDTP-ABC): las K estaciones más cercanas del catálogo.
    try:
        from .estaciones_multi import construir_red_estaciones
        red_estaciones = construir_red_estaciones(lat, lon, k=3,
                                                  n_anios=len(serie),
                                                  semilla=semilla)
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] red de estaciones falló: {e}", flush=True)
        red_estaciones = None
    # Doble masa: consistencia de la fuente adoptada vs promedio regional. La
    # referencia son las ESTACIONES vecinas (red multiestación) si existen; si
    # no, las otras fuentes grilladas independientes (curva de doble masa).
    try:
        from .doble_masa import analisis_doble_masa
        _fad = getattr(decision, "fuente_adoptada", "") or ""
        _refs_est = (red_estaciones.series_referencia
                     if red_estaciones is not None else [])
        _refs_sat = [s for s in series_sat
                     if not (s.fuente in _fad or (_fad and _fad in s.fuente))]
        _refs = _refs_est if _refs_est else _refs_sat
        doble_masa = analisis_doble_masa(serie, _refs,
                                         fuente_adoptada=_fad or "adoptada")
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] doble masa falló: {e}", flush=True)
        doble_masa = None

    # 5b. Sanity-check del cuantil P24(T=100) contra el rango físico regional
    #     (skill hidrología Bolivia). Tras la corrección de piso debería caer
    #     dentro de rango; si aún no, se advierte en el informe.
    p24_validacion = None
    try:
        from .depuracion import validar_p24_regional
        fila100 = cuantiles.loc[cuantiles["T_anios"] == 100]
        if len(fila100):
            p24_100 = float(fila100["p24_mm"].iloc[0])
            alt = float(getattr(estacion, "altitud_msnm", 0)) or None
            p24_validacion = validar_p24_regional(p24_100, lat, lon, alt)
            if p24_validacion:
                print(f"[pipeline] ⚠ P24(100) fuera de rango regional: "
                       f"{p24_validacion['mensaje']}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] validación P24 regional falló: {e}", flush=True)

    # 6. Desagregación + modelos IDF. El exponente de Dyck-Peschke se ajusta
    #    a la región climática (altiplano 0.22, valles 0.25, yungas 0.29,
    #    llanos 0.27) salvo que el usuario fije uno distinto al default 0.25.
    exp_usado = exp_dp
    region_dp = "valor del formulario"
    if abs(exp_dp - 0.25) < 1e-9:   # default → usar el regional
        alt = float(getattr(estacion, "altitud_msnm", 0)) or None
        exp_usado, region_dp = exponente_dyck_peschke(lat, lon, alt)
        if abs(exp_usado - 0.25) > 1e-9:
            print(f"[pipeline] Dyck-Peschke regional: exp={exp_usado} "
                   f"({region_dp})", flush=True)
    idf_largo = desagregar_dyck_peschke(cuantiles, DURACIONES_DEFAULT_MIN, exp_usado)
    modelos = ajustar_todos_los_modelos(idf_largo)
    modelo_rec, just_modelo, preferidos = recomendar_modelo_por_datos(resolucion_datos, modelos)
    modelo_sherman = ajustar_sherman(idf_largo)

    # 7. Tiempo de concentración (procedimiento de 5 pasos + validación de forma)
    # Cascada de precisión decreciente para la morfología:
    #   (a) Watershed MERIT Hydro real D8 desde el punto → cuenca de aporte
    #       verdadera al punto + polígono delineado a 90 m.
    #   (b) HydroBASINS L12 → sub-cuenca predefinida que contiene al punto
    #       (área correcta solo si el punto cae cerca del outlet de la sub-cuenca).
    #   (c) Estimación sintética por ley de Hack (solo cuando GEE no responde).
    from .gee import (morfologia_desde_gee, cn_desde_poligono,
                       cn_ponderado_desde_poligono,
                       cuenca_upstream_hidrobasins)
    from .watershed import delinear_cuenca_merit
    from .morfologia import MorfologiaCuenca
    cuenca_pol = None
    cuenca_obj = None
    cn = None
    cn_ponderado = None
    cuenca = delinear_cuenca_merit(lat, lon)
    # Cuenca grande: la delineación pixel a pixel de MERIT se trunca en el
    # borde del tile y «no fusiona» la cuenca completa (caso amazónico).
    # Cuando eso ocurre, se delinea fusionando las sub-cuencas HydroBASINS L12
    # aguas arriba (trazado NEXT_DOWN + dissolve en el servidor de GEE), que
    # sí entrega UN polígono cerrado de la cuenca entera.
    if cuenca is not None and getattr(cuenca, "truncada", False):
        print("[pipeline] cuenca truncada por MERIT (grande) — fusionando "
              "sub-cuencas HydroBASINS L12 aguas arriba…", flush=True)
        merge = cuenca_upstream_hidrobasins(lat, lon)
        if merge is not None and merge.get("poligono") is not None:
            import numpy as _np
            cuenca.poligono_latlon = _np.asarray(merge["poligono"], dtype=float)
            cuenca.area_km2 = merge["area_km2"]
            cuenca.perimetro_km = merge["perimetro_km"]
            cuenca.truncada = bool(merge.get("truncada", False))
            cuenca.bbox = (
                cuenca.poligono_latlon[:, 0].min(),
                cuenca.poligono_latlon[:, 1].min(),
                cuenca.poligono_latlon[:, 0].max(),
                cuenca.poligono_latlon[:, 1].max(),
            )
            print(f"[pipeline] cuenca fusionada HydroBASINS: "
                  f"{merge['n_subcuencas']} sub-cuencas L12 → "
                  f"A={merge['area_km2']} km²"
                  + (" (aún truncada, escala continental)"
                     if merge.get("truncada") else ""), flush=True)
        elif merge is not None and merge.get("truncada"):
            print(f"[pipeline] cuenca de escala continental "
                  f"({merge['n_subcuencas']} sub-cuencas L12) — excede la "
                  f"delineación punto a punto; se conserva la malla MERIT "
                  f"truncada y se marca el aviso.", flush=True)
    if cuenca is not None:
        # CN ponderado por área (media de MapBiomas → CN). Idéntico al del mapa
        # 9.5; se calcula acá UNA vez para que tanto §9 como §10 lo compartan.
        cn_ponderado = cn_ponderado_desde_poligono(cuenca.poligono_latlon)
        cn = cn_ponderado or cn_desde_poligono(cuenca.poligono_latlon) or 75.0
        cota_menor = max(cuenca.cota_menor_m, float(estacion.altitud_msnm))
        # El cauce principal real (D8) está en cuenca.red_drenaje.main_channel_km.
        red = (cuenca.red_drenaje or {})
        Lc_real = float(red.get("main_channel_km") or cuenca.long_cauce_km)
        desnivel_real = round(cuenca.cota_mayor_m - cota_menor, 1)
        S_real = round(desnivel_real / (Lc_real * 1000.0), 4) if Lc_real else cuenca.pendiente_media_mm
        # Upgrade morfometría con COP-DEM 12.5 m (downscaled cubic):
        # 4–6× más píxeles que MERIT 90 m, mejor estimación de hmax/hmin
        # y pendiente media. Si COP-DEM falla → seguimos con MERIT.
        cota_mayor_morf = cuenca.cota_mayor_m
        cota_menor_morf = cota_menor
        desnivel_morf = desnivel_real
        S_morf = S_real
        fuente_dem_morf = "MERIT Hydro 90 m"
        # El downscaling a 12.5 m solo tiene sentido (y es viable) en cuencas
        # de tamaño manejable. En cuencas grandes/fusionadas (> 2000 km²) sería
        # un raster enorme que satura el worker → se conserva MERIT 90 m.
        _area_para_copdem = cuenca.area_km2 or 0.0
        try:
            if _area_para_copdem > 2000.0:
                raise RuntimeError(
                    f"cuenca grande ({_area_para_copdem:.0f} km²) — se omite "
                    f"downscaling COP-DEM 12.5 m")
            from .copernicus_dem import obtener_dem_cuenca as _copdem_cuenca
            cop_morf = _copdem_cuenca(cuenca.poligono_latlon,
                                          res_target_m=12.5)
            if cop_morf is not None:
                cota_mayor_morf = round(cop_morf["hmax_m"], 1)
                # Mantener cota_menor ≥ altitud estación si ya fue ajustada
                cota_menor_morf = max(round(cop_morf["hmin_m"], 1),
                                          float(estacion.altitud_msnm))
                desnivel_morf = round(cota_mayor_morf - cota_menor_morf, 1)
                S_morf = (round(desnivel_morf / (Lc_real * 1000.0), 4)
                            if Lc_real else cuenca.pendiente_media_mm)
                fuente_dem_morf = (f"COP-DEM GLO-30 (downscaling cubic a "
                                      f"12.5 m, {cop_morf['n_pixels_validos']:,}"
                                      f" px)").replace(",", " ")
                print(f"[pipeline] morfometría con COP-DEM 12.5 m: "
                       f"H={cota_menor_morf:.0f}–{cota_mayor_morf:.0f} m, "
                       f"S_pendiente_DEM={cop_morf['pendiente_media_pct']:.1f}%",
                       flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] COP-DEM upgrade no aplicable: "
                   f"{type(e).__name__}: {e}", flush=True)
        morf = MorfologiaCuenca(
            area_km2=cuenca.area_km2,
            long_cauce_km=Lc_real,
            cota_mayor_m=cota_mayor_morf,
            cota_menor_m=cota_menor_morf,
            desnivel_m=desnivel_morf,
            pendiente_media_mm=S_morf,
            perimetro_km=cuenca.perimetro_km,
            cn=float(cn),
            sintetica=False,
        )
        # Marcador para que el informe / telemetría sepan qué DEM se usó
        try:
            morf.fuente_dem = fuente_dem_morf  # type: ignore[attr-defined]
        except Exception:  # dataclass frozen → no hacer nada
            pass
        cuenca_pol = cuenca.poligono_latlon
        cuenca_obj = cuenca
    else:
        # MERIT Hydro falló → fallback a HydroBASINS L12 para tener AL MENOS
        # un polígono REAL para los mapas temáticos GEE (drenaje, uso, cobertura,
        # CN, pendientes, coef. escorrentía) y el 9.2 desde COP-DEM. Sin esto,
        # cuenca_pol queda None y TODOS los mapas caen a esquemáticos.
        try:
            from .gee import poligono_hidrobasins_l12
            # Primero la cuenca FUSIONADA aguas arriba (sirve para cuencas
            # grandes); si no, el polígono de la sub-cuenca L12 única.
            merge = cuenca_upstream_hidrobasins(lat, lon)
            if merge is not None and merge.get("poligono") is not None:
                import numpy as _np
                cuenca_pol = _np.asarray(merge["poligono"], dtype=float)
                print(f"[pipeline] MERIT falló — usando cuenca FUSIONADA "
                       f"HydroBASINS ({merge['n_subcuencas']} sub-cuencas L12, "
                       f"A={merge['area_km2']} km²) para mapas", flush=True)
            else:
                cuenca_pol = poligono_hidrobasins_l12(lat, lon)
                if cuenca_pol is not None:
                    print(f"[pipeline] MERIT falló — usando polígono "
                           f"HydroBASINS L12 único ({len(cuenca_pol)} "
                           f"vértices) para mapas", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] HydroBASINS fallback falló: "
                   f"{type(e).__name__}: {e}", flush=True)
        # HYDROFRA v1.3: morfología SOLO real (HydroBASINS L12 + COP-DEM vía
        # morfologia_desde_gee). Se eliminó la estimación sintética por ley
        # de Hack. Si ninguna fuente real responde, se aborta el análisis con
        # un mensaje claro en lugar de inventar área/perímetro/pendiente.
        morf = morfologia_desde_gee(lat, lon, estacion.altitud_msnm)
        if morf is None:
            raise RuntimeError(
                "No se pudo delinear la cuenca ni obtener su morfología con "
                "datos reales (MERIT Hydro, HydroBASINS y COP-DEM no "
                "respondieron) para este sitio. HYDROFRA v1.3 no usa "
                "morfometría sintética (ley de Hack). Verificar /gee_status "
                "y reintentar el análisis.")

    # 7. Tiempo de concentración (procedimiento de 5 pasos + validación de forma).
    #    Cuando hay análisis morfológico real, `morf` lleva: Lc del cauce D8,
    #    ΔH del DEM, S = ΔH/Lc real y CN ponderado por área del mapa 9.5.
    tc_resultados = _calc_tc(morf)
    tc_adoptado = adoptar_tc(tc_resultados, morf, tipo_obra.clave, cn_disponible)

    # 7b. Análisis morfológico completo (§9.8-9.10) — usa el mismo CN y el Tc
    #     adoptado, así §9 y §10 quedan consistentes.
    analisis_morf = None
    if cuenca_obj is not None:
        from .morfometria import analizar as _analizar_morf
        try:
            analisis_morf = _analizar_morf(
                cuenca_obj, tc_min=tc_adoptado.tc_min, cn_ponderado=cn)
        except Exception:  # noqa: BLE001
            analisis_morf = None

    # 7c. RECONCILIACIÓN A FUENTE ÚNICA del relieve y la pendiente del cauce.
    #     `morf` deriva sus cotas del COP-DEM 12.5 m (downscaling), mientras que
    #     `analisis_morf` las derivaba del array MERIT 90 m: el mismo desnivel
    #     salía distinto en §9 y en §10 (p. ej. 848 m vs 1012 m) y lo mismo la
    #     pendiente del cauce. Se adopta como ÚNICA fuente de verdad el DEM de
    #     mayor resolución efectivamente usado en `morf`, y se propaga a
    #     `analisis_morf` para que todas las secciones publiquen el mismo valor.
    reconciliacion_morf = None
    if analisis_morf is not None and morf is not None:
        try:
            _h_prev = float(analisis_morf.desnivel_m)
            _s_prev = float(analisis_morf.pendiente_cauce_pct)
            _Lc = float(analisis_morf.long_cauce_principal_km
                        or morf.long_cauce_km or 0.0)
            analisis_morf.cota_mayor_m = float(morf.cota_mayor_m)
            analisis_morf.cota_menor_m = float(morf.cota_menor_m)
            analisis_morf.desnivel_m = float(morf.desnivel_m)
            if _Lc > 0:
                analisis_morf.pendiente_cauce_pct = round(
                    100.0 * float(morf.desnivel_m) / (_Lc * 1000.0), 2)
            reconciliacion_morf = {
                "fuente": getattr(morf, "fuente_dem", "DEM de mayor resolución"),
                "desnivel_antes_m": round(_h_prev, 1),
                "desnivel_adoptado_m": round(float(morf.desnivel_m), 1),
                "pendiente_cauce_antes_pct": round(_s_prev, 2),
                "pendiente_cauce_adoptada_pct": float(
                    analisis_morf.pendiente_cauce_pct),
                "Lc_km": round(_Lc, 3),
            }
            print(f"[pipeline] morfometría reconciliada a fuente única "
                  f"({reconciliacion_morf['fuente']}): H "
                  f"{_h_prev:.0f}→{morf.desnivel_m:.0f} m, S_cauce "
                  f"{_s_prev:.2f}→{analisis_morf.pendiente_cauce_pct:.2f} %",
                  flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] reconciliación morfométrica falló: {e}",
                  flush=True)

    # 8. Hietogramas para TODOS los períodos de retorno (5, 10, 20, 100, 500,
    #    1000, 5000, 10000 años) por bloques, SCS, Chicago y Huff (este último
    #    solo cuando A > 25 km², donde dominan tormentas de mayor duración).
    from .hietograma import huff as _huff
    from .caudal_maximo import PERIODOS_QMAX_DEFAULT as _PERIODOS_TODOS
    hietogramas = {
        "bloques": bloques_alternos(modelo_sherman, T_diseno, tc_adoptado.tc_min),
        "scs": scs_tipo2(modelo_sherman, T_diseno, tc_adoptado.tc_min),
        "chicago": chicago(modelo_sherman, T_diseno, tc_adoptado.tc_min),
    }
    aplica_huff = float(morf.area_km2) > 25.0
    if aplica_huff:
        hietogramas["huff"] = _huff(modelo_sherman, T_diseno,
                                     tc_adoptado.tc_min, cuartil=2)
    hietogramas_por_T = {}
    metodos_hieto = ["bloques", "scs", "chicago"]
    if aplica_huff:
        metodos_hieto.append("huff")
    for T in _PERIODOS_TODOS:
        hietogramas_por_T[int(T)] = {
            "bloques": bloques_alternos(modelo_sherman, T, tc_adoptado.tc_min),
            "scs":     scs_tipo2(modelo_sherman, T, tc_adoptado.tc_min),
            "chicago": chicago(modelo_sherman, T, tc_adoptado.tc_min),
        }
        if aplica_huff:
            hietogramas_por_T[int(T)]["huff"] = _huff(
                modelo_sherman, T, tc_adoptado.tc_min, cuartil=2)

    # 9. HEC-HMS
    hechms = resumen_hec_hms(area_km2=morf.area_km2, tc_min=tc_adoptado.tc_min,
                             hietograma=hietogramas["bloques"])

    # 9b. Modelación HEC-HMS-like (§13): tormenta de diseño de 24 h + SCS-CN +
    #     HU SCS. Se usa la distribución SCS Tipo II sobre 24 h (USDA-SCS TR-55,
    #     1986), el estándar de HEC-HMS para modelación lluvia-escorrentía. La
    #     duración de 24 h es CLAVE: con tormentas cortas de duración = Tc la
    #     lámina total no supera la abstracción inicial Ia = 0.2·S del método
    #     SCS-CN y la escorrentía sale nula para los períodos frecuentes; una
    #     tormenta de 24 h acumula la lámina del cuantil diario P24(T) y produce
    #     escorrentía físicamente representativa en todos los T.
    from .hec_hms_sim import ParametrosHEC, simular_familia_T
    HEC_DUR_MIN = 1440.0                                    # 24 h
    dt_hec = float(min(30.0, max(5.0, round(tc_adoptado.tc_min / 6.0))))
    hec_clave = "scs"
    hec_just = (
        "tormenta de diseño de <b>24 h con distribución SCS Tipo II</b> "
        "(USDA-SCS TR-55, 1986), el estándar de HEC-HMS para el par pérdidas "
        "SCS-CN + hidrograma unitario SCS. La duración de 24 h garantiza que "
        "la lámina supere la abstracción inicial (Ia = 0.2·S) y genere "
        "escorrentía representativa en todos los períodos de retorno.")
    hietogramas_hec_por_T = {
        int(T): {"scs": scs_tipo2(modelo_sherman, T, HEC_DUR_MIN,
                                   delta_t_min=dt_hec)}
        for T in _PERIODOS_TODOS
    }
    cn_para_hec = (analisis_morf.cn if analisis_morf is not None and analisis_morf.cn
                   else (cn_ponderado or float(getattr(morf, "cn", 75.0))))
    # Corrección del CN por pendiente media del terreno (Williams 1995): en
    # cuencas de montaña la pendiente > 5 % del supuesto SCS aumenta la
    # escorrentía. Se usa la pendiente media de la cuenca (m/m).
    cn_correccion = None
    try:
        from .hec_hms_sim import cn_ajustado_pendiente
        _pend_cuenca_pct = float(
            analisis_morf.pendiente_cuenca_pct if analisis_morf is not None
            else getattr(morf, "pendiente_pct", 0.0))
        cn_correccion = cn_ajustado_pendiente(cn_para_hec,
                                              _pend_cuenca_pct / 100.0)
        cn_para_hec = float(cn_correccion["cn2s"])
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] corrección CN por pendiente falló: {e}", flush=True)
    hec_params = ParametrosHEC(
        area_km2=float(morf.area_km2), cn=float(cn_para_hec),
        tc_min=float(tc_adoptado.tc_min),
        metodo_hieto=hec_clave,
        nota_hieto=hec_just,
    )
    hec_hidrogramas_por_T = {}
    try:
        hec_hidrogramas_por_T = simular_familia_T(hec_params,
                                                   hietogramas_hec_por_T)
    except Exception:  # noqa: BLE001
        hec_hidrogramas_por_T = {}

    # 10. Caudales máximos para 9 períodos de retorno × 5 métodos.
    from .caudal_maximo import (EntradaQMax, tabla_caudal_maximo,
                                  PERIODOS_QMAX_DEFAULT)
    from .stats import cuantiles_para_periodos_retorno as _q_T
    # Períodos de retorno del Q máx: los por defecto + el T de diseño + el T de
    # verificación estructural (si el tipo de obra lo define, p. ej. ABC 200/300).
    T_verif = getattr(tipo_obra, "t_verificacion", None)
    periodos_qmax = tuple(sorted(set(PERIODOS_QMAX_DEFAULT) | {int(T_diseno)} |
                                 ({int(T_verif)} if T_verif else set())))
    qmax_tabla = None
    qmax_entrada = None
    try:
        cuant_qmax = _q_T(mejor, periodos_qmax)
        p24_por_T = {int(r["T_anios"]): float(r["p24_mm"])
                     for _, r in cuant_qmax.iterrows()}
        cn_qmax = None
        if analisis_morf is not None and analisis_morf.cn:
            cn_qmax = float(analisis_morf.cn)
        elif cn_ponderado:
            cn_qmax = float(cn_ponderado)
        else:
            cn_qmax = float(getattr(morf, "cn", 75.0))
        S_cuenca_pct = (analisis_morf.pendiente_cuenca_pct if analisis_morf
                        else morf.pendiente_pct)
        Sc_cauce_pct = (analisis_morf.pendiente_cauce_pct if analisis_morf
                        else morf.pendiente_pct)
        # C ponderado: si no llegó del mapa todavía (se calcula en _generar_graficos
        # después), usamos un valor por defecto razonable derivado del CN para
        # tener algo válido. Se sobreescribirá si el mapa 9.7 da c_ponderado.
        C_defecto = (analisis_morf.cn if analisis_morf else cn_qmax)
        C_defecto = max(0.10, min(0.95, (C_defecto - 30.0) / 70.0))
        qmax_entrada = EntradaQMax(
            A_km2=float(morf.area_km2), L_km=float(morf.long_cauce_km),
            S_pct=float(S_cuenca_pct), Sc_pct=float(Sc_cauce_pct),
            Tc_min=float(tc_adoptado.tc_min),
            CN=cn_qmax, C=C_defecto,
        )
        qmax_tabla = tabla_caudal_maximo(qmax_entrada, modelo_sherman,
                                         p24_por_T, periodos_qmax)
    except Exception:  # noqa: BLE001
        qmax_tabla = None

    # 10.b Tirante (calado) tipo HEC-RAS 1D — tirante normal (Manning) por
    # sección. El caudal de entrada al módulo hidráulico se toma de la
    # MODELACIÓN HEC-HMS (§13, Q pico por T), no de la mediana del §11: el
    # hidrograma HEC-HMS es el método base para el dimensionamiento hidráulico
    # del puente. Se calcula el T de diseño (100) y el de verificación (500);
    # si HEC-HMS no entregó caudal para algún T, se cae a la mediana del §11.
    tirante = None
    if qmax_tabla is not None and len(qmax_tabla) and qmax_entrada is not None:
        try:
            from .hidraulica_fluvial import calcular_tirante

            def _q_para_T(T):
                if T is None:
                    return None
                rhec = (hec_hidrogramas_por_T or {}).get(int(T))
                if rhec is not None and getattr(rhec, "Q_pico_m3s", 0) > 0:
                    return float(rhec.Q_pico_m3s)
                fila = qmax_tabla.loc[qmax_tabla["T_anios"] == int(T)]
                return (float(fila["Q_mediana"].iloc[0])
                        if len(fila) else None)

            Q_d = _q_para_T(T_diseno)
            Q_v = _q_para_T(T_verif) if T_verif else None
            if Q_d and Q_d > 0:
                tirante = calcular_tirante(
                    lat=lat, lon=lon, Q_diseno=Q_d, T_diseno=int(T_diseno),
                    area_cuenca_km2=float(qmax_entrada.A_km2),
                    S_cauce_pct=float(qmax_entrada.Sc_pct),
                    poligono_cuenca=cuenca_pol,
                    Q_verif=Q_v, T_verif=int(T_verif) if T_verif else None,
                    intentar_dem=not modo_ligero,
                    params_puente=params_puente)
        except Exception:  # noqa: BLE001
            tirante = None

    # 10.c Análisis de sensibilidad ±20 % (CN, Tc, n) → Q y tirante (EDTP).
    sensibilidad = None
    if tirante is not None and tirante.secciones:
        try:
            from .sensibilidad import analisis_sensibilidad
            _hieto_dis = (hietogramas_hec_por_T.get(int(T_diseno), {})
                          .get("scs"))
            _rhec_dis = (hec_hidrogramas_por_T or {}).get(int(T_diseno))
            _q_base = (float(_rhec_dis.Q_pico_m3s) if _rhec_dis is not None
                       else float(tirante.Q_m3s))
            if _hieto_dis is not None:
                sensibilidad = analisis_sensibilidad(
                    hec_params=hec_params, hietograma_diseno=_hieto_dis,
                    tirante=tirante, Q_base=_q_base, T_diseno=int(T_diseno))
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] análisis de sensibilidad falló: {e}", flush=True)

    # 10.c.2 Sensibilidad hidráulica-socavación ±20/40 % (Q, n, S, D50) para el
    # diseño del puente (tirante, velocidad, socavación, gálibo).
    sensibilidad_hid = None
    if tirante is not None and tirante.secciones:
        try:
            from .sensibilidad import sensibilidad_hidraulica
            _rhec_d = (hec_hidrogramas_por_T or {}).get(int(T_diseno))
            _qb = (float(_rhec_d.Q_pico_m3s) if _rhec_d is not None
                   else float(tirante.Q_m3s))
            sensibilidad_hid = sensibilidad_hidraulica(
                tirante=tirante, params_puente=params_puente,
                Q_base=_qb, T_base=int(T_diseno))
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] sensibilidad hidráulica falló: {e}", flush=True)

    # 10.d Dimensionamiento preliminar de obras de protección fluvial (§14.8).
    proteccion = None
    if tirante is not None and tirante.secciones:
        try:
            from .proteccion_fluvial import dimensionar_proteccion
            _V = (tirante.velocidad_verif_ms or tirante.velocidad_media_ms)
            _y = (tirante.tirante_verif_m or tirante.tirante_control_m)
            _soc = getattr(tirante, "socavacion", None)
            _prof = None
            if _soc is not None:
                _cands = [v for v in (getattr(_soc, "socavacion_total_pila_m",
                                              float("nan")),
                                      getattr(_soc, "socavacion_total_estribo_m",
                                              float("nan")),
                                      getattr(_soc, "ys_general_m",
                                              float("nan"))) if v == v]
                _prof = max(_cands) if _cands else None
            _ancho = max((s.ancho_sup_m for s in tirante.secciones
                          if s.ancho_sup_m == s.ancho_sup_m), default=None)
            proteccion = dimensionar_proteccion(
                velocidad_ms=_V, tirante_m=_y,
                name_sobre_fondo_m=_y, prof_socavacion_m=_prof,
                ancho_cauce_m=_ancho)
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] protección fluvial falló: {e}", flush=True)

    # 10.e Resultados reales de HEC-RAS (si el usuario subió el HDF del plan).
    hecras_resultados = None
    if hecras_hdf:
        try:
            from .hec_commander import leer_resultados_hecras
            hecras_resultados = leer_resultados_hecras(hecras_hdf)
            if hecras_resultados is not None:
                print(f"[pipeline] HEC-RAS: {hecras_resultados.n_secciones} "
                      f"secciones leídas ({hecras_resultados.fuente}); "
                      f"WSE máx {hecras_resultados.wse_max_global_m:.2f} m",
                      flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] lectura HEC-RAS falló: {e}", flush=True)

    # 10.f Diseño de alcantarillas de drenaje vial menor (FHWA HDS-5).
    # Se dimensiona con Q(25) y se verifica con Q(100). Si el usuario aportó un
    # modelo HEC-RAS, el caudal de diseño y el TW se toman de ese modelo.
    alcantarillas = None
    if (tipo_obra.clave == "drenaje_vial_menor" and qmax_tabla is not None
            and len(qmax_tabla) and qmax_entrada is not None):
        try:
            from .alcantarillas import disenar_alcantarilla

            def _q_alc(T):
                rhec = (hec_hidrogramas_por_T or {}).get(int(T))
                if rhec is not None and getattr(rhec, "Q_pico_m3s", 0) > 0:
                    return float(rhec.Q_pico_m3s)
                fila = qmax_tabla.loc[qmax_tabla["T_anios"] == int(T)]
                return float(fila["Q_mediana"].iloc[0]) if len(fila) else None

            _q25_int = _q_alc(25) or _q_alc(int(T_diseno))
            _q100 = _q_alc(100)
            _pa = params_alcantarilla or {}
            _kw_alc = {}
            if _pa.get("long_m"):
                _kw_alc["long_m"] = float(_pa["long_m"])
            if _pa.get("criterio_hw_d"):
                _kw_alc["criterio_hw_d"] = float(_pa["criterio_hw_d"])
            if _pa.get("v_admisible_ms"):
                _kw_alc["v_admisible_ms"] = float(_pa["v_admisible_ms"])
            # Diseño con sección fija (tipo + dimensiones + celdas del usuario).
            if _pa.get("tipo_fijo"):
                _kw_alc["tipo_fijo"] = str(_pa["tipo_fijo"])
                _kw_alc["n_celdas_fijo"] = int(_pa.get("n_celdas_fijo") or 1)
                if _pa.get("D_fijo"):
                    _kw_alc["D_fijo"] = float(_pa["D_fijo"])
                if _pa.get("B_fijo"):
                    _kw_alc["B_fijo"] = float(_pa["B_fijo"])
                if _pa.get("H_fijo"):
                    _kw_alc["H_fijo"] = float(_pa["H_fijo"])

            # Procedencia del caudal de diseño y del tirante de descarga (TW).
            _fq = "interno (HEC-HMS)"
            _q_dis = _q25_int
            _ftw = "por defecto"
            _tw_manual = _pa.get("tw_m")
            _contraste = None
            if hecras_resultados is not None:
                _q_hr = getattr(hecras_resultados, "flow_max_global_m3s", None)
                if _q_hr and _q_hr == _q_hr and _q_hr > 0:
                    _q_dis = float(_q_hr)
                    _fq = "HEC-RAS (modelo del usuario)"
                _tw_hr = hecras_resultados.tw_aguas_abajo_m()
                _sc = hecras_resultados.seccion_critica()
                _contraste = {
                    "wse_max_m": hecras_resultados.wse_max_global_m,
                    "vel_max_ms": hecras_resultados.vel_max_global_ms,
                    "q_hecras_m3s": _q_hr,
                    "q_interno_25_m3s": _q25_int,
                    "q_interno_100_m3s": _q100,
                    "tw_hecras_m": _tw_hr,
                    "seccion_critica": (
                        f"{_sc.river}/{_sc.reach} {_sc.station}"
                        if _sc is not None else None),
                }
            # TW: manual > HEC-RAS > por defecto.
            if _tw_manual is not None:
                _kw_alc["tw_m"] = float(_tw_manual)
                _ftw = "manual"
            elif hecras_resultados is not None:
                _tw_hr = hecras_resultados.tw_aguas_abajo_m()
                if _tw_hr is not None and _tw_hr > 0:
                    _kw_alc["tw_m"] = float(_tw_hr)
                    _ftw = "HEC-RAS (WSE − fondo aguas abajo)"

            if _q_dis and _q_dis > 0:
                alcantarillas = disenar_alcantarilla(
                    Q_diseno=_q_dis, T_diseno=25,
                    S_cauce_pct=float(qmax_entrada.Sc_pct),
                    Q_verif=_q100, T_verif=(100 if _q100 else None),
                    **_kw_alc)
                if alcantarillas is not None:
                    alcantarillas.fuente_q = _fq
                    alcantarillas.fuente_tw = _ftw
                    alcantarillas.contraste_hecras = _contraste
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] diseño de alcantarillas falló: {e}", flush=True)

    # 10.g Captación de riego menor (canal, desarenador, bocatomas, protección).
    riego = None
    if tipo_obra.clave == "riego_pequeno":
        try:
            from .riego_menor import disenar_captacion_riego
            _pr = params_riego or {}
            # Caudal de crecida del río = Q(T de diseño) de la hidrología.
            _q_cre = None
            if qmax_tabla is not None and len(qmax_tabla):
                _rhec = (hec_hidrogramas_por_T or {}).get(int(T_diseno))
                if _rhec is not None and getattr(_rhec, "Q_pico_m3s", 0) > 0:
                    _q_cre = float(_rhec.Q_pico_m3s)
                else:
                    _f = qmax_tabla.loc[qmax_tabla["T_anios"] == int(T_diseno)]
                    _q_cre = float(_f["Q_mediana"].iloc[0]) if len(_f) else None
            riego = disenar_captacion_riego(
                q_captacion_ls=_pr.get("q_captacion_ls"),
                area_ha=_pr.get("area_ha"),
                modulo_ls_ha=_pr.get("modulo_ls_ha"),
                q_crecida_m3s=_q_cre,
                q_estiaje_ls=_pr.get("q_estiaje_ls"),
                ancho_rio_m=float(_pr.get("ancho_rio_m") or 8.0),
                cota_captacion=_pr.get("cota_captacion"),
                canal_so_pct=float(_pr.get("canal_so_pct") or 0.1),
                canal_revestimiento=str(_pr.get("canal_revestimiento")
                                        or "hormigon"),
                canal_forma=str(_pr.get("canal_forma") or "trapezoidal"),
                canal_talud_z=float(_pr.get("canal_talud_z") or 1.0),
                canal_base_m=_pr.get("canal_base_m"),
                d_particula_mm=float(_pr.get("d_particula_mm") or 0.20))
            if riego is not None:
                print(f"[pipeline] captación de riego: Q={riego.q_captacion_m3s:.3f} "
                      f"m³/s ({riego.fuente_q})", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[pipeline] diseño de captación de riego falló: {e}",
                  flush=True)

    R = ResultadoCompleto(
        proyecto=proyecto.limpio(), tipo_obra=tipo_obra, T_diseno=T_diseno,
        T_verificacion=T_verif,
        lat=lat, lon=lon, estacion=estacion, dist_km=dist,
        serie_estacion=serie_estacion, series_satelitales=series_sat,
        decision=decision, serie=serie, desc=desc, pruebas=pruebas,
        ajustes=ajustes, mejor_ajuste=mejor, cuantiles=cuantiles, exp_dp=exp_dp,
        idf_largo=idf_largo, modelos=modelos,
        modelo_recomendado=modelo_rec, justificacion_modelo=just_modelo,
        modelos_preferidos=preferidos, resolucion_datos=resolucion_datos,
        modo_ligero=modo_ligero, modelo_sherman=modelo_sherman,
        morfologia=morf, tc_resultados=tc_resultados, tc_adoptado=tc_adoptado,
        hietogramas=hietogramas, hechms=hechms, cuenca_poligono=cuenca_pol,
        analisis_morf=analisis_morf,
        cn_ponderado=cn_ponderado,
        qmax_tabla=qmax_tabla, qmax_entrada=qmax_entrada,
        tirante=tirante,
        hietogramas_por_T=hietogramas_por_T,
        aplica_huff=aplica_huff,
        metodos_hieto=metodos_hieto,
        hec_params=hec_params,
        hec_metodo_hieto=hec_clave,
        hec_justificacion=hec_just,
        hec_hidrogramas_por_T=hec_hidrogramas_por_T,
        hec_duracion_min=HEC_DUR_MIN,
        sensibilidad=sensibilidad,
        sensibilidad_hidraulica=sensibilidad_hid,
        proteccion=proteccion,
        alcantarillas=alcantarillas,
        hecras_resultados=hecras_resultados,
        riego=riego,
        cn_correccion=cn_correccion,
        reconciliacion_morf=reconciliacion_morf,
        cuantiles_sin_correccion=cuantiles_sin_correccion,
        serie_sin_correccion=serie_sin_correccion,
        ic_cuantiles=ic_cuantiles,
        serie_observada_usada=serie_observada_usada,
        anios_descartados=anios_descartados,
        exp_dyck_peschke=exp_usado,
        region_dyck_peschke=region_dp,
        p24_validacion_regional=p24_validacion,
        hershfield_aplicado=hershfield_aplicado,
        correccion_regional=correccion_regional,
        grubbs=grubbs,
        doble_masa=doble_masa,
        red_estaciones=red_estaciones,
    )

    if generar_archivos:
        _generar_csvs(R, out)
        _generar_graficos(R, out)
        R.pdf = generar_pdf(out / "informe_curvas_idf.pdf", R)
    return R


def _generar_csvs(R: ResultadoCompleto, out: Path) -> None:
    R.serie_estacion.to_csv(out / "serie_estacion.csv", index=False)
    R.serie.to_csv(out / "serie_adoptada.csv", index=False)
    R.cuantiles.to_csv(out / "cuantiles_p24.csv", index=False)
    R.idf_largo.to_csv(out / "idf_tabla_larga.csv", index=False)
    for k, h in R.hietogramas.items():
        h.tabla.to_csv(out / f"hietograma_{k}.csv", index=False)


def _generar_graficos(R: ResultadoCompleto, out: Path) -> None:
    g = R.graficos
    g["serie_estacion"] = plot_serie_anual_maxima(
        R.serie_estacion, f"P24max anual — {R.estacion.nombre}", out / "01_serie_estacion.png")
    # Gráficos satelitales solo si hay series (no en modo ligero)
    if R.series_satelitales:
        g["series_satelitales"] = plot_series_satelitales(
            R.serie_estacion, R.series_satelitales, out / "02_series_satelitales.png",
            nombre_estacion=R.estacion.nombre)
        g["correlacion"] = plot_correlacion(
            R.serie_estacion, R.series_satelitales, out / "03_correlacion.png")
    if getattr(R, "doble_masa", None) is not None:
        from .plotting import plot_doble_masa
        p = plot_doble_masa(R.doble_masa, out / "03b_doble_masa.png")
        if p is not None:
            g["doble_masa"] = p
    g["ajustes"] = plot_ajuste_distribucion(
        R.serie["p24_mm"].to_numpy(), R.ajustes, out / "04_ajustes.png")
    g["modelos_idf_comparacion"] = plot_modelos_idf(
        R.modelos, PERIODOS_RETORNO_DEFAULT, DURACIONES_DEFAULT_MIN,
        out / "05_modelos_idf.png", T_destacado=R.T_diseno)
    # En modo completo, una curva IDF por cada modelo; en ligero se omiten.
    if not R.modo_ligero:
        for k, m in enumerate(R.modelos, 1):
            g[f"modelo_{k}"] = plot_modelo_idf_curvas(
                m, PERIODOS_RETORNO_DEFAULT, DURACIONES_DEFAULT_MIN,
                out / f"06_modelo_{k}.png")
    g["tc"] = plot_tiempo_concentracion(
        R.tc_resultados, R.tc_adoptado.tc_min, out / "07_tiempo_concentracion.png")
    # Curva hipsométrica (9.9) — solo si el análisis morfológico está disponible.
    if R.analisis_morf is not None:
        from .plotting import plot_curva_hipsometrica
        g["hipsometrica"] = plot_curva_hipsometrica(
            R.analisis_morf, out / "09_hipsometrica.png")
    if R.qmax_tabla is not None and len(R.qmax_tabla):
        from .plotting import plot_caudal_maximo
        g["qmax"] = plot_caudal_maximo(R.qmax_tabla, out / "10_qmax.png")
    if getattr(R, "tirante", None) is not None and R.tirante.secciones:
        from .plotting import plot_tirante, plot_tirante_planta
        g["tirante"] = plot_tirante(R.tirante, out / "11_tirante.png")
        planta = plot_tirante_planta(R.tirante, out / "11b_tirante_planta.png")
        if planta is not None:
            g["tirante_planta"] = planta
    # Alcantarilla (drenaje vial menor): curva de funcionamiento y perfil.
    _alc = getattr(R, "alcantarillas", None)
    if _alc is not None and getattr(_alc, "recomendada", None) is not None:
        from .plotting import (plot_alcantarilla_curva,
                                 plot_alcantarilla_perfil)
        _pc = plot_alcantarilla_curva(_alc, out / "14_alc_curva.png")
        if _pc is not None:
            g["alc_curva"] = _pc
        _pp = plot_alcantarilla_perfil(_alc, out / "14b_alc_perfil.png")
        if _pp is not None:
            g["alc_perfil"] = _pp
    hieto_comp = {"Bloques alternos": R.hietogramas["bloques"],
                  "SCS Tipo II":      R.hietogramas["scs"],
                  "Chicago":          R.hietogramas["chicago"]}
    if "huff" in R.hietogramas:
        hieto_comp["Huff (Q2)"] = R.hietogramas["huff"]
    g["hietogramas_comparacion"] = plot_hietograma_comparado(
        hieto_comp, out / "08_hietogramas.png")
    # Familia de hietogramas para los 9 períodos de retorno, un gráfico por método.
    if R.hietogramas_por_T:
        from .plotting import plot_hietogramas_familia_T
        for met in R.metodos_hieto:
            g[f"hieto_familia_{met}"] = plot_hietogramas_familia_T(
                R.hietogramas_por_T, met, out / f"12_hieto_familia_{met}.png")
    # Modelación HEC-HMS (§13): pérdidas, HU, hidrogramas familia y Qp vs T.
    if R.hec_hidrogramas_por_T:
        from .plotting import (plot_hec_perdidas, plot_hec_hu,
                                 plot_hec_hidrogramas_familia, plot_hec_qpico_vs_T)
        T_des = R.T_diseno if R.T_diseno in R.hec_hidrogramas_por_T else \
                 next(iter(R.hec_hidrogramas_por_T.keys()))
        r_des = R.hec_hidrogramas_por_T[T_des]
        g["hec_perdidas"] = plot_hec_perdidas(r_des, out / "13_hec_perdidas.png")
        g["hec_hu"] = plot_hec_hu(r_des.delta_t_min, R.hec_params.tc_min,
                                    R.hec_params.area_km2,
                                    out / "13_hec_hu.png")
        g["hec_hidrogramas"] = plot_hec_hidrogramas_familia(
            R.hec_hidrogramas_por_T, out / "13_hec_hidrogramas.png")
        g["hec_qpico_T"] = plot_hec_qpico_vs_T(
            R.hec_hidrogramas_por_T, out / "13_hec_qpico_T.png")
    # Mapas de la cuenca: SOLO reales (GEE / COP-DEM). Los mapas
    # esquemáticos sintéticos fueron eliminados (HYDROFRA v1.3): si un
    # mapa real no se puede generar, no se dibuja un esquema falso — el
    # informe lo marca como «no disponible» en la tabla diagnóstica de §9.
    from .gee import mapa_cuenca_gee
    # Mapa real de la cuenca: si tenemos polígono delineado por MERIT Hydro,
    # se usa ese contorno y encuadre; si no, cae a HydroBASINS L12. La leyenda
    # del 9.1 son las bandas de elevación del análisis morfológico.
    leyenda_elev = None
    if R.analisis_morf is not None:
        cols = ["#2c7bb6", "#abd9e9", "#a6d96a", "#fdae61", "#f46d43", "#a50026"]
        leyenda_elev = [
            {"etiqueta": f"{b.desde_m:.0f}–{b.hasta_m:.0f} m", "color": cols[i % len(cols)],
             "pct": b.pct}
            for i, b in enumerate(R.analisis_morf.bandas_elevacion)]
    mapa_real = mapa_cuenca_gee(R.lat, R.lon, out / "mapa_01_cuenca_gee.png",
                                 autor=R.proyecto.ingeniero,
                                 poligono_externo=R.cuenca_poligono,
                                 entradas_leyenda=leyenda_elev)
    if mapa_real:
        g["mapa_cuenca"] = mapa_real
        g["mapa_cuenca_real"] = True
    # Mapas temáticos 9.2-9.7 reales (drenaje, uso, cobertura, CN, pendientes,
    # coef. escorrentía). Se intentan SIEMPRE que haya polígono delineado por
    # MERIT Hydro — antes los saltábamos en modo_ligero, pero el modo ligero
    # debe afectar solo a simulaciones pesadas (HEC-HMS), no a mapas. Los 6
    # mapas se descargan en paralelo (~30-60 s adicionales). Cada mapa fallido
    # se queda con su versión esquemática.
    g["mapas_gee_motivo"] = None
    if R.cuenca_poligono is None:
        g["mapas_gee_motivo"] = (
            "Sin polígono delineado por MERIT Hydro 90 m — la cuenca no se "
            "pudo trazar desde el punto. Mapas 9.2–9.7 con esquemas "
            "sintéticos.")
        print(f"[pipeline] {g['mapas_gee_motivo']}", flush=True)
    else:
        from .mapas_gee import generar_todos_los_mapas_gee
        mapas_reales = generar_todos_los_mapas_gee(
            R.lat, R.lon, R.cuenca_poligono, out, autor=R.proyecto.ingeniero)
        stats = mapas_reales.pop("_stats", {})
        g.update(mapas_reales)
        if mapas_reales:
            g["mapas_tematicos_reales"] = sorted(mapas_reales.keys())
        else:
            g["mapas_gee_motivo"] = (
                "Cuenca delineada OK pero los 6 mapas temáticos GEE no se "
                "generaron (verificar GEE_SERVICE_ACCOUNT_JSON / "
                "GEE_PROJECT_ID en el Space, o el endpoint /gee_status).")
            print(f"[pipeline] {g['mapas_gee_motivo']}", flush=True)
        # Mapa de vulnerabilidad/riesgo hidroclimático (§14) — SOLO obra ABC.
        # R = V × A: reclasifica 1–5 las 7 variables del Manual y las combina
        # con pesos (Tabla 5.1) usando nuestros datasets GEE + las constantes
        # del tramo RVF (fisiografía, clima, rodadura).
        if getattr(R.tipo_obra, "clave", "") == "analisis_riesgo_abc":
            try:
                from concurrent.futures import (ThreadPoolExecutor,
                                                 TimeoutError as _FT)
                from .mapas_gee import mapa_riesgo_abc_gee
                from .riesgo_hidroclimatico_abc import tramo_referencia_para
                _t = tramo_referencia_para(R.lat, R.lon,
                                            getattr(R, "departamento", None))
                _v = _t.variables  # [0]=Fisiografía [1]=Clima [6]=Rodadura
                # Acotado con timeout por ronda: si GEE se cuelga generando el
                # mapa, se abandona el hilo colgado (wait=False) y se REINTENTA
                # en una ronda nueva. Esperamos hasta MAX_INTENTOS rondas a que
                # el mapa se genere; sólo tras agotarlas el informe sigue sin
                # ese mapa (degradación elegante). Nunca bloquea el worker para
                # siempre: cada ronda tiene su propio timeout acotado.
                import os as _os
                _MAX = int(_os.environ.get("HYDROFRA_MAPAS_REINTENTOS", "3"))
                _TO = int(_os.environ.get("HYDROFRA_MAPAS_TIMEOUT", "180"))
                _rabc = None
                for _intento in range(1, _MAX + 1):
                    _ex = ThreadPoolExecutor(max_workers=1)
                    try:
                        _fut = _ex.submit(
                            mapa_riesgo_abc_gee, R.lat, R.lon,
                            R.cuenca_poligono,
                            _v[0].valor, _v[1].valor, _v[6].valor,
                            out / "mapa_14_riesgo_abc_gee.png",
                            R.proyecto.ingeniero)
                        _rabc = _fut.result(timeout=_TO)
                    except _FT:
                        print(f"[pipeline] mapa riesgo ABC excedió {_TO} s "
                              f"(intento {_intento}/{_MAX})", flush=True)
                        _rabc = None
                    except Exception as _e:  # noqa: BLE001
                        print(f"[pipeline] mapa riesgo ABC error "
                              f"(intento {_intento}/{_MAX}): "
                              f"{type(_e).__name__}: {_e}", flush=True)
                        _rabc = None
                    finally:
                        try:
                            _ex.shutdown(wait=False, cancel_futures=True)
                        except TypeError:
                            _ex.shutdown(wait=False)
                    if _rabc and _rabc.get("path"):
                        break
                    if _intento < _MAX:
                        print(f"[pipeline] regenerando mapa riesgo ABC "
                              f"(intento {_intento + 1}/{_MAX})", flush=True)
                if _rabc and _rabc.get("path"):
                    g["mapa_riesgo_abc"] = _rabc["path"]
                    g["mapa_riesgo_abc_vmedia"] = _rabc.get("v_media")
                    print(f"[pipeline] mapa riesgo ABC OK (tramo {_t.ucod}, "
                           f"V media={_rabc.get('v_media')})", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[pipeline] mapa riesgo ABC falló: "
                       f"{type(e).__name__}: {e}", flush=True)
        # Si el §7 ya calculó cn_ponderado, conservamos ese valor (es el mismo
        # cálculo que el del mapa 9.5: media de MapBiomas → CN). Sólo lo
        # actualizamos cuando antes no se obtuvo.
        if stats.get("cn_ponderado") and R.cn_ponderado is None:
            R.cn_ponderado = float(stats["cn_ponderado"])
        # Pendiente media de LADERA del mapa 9.6 (Terrain.slope COP-DEM).
        # IMPORTANTE: es DESCRIPTIVA del terreno — NO se usa para el Tc.
        # El Tc usa la pendiente del CAUCE principal (S = ΔH/Lc), que es
        # mucho menor y ya está en R.morfologia.pendiente_media_mm. Antes
        # sobreescribíamos pendiente_media_mm con la de ladera (~50%), lo
        # que inflaba el Tc — ese bug queda revertido. Guardamos la
        # pendiente de ladera como dato aparte para reportarla en §9.
        if stats.get("pendiente_media_pct"):
            try:
                R.pendiente_ladera_pct = float(stats["pendiente_media_pct"])
                print(f"[pipeline] pendiente media de ladera (9.6): "
                       f"{R.pendiente_ladera_pct:.1f}% (descriptiva, NO "
                       f"usada en Tc — el Tc usa la pendiente del cauce "
                       f"{R.morfologia.pendiente_media_mm*100:.2f}%)",
                       flush=True)
            except Exception:  # noqa: BLE001
                pass
        # Susceptibilidad a la inundación del mapa 9.9 (índice HAND): % de área
        # con susceptibilidad alta/muy alta y HAND medio, para las conclusiones.
        if stats.get("inund_area_alta_pct") is not None:
            R.inund_area_alta_pct = float(stats["inund_area_alta_pct"])
        if stats.get("hand_medio_m") is not None:
            R.hand_medio_m = float(stats["hand_medio_m"])
        if stats.get("c_ponderado"):
            R.c_ponderado = float(stats["c_ponderado"])
            # Si Q max se calculó con C estimado, lo recalculamos con el C
            # ponderado real del mapa 9.7 para mantener §11 ↔ §9.7 consistentes.
            if R.qmax_entrada is not None and R.qmax_tabla is not None:
                try:
                    from .caudal_maximo import (EntradaQMax, tabla_caudal_maximo,
                                                  PERIODOS_QMAX_DEFAULT)
                    from .stats import cuantiles_para_periodos_retorno as _q_T
                    e = R.qmax_entrada
                    e2 = EntradaQMax(A_km2=e.A_km2, L_km=e.L_km,
                                      S_pct=e.S_pct, Sc_pct=e.Sc_pct,
                                      Tc_min=e.Tc_min, CN=e.CN,
                                      C=float(R.c_ponderado))
                    p24 = {int(row["T_anios"]): float(row["p24_mm"])
                           for _, row in _q_T(R.mejor_ajuste,
                                              PERIODOS_QMAX_DEFAULT).iterrows()}
                    R.qmax_tabla = tabla_caudal_maximo(e2, R.modelo_sherman, p24)
                    R.qmax_entrada = e2
                except Exception:  # noqa: BLE001
                    pass

    # Coef. de escorrentía del EVENTO de diseño por SCS-CN (C = Q/P), con la
    # P24 del período de retorno adoptado y el CN ponderado de la cuenca.
    try:
        cn_ev = R.cn_ponderado or getattr(R.morfologia, "cn", None)
        fila = R.cuantiles.loc[R.cuantiles["T_anios"] == R.T_diseno, "p24_mm"]
        P = float(fila.iloc[0]) if len(fila) else None
        if cn_ev and P and P > 0:
            S = 25400.0 / cn_ev - 254.0
            Ia = 0.2 * S
            Q = (P - Ia) ** 2 / (P - Ia + S) if P > Ia else 0.0
            R.c_evento = round(Q / P, 3)
            R.p24_diseno_mm = round(P, 1)
    except Exception:  # noqa: BLE001
        pass

    # Sensibilidad del caudal de diseño al cambio climático (TODOS los informes).
    try:
        from .sensibilidad_cc import analisis_sensibilidad_cc
        _q_dis = None
        if R.qmax_tabla is not None and len(R.qmax_tabla):
            _rh = (R.hec_hidrogramas_por_T or {}).get(int(R.T_diseno))
            if _rh is not None and getattr(_rh, "Q_pico_m3s", 0) > 0:
                _q_dis = float(_rh.Q_pico_m3s)
            else:
                _f = R.qmax_tabla.loc[R.qmax_tabla["T_anios"] == int(R.T_diseno)]
                _q_dis = float(_f["Q_mediana"].iloc[0]) if len(_f) else None
        _cn = R.cn_ponderado or getattr(R.morfologia, "cn", None)
        if R.p24_diseno_mm and _q_dis and _cn:
            R.sensibilidad_cc = analisis_sensibilidad_cc(
                R.p24_diseno_mm, _q_dis, _cn)
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] sensibilidad CC falló: {e}", flush=True)
