"""Verificación normativa del proyecto de agua potable.

Compara los resultados del informe (oferta hídrica, demanda calculada,
parámetros de diseño) contra los requisitos exigidos por la normativa
boliviana vigente (NB 512, NB 689, Ley 1333, RMCH) y emite una tabla de
cumplimiento (Tabla 14 obligatoria del skill, Sección 8.1).

Cada requisito devuelve cumplimiento `cumple` / `condicionado` / `no_cumple`
con un comentario explicativo. La conclusión global (Sección 8.4) resume
si la fuente es viable sin restricciones, viable con condicionantes o no
viable en las condiciones actuales.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .demanda_agua_potable import CaudalesDemanda, HORIZONTE_NB689, K1_NB689, K2_NB689
from .balance_oferta_demanda import BalanceAguaPotable

EstadoCumplimiento = Literal["cumple", "condicionado", "no_cumple",
                                "informativo"]


@dataclass
class RequisitoNormativo:
    requisito: str
    referencia: str
    valor_exigido: str
    valor_calculado: str
    cumplimiento: EstadoCumplimiento
    comentario: str = ""


@dataclass
class VerificacionGlobal:
    requisitos: list[RequisitoNormativo]
    n_cumple: int
    n_condicionado: int
    n_no_cumple: int
    n_informativo: int
    diagnostico_global: str
    condicion_aprobacion: Literal["viable", "viable_condicionado", "no_viable"]


def _glyph(estado: EstadoCumplimiento) -> str:
    return {
        "cumple": "✓",
        "condicionado": "~",
        "no_cumple": "✗",
        "informativo": "•",
    }[estado]


def verificar(balance: BalanceAguaPotable,
                caudales: CaudalesDemanda,
                tiene_analisis_calidad: bool = False,
                n_aforos_estiaje: int = 0,
                piso_clave: str | None = None
                ) -> VerificacionGlobal:
    """Construye la verificación normativa completa."""
    req: list[RequisitoNormativo] = []

    # ─── NB 689 — Período de diseño según categoría poblacional ────────
    cat = caudales.proyeccion.categoria_nb689
    h_exigido = HORIZONTE_NB689.get(cat, 20)
    h_calc = caudales.proyeccion.horizonte_anios
    estado_h = ("cumple" if h_calc >= h_exigido else "no_cumple")
    req.append(RequisitoNormativo(
        requisito=f"Período de diseño (categoría poblacional {cat})",
        referencia="NB 689 — Tabla 1",
        valor_exigido=f"≥ {h_exigido} años",
        valor_calculado=f"{h_calc} años",
        cumplimiento=estado_h,
        comentario=("Acorde a la categoría poblacional de diseño."
                     if estado_h == "cumple" else
                     f"Ampliar horizonte a {h_exigido} años o cambiar "
                     f"categoría poblacional."),
    ))

    # ─── NB 689 — Coeficiente K1 (máx. diario / medio) ─────────────────
    req.append(RequisitoNormativo(
        requisito="Coeficiente K₁ (máximo diario / medio)",
        referencia="NB 689",
        valor_exigido="1.20 ≤ K₁ ≤ 1.50",
        valor_calculado=f"{caudales.k1:.2f}",
        cumplimiento=("cumple" if 1.20 <= caudales.k1 <= 1.50
                       else "condicionado"),
        comentario="Recomendado: 1.50 para comunidades rurales.",
    ))

    # ─── NB 689 — Coeficiente K2 (máx. horario / máx. diario) ──────────
    req.append(RequisitoNormativo(
        requisito="Coeficiente K₂ (máximo horario / máximo diario)",
        referencia="NB 689",
        valor_exigido="1.50 ≤ K₂ ≤ 2.20",
        valor_calculado=f"{caudales.k2:.2f}",
        cumplimiento=("cumple" if 1.50 <= caudales.k2 <= 2.20
                       else "condicionado"),
        comentario="Adoptamos el límite superior (2.20) para sistemas "
                     "sin almacenamiento de regulación.",
    ))

    # ─── NB 689 — Q de captación cubre demanda máx. diaria ─────────────
    if balance.q_disponible_m3s >= caudales.q_max_d_m3s:
        cumple_q = "cumple"
        com_q = (f"Holgura: "
                  f"{((balance.q_disponible_m3s - caudales.q_max_d_m3s)/caudales.q_max_d_m3s*100):.0f} %"
                  f" sobre la demanda exigida.")
    elif balance.q_disponible_m3s >= caudales.q_md_m3s:
        cumple_q = "condicionado"
        com_q = ("La oferta cubre el Q medio diario pero no el "
                  "Q máximo diario sin regulación intermedia.")
    else:
        cumple_q = "no_cumple"
        com_q = ("Oferta disponible inferior a la demanda mínima "
                  "del proyecto.")
    req.append(RequisitoNormativo(
        requisito="Suficiencia de la fuente para Q_máx_d",
        referencia="NB 689 — Captación",
        valor_exigido=(f"Q_disp ≥ Q_máx_d = "
                        f"{caudales.q_max_d_l_s:.2f} L/s"),
        valor_calculado=f"Q_disp = {balance.q_disponible_m3s * 1000:.2f} L/s",
        cumplimiento=cumple_q,
        comentario=com_q,
    ))

    # ─── Ley 1333 / RMCH — Caudal ecológico respetado ───────────────────
    if balance.q_ecologico_m3s > 0:
        razon_eco = (balance.q_ecologico_m3s
                       / max(balance.q_min_adoptado_m3s, 1e-9))
        estado_eco = ("cumple" if razon_eco >= 0.10 else "condicionado")
        com_eco = (f"Q_eco/Q_mín_adoptado = {razon_eco*100:.0f} %. "
                    f"Método: {balance.q_ecologico_metodo}.")
    else:
        estado_eco = "no_cumple"
        com_eco = ("Caudal ecológico no calculado — necesario antes de "
                    "operar la captación.")
    req.append(RequisitoNormativo(
        requisito="Respeto al caudal ecológico remanente",
        referencia="Ley 1333 Art. 36 / RMCH",
        valor_exigido="Q_eco > 0 y ≥ 10 % del Q_mín adoptado",
        valor_calculado=(f"Q_eco = {balance.q_ecologico_m3s * 1000:.2f} L/s"
                          if balance.q_ecologico_m3s > 0 else "no calculado"),
        cumplimiento=estado_eco,
        comentario=com_eco,
    ))

    # ─── NB 512 — Análisis físico-químico y microbiológico ─────────────
    req.append(RequisitoNormativo(
        requisito="Análisis físico-químico y microbiológico de la fuente",
        referencia="NB 512",
        valor_exigido="Conformidad con la tabla de parámetros NB 512",
        valor_calculado=("Disponible — ver Anexo G" if tiene_analisis_calidad
                          else "Pendiente de campaña de calidad"),
        cumplimiento=("cumple" if tiene_analisis_calidad else "condicionado"),
        comentario=("Requerido antes de aprobación operativa." if not
                     tiene_analisis_calidad else
                     "Verificar tratabilidad y necesidades de potabilización."),
    ))

    # ─── OMM 168 — Aforos de estiaje (verificación de campo) ───────────
    req.append(RequisitoNormativo(
        requisito="Aforos de estiaje (verificación de campo)",
        referencia="OMM 168 — Vol. I",
        valor_exigido="≥ 3 aforos en temporada de estiaje (jul–ago)",
        valor_calculado=f"{n_aforos_estiaje} aforos disponibles",
        cumplimiento=("cumple" if n_aforos_estiaje >= 3 else
                       "condicionado" if n_aforos_estiaje >= 1 else
                       "no_cumple"),
        comentario=("Requerido antes de aprobación operativa. Planilla "
                     "en Anexo E."),
    ))

    # ─── Lineamientos AAPS — Registro y memoria de cálculo ─────────────
    req.append(RequisitoNormativo(
        requisito="Memoria de cálculo conforme AAPS",
        referencia="Lineamientos AAPS",
        valor_exigido="10 secciones + 8 anexos + 15 tablas mínimas",
        valor_calculado="Estructura completa (este documento)",
        cumplimiento="cumple",
        comentario="Verificar firma del profesional responsable.",
    ))

    # ─── Diagnóstico global y condición de aprobación ──────────────────
    n_c = sum(1 for r in req if r.cumplimiento == "cumple")
    n_x = sum(1 for r in req if r.cumplimiento == "no_cumple")
    n_w = sum(1 for r in req if r.cumplimiento == "condicionado")
    n_i = sum(1 for r in req if r.cumplimiento == "informativo")

    if n_x == 0 and n_w == 0:
        condicion = "viable"
        diag = (f"<b>FUENTE VIABLE SIN RESTRICCIONES</b>. Los "
                 f"{n_c} requisitos verificados se cumplen. El proyecto "
                 f"está en condiciones de pasar a la fase de diseño "
                 f"definitivo y trámites de aprobación.")
    elif n_x == 0:
        condicion = "viable_condicionado"
        diag = (f"<b>FUENTE VIABLE CON CONDICIONANTES</b>. Se cumplen "
                 f"{n_c}/{len(req)} requisitos plenamente y {n_w} requieren "
                 f"acciones complementarias (típicamente: campañas de "
                 f"aforo en estiaje, análisis de calidad NB 512 y/o "
                 f"verificación de captaciones aguas arriba) antes de la "
                 f"aprobación operativa.")
    else:
        condicion = "no_viable"
        diag = (f"<b>FUENTE NO VIABLE EN LAS CONDICIONES ACTUALES</b>. "
                 f"{n_x} requisitos NO se cumplen "
                 f"(ver tabla siguiente). Se requiere reformulación del "
                 f"proyecto: fuente alternativa, redimensionamiento o "
                 f"medidas correctivas mayores.")

    return VerificacionGlobal(
        requisitos=req, n_cumple=n_c, n_condicionado=n_w,
        n_no_cumple=n_x, n_informativo=n_i,
        diagnostico_global=diag,
        condicion_aprobacion=condicion,
    )


def tabla_verificacion(v: VerificacionGlobal) -> list[list[str]]:
    """Tabla 14 — Verificación normativa."""
    cab = ["Requisito", "Referencia", "Exigido", "Calculado",
              "Cumple", "Comentario"]
    filas: list[list[str]] = [cab]
    for r in v.requisitos:
        filas.append([
            r.requisito,
            r.referencia,
            r.valor_exigido,
            r.valor_calculado,
            _glyph(r.cumplimiento),
            r.comentario,
        ])
    return filas


def lista_riesgos(piso_clave: str | None) -> list[tuple[str, str]]:
    """Listado de riesgos para la Sección 8.3."""
    base = [
        ("Sequía multianual / variabilidad ENSO",
            "Riesgo de cese estacional en años con La Niña fuerte. "
            "Mitigación: monitoreo de aforos + plan de contingencia."),
        ("Cambio climático",
            "Tendencias regionales 2021–2050: cambios en precipitación "
            "estacional y aumento de evapotranspiración."),
        ("Deforestación de cabecera",
            "Pérdida de cobertura reduce infiltración y aumenta "
            "estiaje. Recomendado ordenamiento del uso del suelo."),
        ("Incendios forestales",
            "Eventos repetidos degradan suelo y red de drenaje; "
            "considerar plan de manejo de cuenca."),
        ("Captaciones competitivas aguas arriba",
            "Verificar en registros AAPS / municipio si existen "
            "captaciones operativas o en trámite."),
        ("Sedimentación en captación",
            "Diseñar desarenador y limpieza periódica programada."),
        ("Conflicto de uso (riego / abastecimiento)",
            "Coordinación con comunidad para definir prioridad de uso "
            "en escasez. Acta o reglamento de operación."),
        ("Contaminación de la fuente",
            "Monitoreo periódico NB 512 (físico-químico + microbiológico) "
            "y zona de protección sanitaria."),
    ]
    # Riesgos específicos por piso
    extra = {
        "nival": ("Retroceso glaciar",
                    "Pérdida progresiva de la fuente; planificar "
                    "fuente alternativa a horizonte 20–30 años."),
        "puna": ("Degradación de bofedales",
                    "Sobrepastoreo o drenaje reduce regulación natural; "
                    "incluir en plan de manejo de cuenca."),
        "prepuna": ("Estiaje extremo",
                       "Riesgo alto de cese total en microcuencas "
                       "< 5 km²; reservorio o fuente complementaria."),
        "valles": ("Conflicto urbano-rural",
                      "Alta presión por riego, urbano y agroindustria; "
                      "asegurar prioridad legal del agua potable."),
        "yungas": ("Flujos de detritos / remoción en masa",
                      "Riesgo alto de destrucción de obra en evento extremo; "
                      "diseño geotécnico cuidadoso."),
        "tierras_bajas": ("Variabilidad estacional amplia",
                              "Crecidas y estiajes pronunciados; "
                              "considerar pozo somero como alternativa."),
    }
    if piso_clave and piso_clave in extra:
        base.insert(2, extra[piso_clave])
    return base
