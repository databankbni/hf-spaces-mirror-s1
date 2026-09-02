"""Integración con HEC-RAS / HEC-HMS vía ras-commander y hms-commander.

Cubre tres necesidades, con distinta viabilidad según el entorno:

1. **Lectura de resultados HEC-RAS** (WSE, velocidad, caudal) desde el HDF de
   un plan. Funciona en el Space (Linux headless): usa ``h5py`` puro y, si está
   instalado ``ras-commander``, lo aprovecha como backend más completo. Permite
   que el usuario suba el ``.pXX.hdf`` que generó en su PC y HYDROFRA use el
   **tirante/velocidad reales** en el informe, en vez del cálculo 1D interno.

2. **Lectura de hidrogramas HEC-HMS (DSS)**. Requiere Java (``pyjnius``) o
   ``pydsstools``; en el Space normalmente NO está disponible → degrada con un
   mensaje claro.

3. **Ejecución de los motores** (HEC-RAS/HEC-HMS). Solo es posible en una
   máquina con el software HEC instalado (Windows). En el Space Linux estas
   funciones informan que no es posible y no intentan nada.

Referencias
-----------
- ras-commander (CLB Engineering) — https://rascommander.info/
- hms-commander — https://hms-commander.readthedocs.io/
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

# Paths HDF de resultados 1D de HEC-RAS (coherentes con ras-commander).
_BASE_TS = ("Results/Unsteady/Output/Output Blocks/Base Output/"
            "Unsteady Time Series")
_XSEC = f"{_BASE_TS}/Cross Sections"
_TIME_STAMP = f"{_BASE_TS}/Time Date Stamp (ms)"


# ─────────────────── Estructuras de resultado ───────────────────

@dataclass
class SeccionHECRAS:
    river: str
    reach: str
    station: str
    name: str
    wse_max_m: float
    vel_total_max_ms: float
    vel_channel_max_ms: float
    flow_max_m3s: float
    # Cota de fondo (thalweg) de la geometría y tirante = WSE − fondo.
    min_ch_el_m: float | None = None
    tirante_max_m: float | None = None

    @property
    def station_num(self) -> float:
        """Progresiva como número (para ordenar aguas arriba/abajo)."""
        try:
            return float(str(self.station).replace("*", "").strip())
        except (TypeError, ValueError):
            return float("nan")


@dataclass
class ResultadosHECRAS:
    fuente: str                 # "ras-commander" | "h5py"
    plan_hdf: str
    n_secciones: int
    secciones: list[SeccionHECRAS] = field(default_factory=list)
    wse_max_global_m: float = 0.0
    vel_max_global_ms: float = 0.0
    flow_max_global_m3s: float = 0.0

    def seccion_critica(self) -> SeccionHECRAS | None:
        """Sección de mayor nivel de agua (WSE) — la más desfavorable."""
        if not self.secciones:
            return None
        return max(self.secciones, key=lambda s: s.wse_max_m)

    def seccion_aguas_abajo(self) -> SeccionHECRAS | None:
        """Sección más aguas abajo (menor progresiva de río)."""
        secs = [s for s in self.secciones if s.station_num == s.station_num]
        if not secs:
            return self.secciones[0] if self.secciones else None
        return min(secs, key=lambda s: s.station_num)

    def tw_aguas_abajo_m(self) -> float | None:
        """Tirante de descarga (TW) real = WSE − fondo en la sección aguas
        abajo. None si la geometría del HDF no trae la cota de fondo."""
        s = self.seccion_aguas_abajo()
        if s is None:
            return None
        return s.tirante_max_m


# ─────────────────── Lectura de resultados HEC-RAS ───────────────────

def _decode(v) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", "ignore").strip()
    return str(v).strip()


def _leer_hdf_h5py(hdf_path: str) -> ResultadosHECRAS:
    """Lee los máximos por sección directamente del HDF con h5py puro.

    No requiere ras-commander ni GDAL: replica los paths de resultados 1D
    no permanentes de HEC-RAS.
    """
    import h5py
    import numpy as np

    with h5py.File(hdf_path, "r") as f:
        if _XSEC not in f:
            raise ValueError(
                "El HDF no contiene resultados 1D de secciones transversales "
                f"en «{_XSEC}». ¿Es un plan con salida no permanente (unsteady) "
                "ya calculado?")
        base = f[_XSEC]
        attrs = base["Cross Section Attributes"][:]
        rivers = [_decode(a["River"]) for a in attrs]
        reaches = [_decode(a["Reach"]) for a in attrs]
        stations = [_decode(a["Station"]) for a in attrs]
        names = [_decode(a["Name"]) if "Name" in attrs.dtype.names else ""
                 for a in attrs]

        def _max_por_seccion(nombre):
            if nombre not in base:
                return None
            arr = base[nombre][:]
            return np.max(arr, axis=0) if arr.ndim == 2 else arr

        ws = _max_por_seccion("Water Surface")
        vt = _max_por_seccion("Velocity Total")
        vc = _max_por_seccion("Velocity Channel")
        fl = _max_por_seccion("Flow")
        thalweg = _thalweg_por_seccion(f)  # {(river,reach,rs): cota_fondo}
        n = len(rivers)
        secs = []
        for i in range(n):
            ws_i = float(ws[i]) if ws is not None else float("nan")
            fondo = thalweg.get((rivers[i], reaches[i], stations[i]))
            tir = (ws_i - fondo) if (fondo is not None and ws_i == ws_i) else None
            secs.append(SeccionHECRAS(
                river=rivers[i], reach=reaches[i], station=stations[i],
                name=names[i] if i < len(names) else "",
                wse_max_m=ws_i,
                vel_total_max_ms=float(vt[i]) if vt is not None else float("nan"),
                vel_channel_max_ms=float(vc[i]) if vc is not None else float("nan"),
                flow_max_m3s=float(fl[i]) if fl is not None else float("nan"),
                min_ch_el_m=fondo, tirante_max_m=tir))
    return _armar_resultado("h5py", hdf_path, secs)


def _thalweg_por_seccion(f) -> dict:
    """Cota de fondo (mín. elevación) por sección desde la geometría del HDF.

    Devuelve {(river, reach, rs): cota_fondo_m}. Vacío si la geometría no está
    en este HDF (p. ej. un HDF solo de resultados)."""
    import numpy as np
    g = "Geometry/Cross Sections"
    try:
        if g not in f:
            return {}
        info = f[f"{g}/Station Elevation Info"][:]
        vals = f[f"{g}/Station Elevation Values"][:]
        attrs = f[f"{g}/Attributes"][:]
    except Exception:  # noqa: BLE001
        return {}
    campos = attrs.dtype.names or ()
    out = {}
    for i in range(len(info)):
        ini, cnt = int(info[i][0]), int(info[i][1])
        if cnt <= 0:
            continue
        elev = vals[ini:ini + cnt]
        # Columna 1 = elevación (columna 0 = estación transversal).
        col = elev[:, 1] if elev.ndim == 2 else elev
        fondo = float(np.min(col))
        riv = _decode(attrs[i]["River"]) if "River" in campos else ""
        rea = _decode(attrs[i]["Reach"]) if "Reach" in campos else ""
        rs = _decode(attrs[i]["RS"]) if "RS" in campos else str(i)
        out[(riv, rea, rs)] = fondo
    return out


def _leer_hdf_rascommander(hdf_path: str) -> ResultadosHECRAS:
    """Backend ras-commander: usa el resumen de secciones si está instalado."""
    from ras_commander import HdfResultsXsec  # puede fallar si falta GDAL
    ds = HdfResultsXsec.get_xsec_timeseries(hdf_path)
    import numpy as np

    def _sv(var):
        if var in ds:
            return np.max(ds[var].values, axis=0)
        mx = f"Maximum_{var}"
        return ds[mx].values if mx in ds else None

    rivers = [_decode(x) for x in ds.coords.get("River", ds.coords.get(
        "cross_section")).values]
    reaches = ([_decode(x) for x in ds.coords["Reach"].values]
               if "Reach" in ds.coords else [""] * len(rivers))
    stations = ([_decode(x) for x in ds.coords["Station"].values]
                if "Station" in ds.coords else [""] * len(rivers))
    names = ([_decode(x) for x in ds.coords["Name"].values]
             if "Name" in ds.coords else [""] * len(rivers))
    ws = _sv("Water_Surface")
    vt = _sv("Velocity_Total")
    vc = _sv("Velocity_Channel")
    fl = _sv("Flow")
    secs = []
    for i in range(len(rivers)):
        secs.append(SeccionHECRAS(
            river=rivers[i], reach=reaches[i], station=stations[i],
            name=names[i],
            wse_max_m=float(ws[i]) if ws is not None else float("nan"),
            vel_total_max_ms=float(vt[i]) if vt is not None else float("nan"),
            vel_channel_max_ms=float(vc[i]) if vc is not None else float("nan"),
            flow_max_m3s=float(fl[i]) if fl is not None else float("nan")))
    return _armar_resultado("ras-commander", hdf_path, secs)


def _armar_resultado(fuente, hdf_path, secs) -> ResultadosHECRAS:
    import math
    val = [s.wse_max_m for s in secs if s.wse_max_m == s.wse_max_m]
    vv = [s.vel_total_max_ms for s in secs
          if s.vel_total_max_ms == s.vel_total_max_ms]
    vf = [s.flow_max_m3s for s in secs if s.flow_max_m3s == s.flow_max_m3s]
    return ResultadosHECRAS(
        fuente=fuente, plan_hdf=os.path.basename(hdf_path),
        n_secciones=len(secs), secciones=secs,
        wse_max_global_m=max(val) if val else math.nan,
        vel_max_global_ms=max(vv) if vv else math.nan,
        flow_max_global_m3s=max(vf) if vf else math.nan)


def leer_resultados_hecras(hdf_path: str,
                           preferir_rascommander: bool = True
                           ) -> ResultadosHECRAS | None:
    """Lee los resultados 1D de un plan HEC-RAS (.pXX.hdf).

    Intenta ras-commander (si está instalado) y cae a h5py puro. Devuelve
    None si el archivo no existe o no tiene resultados legibles.
    """
    if not hdf_path or not os.path.exists(hdf_path):
        return None
    if preferir_rascommander:
        try:
            return _leer_hdf_rascommander(hdf_path)
        except Exception:  # noqa: BLE001 — falta GDAL/geopandas o API distinta
            pass
    try:
        return _leer_hdf_h5py(hdf_path)
    except Exception as e:  # noqa: BLE001
        print(f"[hec_commander] no se pudo leer el HDF: "
              f"{type(e).__name__}: {str(e)[:160]}", flush=True)
        return None


# ─────────────────── Lectura de hidrogramas HEC-HMS (DSS) ───────────────────

def leer_hidrograma_dss(dss_path: str, pathname: str | None = None):
    """Lee una serie (hidrograma) de un archivo DSS de HEC-HMS.

    Requiere ``ras-commander[dss]`` (pyjnius + Java) o ``pydsstools``. En el
    Space normalmente no hay JVM → devuelve None con un mensaje.
    Devuelve un ``pandas.DataFrame`` (columnas: fecha, valor) o None.
    """
    if not dss_path or not os.path.exists(dss_path):
        return None
    # Intento 1: pydsstools (más portable si está disponible).
    try:
        from pydsstools.heclib.dss import HecDss  # type: ignore
        import pandas as pd
        with HecDss.Open(dss_path) as dss:
            paths = [pathname] if pathname else dss.getPathnameList("/*/*/*/*/*/*/")
            if not paths:
                return None
            ts = dss.read_ts(paths[0])
            return pd.DataFrame({"fecha": ts.pytimes, "valor": ts.values})
    except Exception:  # noqa: BLE001
        pass
    # Intento 2: ras-commander (HmsDss / HdfBase DSS ops, requiere Java).
    try:
        from ras_commander import HdfBase  # type: ignore  # noqa: F401
        # La API DSS de ras-commander requiere JVM (pyjnius); si no hay, falla.
        raise RuntimeError("DSS vía ras-commander requiere JVM (pyjnius).")
    except Exception as e:  # noqa: BLE001
        print(f"[hec_commander] lectura DSS no disponible: "
              f"{type(e).__name__}: {str(e)[:140]}", flush=True)
        return None


# ─────────────────── Ejecución de motores (solo desktop) ───────────────────

def _motor_no_disponible(motor: str) -> RuntimeError:
    return RuntimeError(
        f"La ejecución de {motor} requiere una estación de trabajo Windows con "
        f"{motor} instalado; no es posible en el Space Linux headless. Corré la "
        "simulación en tu PC y subí los resultados (HDF de HEC-RAS o DSS de "
        "HEC-HMS) para que HYDROFRA los use en el informe.")


def correr_hechms(project_dir: str, run: str,
                  hms_version: str | None = None) -> str:
    """Ejecuta un run de HEC-HMS vía hms-commander (solo desktop con HMS)."""
    if sys.platform != "win32" and not os.environ.get("HEC_COMMANDER_FORCE"):
        raise _motor_no_disponible("HEC-HMS")
    from hms_commander import init_hms_project, HmsCmdr  # type: ignore
    init_hms_project(project_dir)
    HmsCmdr.compute_run(run)
    return run


def correr_escenarios_hechms(project_dir: str, runs: list[str]) -> list[str]:
    """Ejecuta varios runs de HEC-HMS en paralelo (uno por período de retorno).

    Solo desktop con HEC-HMS instalado. Usa ``HmsCmdr.compute_parallel`` si
    está disponible; si no, cae a ejecución secuencial.
    """
    if sys.platform != "win32" and not os.environ.get("HEC_COMMANDER_FORCE"):
        raise _motor_no_disponible("HEC-HMS")
    from hms_commander import init_hms_project, HmsCmdr  # type: ignore
    init_hms_project(project_dir)
    if hasattr(HmsCmdr, "compute_parallel"):
        HmsCmdr.compute_parallel(runs)
    else:
        for r in runs:
            HmsCmdr.compute_run(r)
    return runs


def correr_hecras(project_path: str, plan: str) -> str:
    """Ejecuta un plan de HEC-RAS vía ras-commander (solo desktop con RAS)."""
    if sys.platform != "win32" and not os.environ.get("HEC_COMMANDER_FORCE"):
        raise _motor_no_disponible("HEC-RAS")
    from ras_commander import init_ras_project, RasCmdr  # type: ignore
    init_ras_project(project_path, "6.5")
    RasCmdr.compute_plan(plan)
    return plan


# ─────────────────── Diagnóstico ───────────────────

def estado() -> dict:
    """Diagnóstico de qué backends están disponibles (para /hec_status)."""
    def _hay(mod):
        try:
            __import__(mod)
            return True
        except Exception:  # noqa: BLE001
            return False
    return {
        "plataforma": sys.platform,
        "lectura_hdf_h5py": _hay("h5py"),
        "ras_commander": _hay("ras_commander"),
        "hms_commander": _hay("hms_commander"),
        "dss_pydsstools": _hay("pydsstools"),
        "puede_ejecutar_motores": sys.platform == "win32",
        "nota": ("En Linux se pueden LEER resultados (HDF/DSS) pero NO ejecutar "
                 "los motores HEC; eso requiere Windows con el software "
                 "instalado."),
    }
