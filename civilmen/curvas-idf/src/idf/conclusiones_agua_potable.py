"""Conclusiones y recomendaciones dinámicas para el informe de agua potable.

Implementa la Sección 9 del informe (skill normativo boliviano). Las
conclusiones se construyen a partir de los resultados reales del análisis:
piso ecológico clasificado, balance oferta-demanda, verificación normativa
y caudales adoptados. Las recomendaciones se filtran por el diagnóstico
global (viable / condicionado / no viable) y por el piso.
"""

from __future__ import annotations

from .balance_oferta_demanda import BalanceAguaPotable
from .demanda_agua_potable import CaudalesDemanda
from .pisos_ecologicos import PisoEcologico
from .verificacion_normativa import VerificacionGlobal


def conclusiones_dinamicas(*, piso: PisoEcologico,
                             balance: BalanceAguaPotable,
                             caudales: CaudalesDemanda,
                             verificacion: VerificacionGlobal,
                             lat: float, lon: float,
                             area_km2: float | None) -> list[str]:
    """Genera la lista numerada de conclusiones (mínimo 7 obligatorias)."""
    out: list[str] = []

    # 1. Localización y piso ecológico
    area_txt = (f"con área de aporte {area_km2:.2f} km²"
                  if area_km2 is not None else "(área de cuenca pendiente)")
    out.append(
        f"La fuente analizada se ubica en lat {lat:.4f}°, lon {lon:.4f}°, "
        f"{area_txt}, en el piso ecológico <b>{piso.nombre}</b> "
        f"({piso.rango_altitud_m[0]:,}–{piso.rango_altitud_m[1]:,} m s.n.m.). "
        f"Este piso condiciona el régimen de estiaje ({piso.estiaje_esperado.lower()})"
        f" y las recomendaciones de dotación."
        .replace(",", " "))

    # 2. Disponibilidad hídrica
    out.append(
        f"La disponibilidad hídrica bruta estimada por enfoque multimétodo "
        f"es de <b>{balance.q_min_adoptado_m3s * 1000:.2f} L/s</b>. Los "
        f"métodos aplicados se reportan en la Tabla 10 (Sección 5.6).")

    # 3. Método de estimación adoptado
    out.append(
        f"El método de estimación adoptado para el Q mínimo de diseño fue "
        f"<i>{balance.metodo_adoptado}</i>, con factor de seguridad "
        f"{balance.factor_seguridad:.2f}. La justificación se desarrolla "
        f"en la Sección 5.7.")

    # 4. Caudal mínimo de diseño y oferta neta
    out.append(
        f"Descontando el caudal ecológico ({balance.q_ecologico_m3s * 1000:.2f} L/s, "
        f"método: {balance.q_ecologico_metodo}), la <b>oferta neta para "
        f"captación es {balance.q_disponible_m3s * 1000:.2f} L/s</b>.")

    # 5. Suficiencia frente a demanda
    p_diseno = caudales.proyeccion.poblacion_diseno
    out.append(
        f"La demanda máxima diaria del proyecto para {p_diseno:,} hab "
        f"(horizonte {caudales.proyeccion.horizonte_anios} años, dotación "
        f"{caudales.dotacion.dotacion_l_hab_dia:.0f} L/hab/día) es "
        f"<b>{caudales.q_max_d_l_s:.2f} L/s</b>. Saldo del balance: "
        f"<b>{balance.saldo_m3s * 1000:+.2f} L/s</b>. "
        f"Estado: <b>{balance.estado.upper()}</b>."
        .replace(",", " "))

    # 6. Cumplimiento normativo
    out.append(
        f"De los {len(verificacion.requisitos)} requisitos normativos "
        f"verificados (NB 512, NB 689, Ley 1333/RMCH, OMM 168, AAPS), "
        f"{verificacion.n_cumple} se cumplen plenamente, "
        f"{verificacion.n_condicionado} requieren acciones complementarias "
        f"y {verificacion.n_no_cumple} no se cumplen. Condición global: "
        f"<b>{verificacion.condicion_aprobacion.replace('_', ' ').upper()}</b>.")

    # 7. Nivel de incertidumbre
    confiabilidades = {e.confiabilidad for e in balance.estimaciones
                          if e.q_min_m3s is not None}
    if "alta" in confiabilidades:
        incert = "MEDIA (al menos un método con confiabilidad alta)"
    elif "media" in confiabilidades:
        incert = "MEDIA-ALTA (los métodos aplicados son de confiabilidad media)"
    else:
        incert = "ALTA (solo métodos indirectos con datos limitados)"
    out.append(
        f"El nivel de incertidumbre del análisis es <b>{incert}</b>. "
        f"Se requiere actualización del estudio cuando se disponga de "
        f"campaña de aforos en estiaje y/o análisis de calidad NB 512 "
        f"(ver recomendaciones).")

    return out


def recomendaciones_dinamicas(*, balance: BalanceAguaPotable,
                                  verificacion: VerificacionGlobal,
                                  piso: PisoEcologico) -> list[str]:
    """Recomendaciones específicas según diagnóstico + piso ecológico."""
    recos: list[str] = []
    # Las recomendaciones específicas del balance ya vienen calculadas
    recos.extend(balance.recomendaciones)

    # Recomendaciones por requisitos no cumplidos
    for r in verificacion.requisitos:
        if r.cumplimiento == "no_cumple":
            recos.append(f"[{r.referencia}] {r.requisito}: {r.comentario}")
        elif r.cumplimiento == "condicionado":
            recos.append(f"[{r.referencia} — condicionado] {r.comentario}")

    # Recomendaciones generales por piso
    recos_por_piso = {
        "nival":   ("Documentar tendencia de retroceso glaciar y planificar "
                     "fuente alternativa a horizonte 20–30 años."),
        "puna":    ("Incluir protección de bofedales y monitoreo de Q en "
                     "estiaje invernal en el plan operativo."),
        "prepuna": ("Considerar reservorio de regulación interanual y "
                     "verificar captaciones competitivas aguas arriba."),
        "valles":  ("Coordinar con autoridad de aguas para asegurar "
                     "prioridad legal del uso doméstico sobre el riego."),
        "yungas":  ("Diseñar obra de captación con resistencia a flujos "
                     "de detritos y desarenador robusto."),
        "tierras_bajas": ("Evaluar pozo somero / galería filtrante como "
                            "alternativa a la toma superficial; ampliar "
                            "monitoreo de calidad."),
    }
    extra = recos_por_piso.get(piso.clave)
    if extra and extra not in recos:
        recos.append(extra)

    # Recomendaciones operativas estándar (siempre presentes)
    estandar = [
        "Realizar el análisis físico-químico y microbiológico (NB 512) "
        "antes de aprobación operativa, incluso si el balance es positivo.",
        "Instalar limnímetro o sensor de nivel en la sección de "
        "captación para monitoreo continuo desde la puesta en marcha.",
        "Actualizar el estudio en la fase de diseño final con al menos "
        "3 aforos en estiaje (Anexo E).",
    ]
    for s in estandar:
        if s not in recos:
            recos.append(s)
    return recos
