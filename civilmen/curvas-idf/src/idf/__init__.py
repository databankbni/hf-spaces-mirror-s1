"""Curvas IDF para diseño hidrológico de la pasarela peatonal.

Módulos:
- data: estaciones SENAMHI-Bolivia y generación sintética por coordenadas.
- stats: análisis de frecuencias (Normal, LogNormal, Gumbel, Pearson III, Log-Pearson III).
- disaggregation: desagregación de lluvia 24h a duraciones sub-diarias (Dyck-Peschke).
- idf: ajuste y evaluación del modelo IDF de Sherman (i = a·T^m / (d+b)^n).
- plotting: gráficos de curvas IDF, ajustes y diagnósticos.
"""

from .data import (
    EstacionSenamhi,
    estacion_mas_cercana,
    serie_anual_maxima_sintetica,
    ESTACIONES_SENAMHI,
)
from .stats import (
    AjusteDistribucion,
    ajustar_todas,
    seleccionar_mejor_ajuste,
    cuantiles_para_periodos_retorno,
)
from .disaggregation import desagregar_dyck_peschke
from .idf import ModeloIDF, ajustar_sherman, intensidad
from .plotting import (
    plot_curvas_idf,
    plot_ajuste_distribucion,
    plot_serie_anual_maxima,
)
from .summary import EstadisticosDescriptivos, estadisticos_descriptivos
from .consistency import (
    ResultadoPrueba,
    correr_todas as pruebas_consistencia,
    grubbs_beck,
    autocorrelacion_lag1,
    wald_wolfowitz_rachas,
    mann_kendall,
    pettitt,
)
from .data import estaciones_cercanas, interpolar_idw
from .obras import TipoObra, TIPOS_OBRA, obtener_tipo_obra
from .satelital import SerieSatelital, obtener_series_satelitales
from .comparacion import DecisionFuente, comparar_y_decidir
from .idf_models import (
    ModeloIDFGenerico,
    ajustar_todos_los_modelos,
    recomendar_modelo_por_datos,
    RESOLUCIONES_DATOS,
)
from .hechms import ResumenHecHms, resumen_hec_hms
from .hietograma import scs_tipo2, chicago
from .pipeline import ResultadoCompleto, ejecutar_pipeline
from .mapas import generar_todos_los_mapas
from .morfologia import MorfologiaCuenca, estimar_morfologia_desde_coordenadas
from .concentracion import (
    ResultadoTc,
    TcAdoptado,
    calcular_todas as calcular_tiempos_concentracion,
    adoptar_tc,
)
from .hietograma import Hietograma, bloques_alternos
from .proyecto import DatosProyecto, APP_NOMBRE, APP_VERSION
from .plotting import plot_tiempo_concentracion, plot_hietograma
from .report import generar_pdf

__all__ = [
    "EstacionSenamhi",
    "estacion_mas_cercana",
    "serie_anual_maxima_sintetica",
    "ESTACIONES_SENAMHI",
    "AjusteDistribucion",
    "ajustar_todas",
    "seleccionar_mejor_ajuste",
    "cuantiles_para_periodos_retorno",
    "desagregar_dyck_peschke",
    "ModeloIDF",
    "ajustar_sherman",
    "intensidad",
    "plot_curvas_idf",
    "plot_ajuste_distribucion",
    "plot_serie_anual_maxima",
    "plot_tiempo_concentracion",
    "plot_hietograma",
    "EstadisticosDescriptivos",
    "estadisticos_descriptivos",
    "ResultadoPrueba",
    "pruebas_consistencia",
    "grubbs_beck",
    "autocorrelacion_lag1",
    "wald_wolfowitz_rachas",
    "mann_kendall",
    "pettitt",
    "MorfologiaCuenca",
    "estimar_morfologia_desde_coordenadas",
    "ResultadoTc",
    "TcAdoptado",
    "calcular_tiempos_concentracion",
    "adoptar_tc",
    "Hietograma",
    "bloques_alternos",
    "DatosProyecto",
    "APP_NOMBRE",
    "APP_VERSION",
    "generar_pdf",
]
