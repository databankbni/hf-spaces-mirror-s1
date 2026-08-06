"""
utils/charts.py — shared chart builders.

Keep it simple and immediately readable: clean horizontal bars with value labels.
dot_h / lollipop_h / box_h all render the same clear horizontal bar so every
per-basin comparison across the app looks consistent and is understandable at a glance.
(Bars are rounded + animated via the global Plotly template.)
"""
import statistics
import plotly.graph_objects as go

NAVY = "#0D2137"


def _bar_h(names, values, colors, x_title="", unit="", height=300,
           diverging=False, value_fmt=None):
    names = list(names); values = list(values); colors = list(colors)
    if value_fmt is None:
        value_fmt = (lambda v: f"{v:+.1f}{unit}") if diverging else (lambda v: f"{v:.0f}{unit}")
    fig = go.Figure(go.Bar(
        x=values, y=names, orientation="h",
        marker=dict(color=colors, line=dict(width=0)),
        text=[value_fmt(v) for v in values], textposition="outside",
        textfont=dict(size=10, color=NAVY),
        hovertemplate="%{y}: %{x:.2f}" + (unit or "") + "<extra></extra>",
        cliponaxis=False,
    ))
    if diverging:
        fig.add_vline(x=0, line_color="#90a4ae", line_width=1)
    vmax = max(values + [0]); vmin = min(values + [0])
    pad = (abs(vmax - vmin) or 1) * 0.16 + 1
    lo = (vmin - pad) if diverging else 0
    fig.update_layout(
        height=height, margin=dict(l=10, r=48, t=10, b=34),
        paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(title=x_title, showgrid=True, gridcolor="#eef2f6",
                   range=[lo, vmax + pad], zeroline=False),
        yaxis=dict(tickfont=dict(size=11)),
        showlegend=False,
    )
    return fig


# all aliases render the same clean horizontal bar
def dot_h(names, values, colors, x_title="", unit="", height=300,
          diverging=False, value_fmt=None, baseline=0.0):
    return _bar_h(names, values, colors, x_title=x_title, unit=unit,
                  height=height, diverging=diverging, value_fmt=value_fmt)


def lollipop_h(names, values, colors, x_title="", unit="", height=300,
               diverging=False, value_fmt=None, baseline=0.0):
    return _bar_h(names, values, colors, x_title=x_title, unit=unit,
                  height=height, diverging=diverging, value_fmt=value_fmt)


def box_h(cats, values_per_cat, colors, x_title="", unit="", height=320, point_value=None):
    """Distribution inputs collapsed to a clean median bar per category."""
    meds = []
    for vals in values_per_cat:
        clean = [v for v in vals if v == v]
        meds.append(statistics.median(clean) if clean else 0.0)
    return _bar_h(list(cats), meds, list(colors), x_title=x_title, unit=unit, height=height)


def _rgba(hex_color, a=0.30):
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"


# vivid, distinct palette — one bright colour per box/violin
PALETTE = ["#0277BD", "#2E7D32", "#E65100", "#8C1D40", "#6A1B9A",
           "#00838F", "#C62828", "#1565C0", "#AD1457", "#F9A825", "#283593"]


def box_v(cats, series, colors=None, y_title="", unit="", height=340):
    """Vertical box plots — each box a distinct vivid colour.
    Hover shows median / quartiles. Clear and standard for hydrology."""
    fig = go.Figure()
    for i, (cat, vals) in enumerate(zip(cats, series)):
        vals = [v for v in vals if v == v]
        if not vals:
            continue
        c = PALETTE[i % len(PALETTE)]
        fig.add_trace(go.Box(
            y=vals, name=str(cat), marker_color=c, line=dict(color=c, width=2),
            fillcolor=_rgba(c, 0.38), boxmean=True, boxpoints="outliers",
            whiskerwidth=0.6, width=0.6,
            hovertemplate=("<b>%{x}</b><br>median %{median:.1f}" + unit +
                           "<br>Q1 %{q1:.1f} · Q3 %{q3:.1f}<extra></extra>"),
        ))
    fig.update_layout(
        height=height, margin=dict(l=46, r=14, t=10, b=46),
        paper_bgcolor="white", plot_bgcolor="white", showlegend=False,
        yaxis=dict(title=y_title, showgrid=True, gridcolor="#eef2f6", zeroline=False),
        xaxis=dict(tickfont=dict(size=10.5), tickangle=-20),
    )
    return fig


def violin_v(cats, series, colors=None, y_title="", unit="", height=340):
    """Vertical violin plots — each violin a distinct vivid colour."""
    fig = go.Figure()
    for i, (cat, vals) in enumerate(zip(cats, series)):
        vals = [v for v in vals if v == v]
        if len(vals) < 3:
            continue
        c = PALETTE[i % len(PALETTE)]
        fig.add_trace(go.Violin(
            y=vals, name=str(cat), line=dict(color=c, width=1.8),
            fillcolor=_rgba(c, 0.40), opacity=0.92, meanline_visible=True,
            box_visible=True, points=False, spanmode="hard",
            hovertemplate=("<b>%{x}</b><br>median %{median:.1f}" + unit + "<extra></extra>"),
        ))
    fig.update_layout(
        height=height, margin=dict(l=46, r=14, t=10, b=46),
        paper_bgcolor="white", plot_bgcolor="white", showlegend=False,
        yaxis=dict(title=y_title, showgrid=True, gridcolor="#eef2f6", zeroline=False),
        xaxis=dict(tickfont=dict(size=10.5), tickangle=-20),
    )
    return fig
