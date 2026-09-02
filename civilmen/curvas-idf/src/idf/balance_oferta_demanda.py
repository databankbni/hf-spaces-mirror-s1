"""Balance oferta-demanda para sistema de agua potable.

Compila los resultados de los métodos de estimación de caudal mínimo
(Secciones 5.1–5.4), aplica la restricción ambiental (Q ecológico
adoptado, Sección 5.5), descuenta la demanda de agua potable (Sección 6)
y diagnostica si el aprovechamiento es viable, marginal o no recomendable
(Sección 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EstadoBalance = Literal["positivo", "restringido", "negativo"]


@dataclass
class EstimacionMetodo:
    """Una fila de la tabla 'Síntesis de oferta' (Sección 7.1)."""
    metodo: str
    q_min_m3s: float | None
    base_datos: str
    confiabilidad: Literal["alta", "media", "baja", "no_aplicable"]
    observacion: str = ""


@dataclass
class BalanceAguaPotable:
    estimaciones: list[EstimacionMetodo]
    q_min_adoptado_m3s: float          # Sección 5.7 — más conservador
    metodo_adoptado: str
    factor_seguridad: float            # 1.0 si confiabilidad alta; > 1 si no
    q_ecologico_m3s: float             # Sección 5.5 — Tennant / Tessman / etc.
    q_ecologico_metodo: str
    q_disponible_m3s: float            # = Q_min_adoptado − Q_ecológico
    q_demanda_max_d_m3s: float         # Sección 6 — Q_máx_d
    saldo_m3s: float                   # Q_disp − Q_demanda
    estado: EstadoBalance
    interpretacion: str = ""
    recomendaciones: list[str] = field(default_factory=list)


def _clasificar_estado(saldo: float, q_demanda: float) -> EstadoBalance:
    """Positivo: saldo ≥ 50 % de Q_demanda; restringido: 0 ≤ saldo < 50 %;
    negativo: saldo < 0."""
    if saldo < 0:
        return "negativo"
    if saldo < 0.5 * q_demanda:
        return "restringido"
    return "positivo"


def _interpretar(estado: EstadoBalance,
                    saldo: float, q_disponible: float,
                    q_demanda: float) -> tuple[str, list[str]]:
    pct = 100 * saldo / max(q_demanda, 1e-9)
    if estado == "positivo":
        txt = (f"<b>BALANCE POSITIVO</b>. El caudal aprovechable "
                f"({q_disponible*1000:.2f} L/s) cubre holgadamente la demanda "
                f"máxima diaria proyectada ({q_demanda*1000:.2f} L/s) con un "
                f"margen de seguridad de {pct:.0f} %. La fuente es <b>viable "
                f"sin restricciones</b> en el horizonte de diseño.")
        recos = [
            "Mantener monitoreo de aforo anual en estiaje para validar la "
            "estimación adoptada.",
            "Proteger la zona de recarga (cabecera de cuenca) mediante "
            "ordenamiento del uso del suelo.",
            "Programar revisión del estudio a mitad del horizonte de diseño.",
        ]
    elif estado == "restringido":
        txt = (f"<b>BALANCE RESTRINGIDO</b>. El caudal aprovechable "
                f"({q_disponible*1000:.2f} L/s) cubre la demanda "
                f"({q_demanda*1000:.2f} L/s) pero el margen es ajustado "
                f"({pct:.0f} %). La fuente es <b>viable con condicionantes</b> "
                f"y se recomienda regulación intermedia.")
        recos = [
            "Incorporar reservorio de regulación diaria/semanal para "
            "absorber picos del Q máximo horario.",
            "Repetir aforos de estiaje al menos 3 años consecutivos para "
            "reducir la incertidumbre.",
            "Vigilar y limitar nuevas captaciones aguas arriba.",
            "Evaluar fuente complementaria como respaldo estacional.",
        ]
    else:  # negativo
        txt = (f"<b>BALANCE NEGATIVO</b>. El caudal aprovechable "
                f"({q_disponible*1000:.2f} L/s) es <b>insuficiente</b> para "
                f"atender la demanda máxima diaria ({q_demanda*1000:.2f} L/s); "
                f"déficit de {abs(saldo)*1000:.2f} L/s. La fuente <b>no es "
                f"recomendable</b> en las condiciones actuales sin medidas "
                f"correctivas mayores.")
        recos = [
            "Evaluar fuente alternativa (manantial, galería filtrante, "
            "pozo somero).",
            "Si la fuente debe mantenerse, dimensionar reservorio de "
            "regulación interanual (almacenamiento estacional).",
            "Revisar dotación adoptada y ajustar el nivel de servicio "
            "si es aceptable para la comunidad.",
            "Revisar la proyección poblacional y considerar fases "
            "incrementales del proyecto.",
            "Plantear cambio de fuente para etapas posteriores del "
            "horizonte de diseño.",
        ]
    return txt, recos


def construir_balance(estimaciones: list[EstimacionMetodo],
                         q_ecologico_m3s: float,
                         q_ecologico_metodo: str,
                         q_demanda_max_d_m3s: float,
                         factor_seguridad: float = 1.0
                         ) -> BalanceAguaPotable:
    """Selecciona el Q mín adoptado y construye el diagnóstico.

    Criterio de adopción (Sección 5.7):
    1. Si hay estimaciones con confiabilidad ALTA → usa la mediana (no la
       mínima, para evitar outliers).
    2. Si solo hay MEDIA → usa la MÍNIMA entre ellas (conservador).
    3. Si solo hay BAJA → usa la MÍNIMA × factor_seguridad (más conservador
       todavía; sugerido factor 1.25–1.5).
    4. Si no hay estimaciones aplicables → adopta 0 y diagnostica «sin
       información para conclusión».
    """
    validas = [e for e in estimaciones
                  if e.q_min_m3s is not None and e.q_min_m3s > 0
                  and e.confiabilidad != "no_aplicable"]
    if not validas:
        return BalanceAguaPotable(
            estimaciones=estimaciones,
            q_min_adoptado_m3s=0.0,
            metodo_adoptado="ninguno aplicable",
            factor_seguridad=factor_seguridad,
            q_ecologico_m3s=q_ecologico_m3s,
            q_ecologico_metodo=q_ecologico_metodo,
            q_disponible_m3s=0.0,
            q_demanda_max_d_m3s=q_demanda_max_d_m3s,
            saldo_m3s=-q_demanda_max_d_m3s,
            estado="negativo",
            interpretacion=("Sin estimación de oferta aplicable — se "
                              "requiere campaña de aforos antes de emitir "
                              "conclusión sobre la viabilidad."),
            recomendaciones=[
                "Levantar al menos 3 aforos de estiaje (jul–ago) en el "
                "punto de captación con metodología ISO 748.",
                "Verificar la disponibilidad real de cuenca donante "
                "para transposición hidrológica.",
            ],
        )

    altas = [e for e in validas if e.confiabilidad == "alta"]
    medias = [e for e in validas if e.confiabilidad == "media"]

    if altas:
        vals = sorted(e.q_min_m3s for e in altas)
        n = len(vals)
        q_adoptado = vals[n // 2] if n % 2 == 1 else 0.5 * (vals[n//2-1] + vals[n//2])
        metodo = ("Mediana de los métodos con confiabilidad ALTA: "
                    + ", ".join(e.metodo for e in altas))
        factor = 1.0
    elif medias:
        e_min = min(medias, key=lambda x: x.q_min_m3s)
        q_adoptado = e_min.q_min_m3s
        metodo = (f"Mínimo entre los métodos con confiabilidad MEDIA: "
                    f"{e_min.metodo}")
        factor = factor_seguridad
        q_adoptado = q_adoptado / factor
    else:
        e_min = min(validas, key=lambda x: x.q_min_m3s)
        q_adoptado = e_min.q_min_m3s / factor_seguridad
        metodo = (f"Mínimo entre los métodos con confiabilidad BAJA "
                    f"({e_min.metodo}), reducido por factor de seguridad "
                    f"{factor_seguridad:.2f}")
        factor = factor_seguridad

    q_disp = max(q_adoptado - q_ecologico_m3s, 0.0)
    saldo = q_disp - q_demanda_max_d_m3s
    estado = _clasificar_estado(saldo, q_demanda_max_d_m3s)
    interp, recos = _interpretar(estado, saldo, q_disp, q_demanda_max_d_m3s)
    return BalanceAguaPotable(
        estimaciones=estimaciones,
        q_min_adoptado_m3s=q_adoptado,
        metodo_adoptado=metodo,
        factor_seguridad=factor,
        q_ecologico_m3s=q_ecologico_m3s,
        q_ecologico_metodo=q_ecologico_metodo,
        q_disponible_m3s=q_disp,
        q_demanda_max_d_m3s=q_demanda_max_d_m3s,
        saldo_m3s=saldo,
        estado=estado,
        interpretacion=interp,
        recomendaciones=recos,
    )


# ─── Helpers para el informe ─────────────────────────────────────────────

def tabla_sintesis_oferta(b: BalanceAguaPotable) -> list[list[str]]:
    """Tabla 10 — Comparación de métodos."""
    filas: list[list[str]] = [
        ["Método", "Q mín (L/s)", "Base de datos",
            "Confiabilidad", "Observación"],
    ]
    for e in b.estimaciones:
        filas.append([
            e.metodo,
            (f"{e.q_min_m3s * 1000:.2f}"
             if e.q_min_m3s is not None else "—"),
            e.base_datos,
            e.confiabilidad.upper(),
            e.observacion or "—",
        ])
    return filas


def tabla_balance(b: BalanceAguaPotable) -> list[list[str]]:
    """Tabla 13 — Balance oferta-demanda."""
    return [
        ["Concepto", "Valor (L/s)", "Valor (m³/s)", "Observación"],
        ["Q mín adoptado (oferta bruta)",
            f"{b.q_min_adoptado_m3s * 1000:.2f}",
            f"{b.q_min_adoptado_m3s:.4f}",
            b.metodo_adoptado],
        ["− Q ecológico",
            f"{b.q_ecologico_m3s * 1000:.2f}",
            f"{b.q_ecologico_m3s:.4f}",
            b.q_ecologico_metodo],
        ["= Q disponible para captación",
            f"{b.q_disponible_m3s * 1000:.2f}",
            f"{b.q_disponible_m3s:.4f}",
            "Oferta − Q ecológico (Ley 1333)"],
        ["− Q demanda (Q máx. diario)",
            f"{b.q_demanda_max_d_m3s * 1000:.2f}",
            f"{b.q_demanda_max_d_m3s:.4f}",
            "Caudal de diseño de captación (NB 689)"],
        ["= Saldo del balance",
            f"{b.saldo_m3s * 1000:+.2f}",
            f"{b.saldo_m3s:+.4f}",
            f"Estado: {b.estado.upper()}"],
    ]
