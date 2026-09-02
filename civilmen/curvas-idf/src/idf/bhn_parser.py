"""Parser de PDFs de boletines hidrológicos SENAMHI.

El «BOLETIN DE MONITOREO DIARIO DE NIVELES» tiene una estructura tabular
relativamente estable:

- Encabezado: fecha del boletín, río/cuerpo de agua, estación.
- Tabla principal por estación con columnas:
    Estación · Río/Cuenca · Lectura nivel (m) · Variación 24h (m) ·
    Caudal estimado (m³/s) · Tendencia · Alerta
- Resumen meteorológico al pie.

Este módulo usa `pdfplumber` (pure Python, ~15 MB) para extraer texto y
tablas. La heurística de detección de tablas tolera variaciones de
maquetado entre años (los layouts de 2020 vs 2024 difieren ligeramente).

Cuando `pdfplumber` no está disponible (entorno mínimo), `extraer_tablas`
devuelve [] silenciosamente; el batch puede continuar con texto crudo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RegistroBHN:
    """Una observación diaria de una estación, parseada del boletín."""
    fecha_boletin: str           # ISO YYYY-MM-DD
    estacion: str
    rio: Optional[str] = None
    nivel_m: Optional[float] = None
    variacion_24h_m: Optional[float] = None
    caudal_m3s: Optional[float] = None
    tendencia: Optional[str] = None      # ASCENSO / DESCENSO / ESTABLE
    alerta: Optional[str] = None         # NORMAL / AMARILLA / NARANJA / ROJA
    fuente_pdf: Optional[str] = None     # ruta o URL


@dataclass
class ResultadoParseo:
    pdf: Path
    fecha_boletin: Optional[str] = None
    registros: list[RegistroBHN] = field(default_factory=list)
    texto_crudo: str = ""
    mensajes: list[str] = field(default_factory=list)


# ─────────────────── Helpers ───────────────────

_RE_FECHA = re.compile(
    r"(\d{1,2})\s*(?:de\s+)?"
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|setiembre|octubre|noviembre|diciembre)"
    r"\s*(?:de\s+)?(\d{4})", re.IGNORECASE)
_MES_NUM = {"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
              "julio":7,"agosto":8,"septiembre":9,"setiembre":9,"octubre":10,
              "noviembre":11,"diciembre":12}


def _detectar_fecha(texto: str) -> Optional[str]:
    """Localiza la fecha del boletín en el texto (formato ISO)."""
    m = _RE_FECHA.search(texto)
    if not m:
        return None
    dia = int(m.group(1))
    mes = _MES_NUM.get(m.group(2).lower())
    anio = int(m.group(3))
    if not mes:
        return None
    try:
        import datetime as _dt
        return _dt.date(anio, mes, dia).isoformat()
    except Exception:  # noqa: BLE001
        return None


_RE_NUM = re.compile(r"^-?\d+[\.,]?\d*$")


def _a_float(s) -> Optional[float]:
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    if not _RE_NUM.match(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


_RE_TENDENCIA = re.compile(
    r"(ASCENSO|DESCENSO|ESTABLE|EN AUMENTO|EN DESCENSO|EN BAJADA)",
    re.IGNORECASE)
_RE_ALERTA = re.compile(
    r"(ROJA|NARANJA|AMARILLA|NORMAL|VERDE)", re.IGNORECASE)


# ─────────────────── Parseo principal ───────────────────

def parsear_pdf(ruta: Path) -> ResultadoParseo:
    """Extrae registros estructurados de un PDF de boletín hidrológico.

    Estrategia: (1) extrae texto + tablas con pdfplumber; (2) detecta fecha;
    (3) recorre filas de tablas convirtiendo a RegistroBHN cuando los
    encabezados coinciden con el esquema BHN. Filas sin nivel ni caudal
    se descartan. Errores silenciosos quedan registrados en `mensajes`.
    """
    ruta = Path(ruta)
    res = ResultadoParseo(pdf=ruta)
    if not ruta.exists():
        res.mensajes.append(f"PDF no encontrado: {ruta}")
        return res

    try:
        import pdfplumber
    except ImportError:
        res.mensajes.append("pdfplumber no instalado — solo texto crudo")
        return res

    try:
        with pdfplumber.open(ruta) as pdf:
            texto_total = []
            for pagina in pdf.pages:
                t = pagina.extract_text() or ""
                texto_total.append(t)
            res.texto_crudo = "\n".join(texto_total)
            res.fecha_boletin = _detectar_fecha(res.texto_crudo)

            for pagina in pdf.pages:
                for tabla in pagina.extract_tables() or []:
                    if not tabla or len(tabla) < 2:
                        continue
                    cab = [str(c or "").strip().lower() for c in tabla[0]]
                    # Heurística: la tabla BHN tiene "estación" o "rio"
                    # como primera columna.
                    if not any("estaci" in c or "río" in c or "rio" in c
                                  for c in cab):
                        continue
                    res.registros.extend(
                        _parsear_filas_tabla(tabla, cab, res.fecha_boletin
                                              or "", str(ruta)))
    except Exception as e:  # noqa: BLE001
        res.mensajes.append(f"parser falló: {type(e).__name__}: {e}")
    return res


def _parsear_filas_tabla(tabla: list, cab: list, fecha: str,
                           fuente: str) -> list[RegistroBHN]:
    """Convierte una tabla con encabezado en una lista de RegistroBHN."""
    # Mapeo flexible de columnas
    def _idx(*aliases):
        for i, c in enumerate(cab):
            if any(a in c for a in aliases):
                return i
        return None

    idx_est = _idx("estaci")
    idx_rio = _idx("río", "rio", "cuerpo", "cuenca")
    idx_nivel = _idx("nivel", "lectura")
    idx_var = _idx("variaci", "delta")
    idx_q = _idx("caudal", "q m", "q (m")
    idx_tend = _idx("tendencia")
    idx_alerta = _idx("alerta")

    out = []
    for fila in tabla[1:]:
        if not fila or all((c is None or str(c).strip() == "") for c in fila):
            continue
        est = (str(fila[idx_est]).strip() if idx_est is not None
                and idx_est < len(fila) else "")
        if not est:
            continue
        nivel = _a_float(fila[idx_nivel]) if (idx_nivel is not None
                                                   and idx_nivel < len(fila)) else None
        var = _a_float(fila[idx_var]) if (idx_var is not None
                                                and idx_var < len(fila)) else None
        q = _a_float(fila[idx_q]) if (idx_q is not None
                                            and idx_q < len(fila)) else None
        # Si no hay ningún valor numérico, descarta
        if nivel is None and q is None:
            continue
        rio = (str(fila[idx_rio]).strip() if idx_rio is not None
                 and idx_rio < len(fila) else None)
        tend = (str(fila[idx_tend]).strip() if idx_tend is not None
                  and idx_tend < len(fila) else None)
        alerta = (str(fila[idx_alerta]).strip() if idx_alerta is not None
                    and idx_alerta < len(fila) else None)
        if tend:
            mt = _RE_TENDENCIA.search(tend)
            tend = mt.group(1).upper() if mt else tend.upper()
        if alerta:
            ma = _RE_ALERTA.search(alerta)
            alerta = ma.group(1).upper() if ma else alerta.upper()
        out.append(RegistroBHN(
            fecha_boletin=fecha, estacion=est, rio=rio,
            nivel_m=nivel, variacion_24h_m=var, caudal_m3s=q,
            tendencia=tend, alerta=alerta, fuente_pdf=fuente))
    return out
