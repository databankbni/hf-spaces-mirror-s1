"""Resumen estadístico descriptivo de la serie anual máxima."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy import stats as sst


@dataclass
class EstadisticosDescriptivos:
    n: int
    media: float
    mediana: float
    minimo: float
    maximo: float
    rango: float
    desv_std: float        # σ muestral (ddof=1)
    varianza: float
    cv: float              # coef. de variación = σ/μ
    asimetria: float       # coef. de asimetría muestral (Fisher-Pearson)
    curtosis: float        # exceso de curtosis (g2)
    q1: float
    q3: float
    iqr: float
    p10: float
    p90: float
    p95: float
    p99: float
    suma: float
    error_estandar: float  # σ/√n
    ic95_media_low: float
    ic95_media_high: float

    def como_dict(self) -> dict[str, float | int]:
        return self.__dict__.copy()


def estadisticos_descriptivos(serie: Sequence[float]) -> EstadisticosDescriptivos:
    x = np.asarray(serie, dtype=float)
    n = x.size
    if n < 2:
        raise ValueError("Se requieren al menos 2 observaciones.")
    media = float(x.mean())
    desv = float(x.std(ddof=1))
    err = desv / np.sqrt(n)
    t_crit = float(sst.t.ppf(0.975, df=n - 1))
    return EstadisticosDescriptivos(
        n=n,
        media=media,
        mediana=float(np.median(x)),
        minimo=float(x.min()),
        maximo=float(x.max()),
        rango=float(x.max() - x.min()),
        desv_std=desv,
        varianza=float(desv ** 2),
        cv=float(desv / media) if media != 0 else float("nan"),
        asimetria=float(sst.skew(x, bias=False)),
        curtosis=float(sst.kurtosis(x, bias=False)),
        q1=float(np.percentile(x, 25)),
        q3=float(np.percentile(x, 75)),
        iqr=float(np.percentile(x, 75) - np.percentile(x, 25)),
        p10=float(np.percentile(x, 10)),
        p90=float(np.percentile(x, 90)),
        p95=float(np.percentile(x, 95)),
        p99=float(np.percentile(x, 99)),
        suma=float(x.sum()),
        error_estandar=float(err),
        ic95_media_low=float(media - t_crit * err),
        ic95_media_high=float(media + t_crit * err),
    )
