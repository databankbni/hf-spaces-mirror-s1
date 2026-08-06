"""Insurance Market dashboard (hosted in the Sector Overviews hub).

Built on the regulator's "Insurance Market Statistics" dataset (premium & claims by
class per company, FY2017–2025) stored in ``insurance_market``, joined with the
regulator-sourced insurer financials in ``metrics_panel`` / ``insurance_statements``.

A clickable **year picker** (pills) at the top drives all three tabs:
  • Market Overview   — size & YoY growth, market loss/expense/combined ratios,
                        market net profit / margin / ROE, class structure & mix.
  • Company Comparison — pick insurers (+ a Market benchmark); metrics × companies
                        matrix, combined-ratio decomposition, underwriting-vs-returns.
  • Player Drilldown   — per-insurer product mix, class loss ratios, trends.

All metrics come pre-computed from ``lib.cache`` (mtime-invalidated) and
``lib.insurance_market_analytics``; charts use Plotly with the app's transparent
layout; widget keys go through ``safe_key`` and obey the Sprint-26 rule. Insurance
classes use one stable colour each (``lib.insurance_market.class_color``) so a class
looks the same in every chart.
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from lib import cache
from lib.format import fmt_pct
from lib.insurance_market import IDCODE_TO_SHORT, class_color, class_color_for_label
from lib.ui import safe_key
from views.shared import ViewContext

# Brand-ish palette consistent with the rest of the app.
_BLUE = "#4a7ab8"
_GREEN = "#2ca02c"
_ORANGE = "#ff7f0e"
_PC = "#1a4f86"      # P&C bubble / loss-ratio colour
_MED = "#0f6e57"     # Medical bubble colour
_EXP = "#DBB968"     # expense-ratio colour
_MARKET_LABEL = "Market (avg)"
# Distinct line colours for the multi-year trend chart (one per company).
_TREND_PALETTE = (
    "#1a4f86", "#0f6e57", "#c0562f", "#6a4c93", "#4a7ab8", "#2ca02c",
    "#ff7f0e", "#8c564b", "#17becf", "#b5a642", "#5b8c5a", "#a83279",
)


def _short(idc: str, fallback: str) -> str:
    return IDCODE_TO_SHORT.get(idc, fallback)


def _layout(fig, height: int = 380):
    fig.update_layout(
        height=height,
        margin=dict(l=40, r=30, t=30, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                     font=dict(size=12)),
        hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, system-ui", size=13),
        bargap=0.5,
    )
    fig.update_xaxes(gridcolor="rgba(128,128,128,0.12)", zeroline=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.12)", zeroline=False)
    # Rounded bar corners, matching the Single-Company IS chart's redesign
    # (kept out of lib.theme.polish_bar_line_chart's line/marker resize since
    # this page's lines are intentionally bolder — 3.5px vs. the 3.2px base).
    fig.update_traces(marker=dict(cornerradius=6), selector=dict(type="bar"))
    return fig


def _dual_axis_grid(fig, bar_max: float | None = None):
    """Tidy the bar+line dual-axis look: the bars carry data labels, so drop the
    left (bar) gridlines entirely and keep only the right (line) axis gridlines —
    this removes the two-scales-of-overlapping-gridlines mess. Adds headroom on the
    bar axis so the outside data labels aren't clipped."""
    fig.update_yaxes(showgrid=False, secondary_y=False)
    if bar_max:
        fig.update_yaxes(range=[0, bar_max * 1.18], secondary_y=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(128,128,128,0.22)", secondary_y=True)
    return fig


def _bar_labels(vals, fmt: str = "{:,.0f}") -> list[str]:
    return [fmt.format(v) if pd.notna(v) else "" for v in vals]


# ---------------------------------------------------------------------------
# Tab 1 — Market Overview
# ---------------------------------------------------------------------------
def _render_overview(db: str, year: int) -> None:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    totals = cache.ins_market_totals(db)
    if totals.empty or year not in totals.index:
        st.info("No market totals for this year.")
        return
    row = totals.loc[year]
    n_ins = len(cache.ins_company_table(db, year))
    hhi = cache.ins_market_hhi(db, year)
    mp = cache.ins_market_uw_profit(db)
    prow = mp.loc[year] if (not mp.empty and year in mp.index) else None

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total GWP", f"₾{row['gwp'] / 1e6:,.0f}M", help=_RATIO_DEFS["GWP (₾M)"])
    growth = row.get("gwp_growth")
    c2.metric("GWP growth (YoY)", fmt_pct(growth) if pd.notna(growth) else "—",
              help=_RATIO_DEFS["GWP growth %"])
    c3.metric("Net loss ratio", fmt_pct(row.get("net_loss_ratio")),
              help="Net incurred claims ÷ net premium across the market "
                   "(collected-premium basis).")
    c4.metric("Active insurers", f"{n_ins}",
              help="Number of insurers reporting premium this year.")
    c5.metric("Concentration (HHI)", f"{hhi:,.0f}" if hhi else "—",
              help="Herfindahl–Hirschman index of GWP shares (Σ shareᵢ², % points). "
                   "<1500 unconcentrated · 1500–2500 moderate · >2500 concentrated.")

    # --- Market size + YoY growth ---
    st.markdown("##### Market size & YoY growth")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    gwp_m = totals["gwp"] / 1e6
    fig.add_trace(go.Bar(
        x=totals.index, y=gwp_m, name="GWP (₾M)", marker_color=_BLUE,
        text=_bar_labels(gwp_m), textposition="outside", cliponaxis=False,
        textfont=dict(size=11, color="#37404a"),
        hovertemplate="FY%{x}<br>GWP: ₾%{y:,.0f}M<extra></extra>"), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=totals.index, y=totals["gwp_growth"] * 100, name="YoY growth (%)",
        mode="lines+markers", line=dict(color=_GREEN, width=3.5), marker=dict(size=8),
        hovertemplate="FY%{x}<br>Growth: %{y:.1f}%<extra></extra>"), secondary_y=True)
    fig.update_yaxes(title_text="GWP (₾M)", secondary_y=False)
    fig.update_yaxes(title_text="YoY growth (%)", secondary_y=True)
    fig.update_xaxes(tickmode="array", tickvals=list(totals.index))
    _dual_axis_grid(_layout(fig), bar_max=float(gwp_m.max()))
    st.plotly_chart(fig, use_container_width=True, key="ins_ov_trend")

    # --- Market loss / expense / combined ratio over time ---
    if prow is not None and not mp.empty:
        st.markdown("##### Underwriting ratios — loss, expense & combined")
        st.caption("Loss + expense bars stack to the combined ratio (line); the dashed "
                   "line is the 100% underwriting break-even. % of net earned premium.")
        figr = go.Figure()
        figr.add_trace(go.Bar(
            x=mp.index, y=mp["loss"] * 100, name="Loss ratio", marker_color=_PC,
            hovertemplate="FY%{x}<br>Loss: %{y:.1f}%<extra></extra>"))
        figr.add_trace(go.Bar(
            x=mp.index, y=mp["expense"] * 100, name="Expense ratio", marker_color=_EXP,
            hovertemplate="FY%{x}<br>Expense: %{y:.1f}%<extra></extra>"))
        figr.add_trace(go.Scatter(
            x=mp.index, y=mp["combined"] * 100, name="Combined ratio",
            mode="lines+markers+text", line=dict(color=_ORANGE, width=3.5),
            marker=dict(size=8),
            text=[f"{v*100:.0f}%" for v in mp["combined"]], textposition="top center",
            textfont=dict(size=11),
            hovertemplate="FY%{x}<br>Combined: %{y:.1f}%<extra></extra>"))
        figr.update_layout(barmode="stack")
        figr.add_hline(y=100, line_dash="dash", line_color="#cb4335")
        figr.update_yaxes(title_text="% of net earned premium")
        figr.update_xaxes(tickmode="array", tickvals=list(mp.index))
        st.plotly_chart(_layout(figr), use_container_width=True, key="ins_ov_ratios")

        # --- Market net profit / margin / ROE ---
        st.markdown("##### Market profitability")
        p1, p2, p3 = st.columns(3)
        np_ = prow.get("net_profit")
        p1.metric("Market net profit", f"₾{np_ / 1e6:,.0f}M" if pd.notna(np_) else "—",
                  help=_RATIO_DEFS["Net profit (₾M)"])
        p2.metric("Net profit margin", fmt_pct(prow.get("np_margin")),
                  help="Market net profit ÷ net earned premium.")
        p3.metric("Market ROE", fmt_pct(prow.get("roe")),
                  help="Σ net profit ÷ Σ equity across all insurers.")
        figp = make_subplots(specs=[[{"secondary_y": True}]])
        np_m = mp["net_profit"] / 1e6
        figp.add_trace(go.Bar(
            x=mp.index, y=np_m, name="Net profit (₾M)", marker_color=_GREEN,
            text=_bar_labels(np_m), textposition="outside", cliponaxis=False,
            textfont=dict(size=11, color="#37404a"),
            hovertemplate="FY%{x}<br>Net profit: ₾%{y:,.0f}M<extra></extra>"), secondary_y=False)
        figp.add_trace(go.Scatter(
            x=mp.index, y=mp["np_margin"] * 100, name="NP margin (%)",
            mode="lines+markers", line=dict(color=_BLUE, width=3.5), marker=dict(size=8),
            hovertemplate="FY%{x}<br>Margin: %{y:.1f}%<extra></extra>"), secondary_y=True)
        figp.add_trace(go.Scatter(
            x=mp.index, y=mp["roe"] * 100, name="ROE (%)",
            mode="lines+markers", line=dict(color=_ORANGE, width=3.5, dash="dot"),
            marker=dict(size=8),
            hovertemplate="FY%{x}<br>ROE: %{y:.1f}%<extra></extra>"), secondary_y=True)
        figp.update_yaxes(title_text="Net profit (₾M)", secondary_y=False)
        figp.update_yaxes(title_text="Margin / ROE (%)", secondary_y=True)
        figp.update_xaxes(tickmode="array", tickvals=list(mp.index))
        _dual_axis_grid(_layout(figp), bar_max=float(np_m.max()))
        st.plotly_chart(figp, use_container_width=True, key="ins_ov_profit")

    col_a, col_b = st.columns(2)

    # --- Class structure (selected year) ---
    with col_a:
        st.markdown(f"##### GWP by class — FY{year}")
        cs = cache.ins_class_structure(db, year)
        if not cs.empty:
            cs = cs.head(10).iloc[::-1]  # largest at top
            figc = go.Figure(go.Bar(
                x=cs["gwp"] / 1e6, y=cs["label"], orientation="h",
                marker_color=[class_color(c) for c in cs["class"]],
                text=[f"{s*100:.1f}%" for s in cs["share"]], textposition="outside",
                hovertemplate="%{y}<br>GWP: ₾%{x:,.1f}M<extra></extra>"))
            figc.update_xaxes(title_text="GWP (₾M)")
            st.plotly_chart(_layout(figc, height=360), use_container_width=True, key="ins_ov_class")

    # --- Class dynamics over time (stacked area, top classes) ---
    with col_b:
        st.markdown("##### Class mix over time")
        dyn = cache.ins_class_dynamics(db)
        if not dyn.empty:
            latest = dyn.loc[dyn.index.max()].sort_values(ascending=False)
            top = list(latest.head(6).index)
            figd = go.Figure()
            for cls in top:
                figd.add_trace(go.Scatter(
                    x=dyn.index, y=dyn[cls] / 1e6, name=cls, mode="lines",
                    stackgroup="one", line=dict(width=0.5, color=class_color_for_label(cls)),
                    hovertemplate="FY%{x} " + cls + ": ₾%{y:,.0f}M<extra></extra>"))
            other = (dyn.drop(columns=top).sum(axis=1)) / 1e6
            if other.sum() > 0:
                figd.add_trace(go.Scatter(
                    x=dyn.index, y=other, name="Other", mode="lines",
                    stackgroup="one", line=dict(width=0.5, color="#999999"),
                    hovertemplate="FY%{x} Other: ₾%{y:,.0f}M<extra></extra>"))
            figd.update_yaxes(title_text="GWP (₾M)")
            figd.update_xaxes(tickmode="array", tickvals=list(dyn.index))
            st.plotly_chart(_layout(figd, height=360), use_container_width=True, key="ins_ov_dyn")


# ---------------------------------------------------------------------------
# Tab 2 — Company Comparison
# ---------------------------------------------------------------------------
# (display label, source col in the comparison frame, "num" | "pct")
_METRIC_ROWS: tuple[tuple[str, str, str], ...] = (
    ("GWP (₾M)", "gwp_m", "num"),
    ("Market share %", "share_pct", "pct"),
    ("GWP growth %", "growth_pct", "pct"),
    ("Loss ratio %", "loss_pct", "pct"),
    ("Expense ratio %", "expense_pct", "pct"),
    ("Combined ratio %", "combined_pct", "pct"),
    ("Retention %", "retention_pct", "pct"),
    ("ROE %", "roe_pct", "pct"),
    ("ROA %", "roa_pct", "pct"),
    ("Net profit (₾M)", "np_m", "num"),
)


# One-line definitions surfaced on hover (KPI `help=` tooltips + comparison row labels).
_RATIO_DEFS: dict[str, str] = {
    "GWP (₾M)": "Gross written premium — total premium contracted in the period "
                "(financial / collected basis), before reinsurance.",
    "Market share %": "Insurer GWP ÷ total market GWP.",
    "GWP growth %": "Year-over-year change in gross written premium.",
    "Loss ratio %": "Net incurred claims ÷ net earned premium — the share of premium paid "
                    "out as claims (underwriting basis, so loss + expense = combined).",
    "Expense ratio %": "Operating & acquisition expenses ÷ net earned premium.",
    "Combined ratio %": "Loss ratio + expense ratio. Below 100% = underwriting profit; "
                        "above 100% = underwriting loss (made up by investment income).",
    "Retention %": "Net premium retained ÷ gross written premium — the share of risk the "
                   "insurer keeps for its own account rather than ceding to reinsurers.",
    "ROE %": "Net profit ÷ shareholders' equity.",
    "ROA %": "Net profit ÷ total assets.",
    "Net profit (₾M)": "After-tax profit for the period.",
}


def _comparison_html(
    matrix: pd.DataFrame,
    groups: list[tuple[str, int]] | None = None,
    sub_headers: list[str] | None = None,
) -> str:
    """Render the transposed comparison matrix as an HTML table whose metric row labels
    carry the definition as a native `title=` tooltip (hover), with a dotted-underline cue.

    Single-level header (default): one ``<th>`` per column — the current single-year
    "metrics × companies" layout.

    Grouped header (``groups`` + ``sub_headers`` given — the multi-year layout): a
    two-row header where each company name spans (``colspan``) its year sub-columns and
    the second row carries the FY labels. ``groups`` is ``[(company_label, n_years), …]``
    in column order; ``sub_headers`` is one FY label per matrix column, aligned to
    ``matrix.columns``.
    """
    if groups is not None and sub_headers is not None:
        top = "".join(
            f"<th colspan='{span}' class='grp'>{html.escape(str(lbl))}</th>"
            for lbl, span in groups
        )
        sub = "".join(f"<th class='yr'>{html.escape(str(s))}</th>" for s in sub_headers)
        thead = f"<tr><th rowspan='2'>Metric</th>{top}</tr><tr>{sub}</tr>"
    else:
        head = "".join(f"<th>{html.escape(str(c))}</th>" for c in matrix.columns)
        thead = f"<tr><th>Metric</th>{head}</tr>"
    body = []
    for label in matrix.index:
        d = _RATIO_DEFS.get(label, "")
        attr = f' title="{html.escape(d)}" class="def"' if d else ""
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in matrix.loc[label])
        body.append(f"<tr><th{attr}>{html.escape(str(label))}</th>{cells}</tr>")
    return (
        "<div class='ins-cmp-wrap'><style>"
        ".ins-cmp-wrap{overflow-x:auto}"
        ".ins-cmp{border-collapse:collapse;width:100%;font-size:0.9rem}"
        ".ins-cmp th,.ins-cmp td{border-bottom:1px solid rgba(128,128,128,.25);"
        "padding:6px 10px;text-align:right;white-space:nowrap;color:inherit}"
        ".ins-cmp thead th{border-bottom:2px solid rgba(128,128,128,.45);font-weight:600}"
        ".ins-cmp thead th.grp{text-align:center;border-left:1px solid rgba(128,128,128,.35)}"
        ".ins-cmp thead th.yr{font-weight:500;font-size:0.82rem;opacity:.85}"
        ".ins-cmp thead th:first-child,.ins-cmp tbody th{text-align:left;font-weight:500}"
        ".ins-cmp tbody th.def{text-decoration:underline dotted;text-underline-offset:3px;cursor:help}"
        "</style>"
        f"<table class='ins-cmp'><thead>{thead}</thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _build_comparison_matrix(
    chosen: list[str],
    rows: list[tuple[str, str, str]],
    sel_years: list[int],
    value_lookup,
) -> tuple[pd.DataFrame, list[tuple[str, int]] | None, list[str] | None]:
    """Assemble the comparison matrix (metrics in rows). Pure — no Streamlit/DB.

    ``chosen``      ordered entity labels (companies, optionally the Market benchmark).
    ``rows``        ``[(metric_label, col_key, kind), …]`` — the metric rows to show.
    ``sel_years``   ascending list of years to display.
    ``value_lookup``  ``(entity, year, col_key) -> float | None`` raw numeric accessor.

    One year  → columns are the entities (single-level header); returns
                ``(matrix, None, None)`` — identical to the legacy single-year layout.
    Many years → columns are one per (entity, year), grouped by entity; returns
                ``(matrix, groups, sub_headers)`` with ``groups`` =
                ``[(entity, len(sel_years)), …]`` and ``sub_headers`` the FY labels
                aligned to ``matrix.columns``.
    """
    metric_labels = [lbl for lbl, _, _ in rows]
    if len(sel_years) <= 1:
        y = sel_years[0]
        data = {
            ent: [_fmt_cell(value_lookup(ent, y, col), kind) for _, col, kind in rows]
            for ent in chosen
        }
        return pd.DataFrame(data, index=metric_labels), None, None

    cols: dict[str, list[str]] = {}
    groups: list[tuple[str, int]] = []
    sub_headers: list[str] = []
    for ent in chosen:
        groups.append((ent, len(sel_years)))
        for y in sel_years:
            # Column keys must be unique per (entity, year); the FY label the user
            # actually sees comes from sub_headers, so the key can be verbose.
            cols[f"{ent} · FY{y}"] = [
                _fmt_cell(value_lookup(ent, y, col), kind) for _, col, kind in rows
            ]
            sub_headers.append(f"FY{str(y)[-2:]}")
    return pd.DataFrame(cols, index=metric_labels), groups, sub_headers


def _comparison_frame(db: str, year: int) -> pd.DataFrame:
    ct = cache.ins_company_table(db, year)
    if ct.empty:
        return ct
    out = pd.DataFrame({
        "Insurer": [_short(r.IdCode, r.Company) for r in ct.itertuples()],
        "Type": ct["SubSector"].replace("", "—").values,
        "gwp_m": ct["gwp"] / 1e6,
        "share_pct": ct["market_share"] * 100,
        "growth_pct": ct["gwp_growth"] * 100,
        "loss_pct": ct["loss_ratio"] * 100,        # underwriting (NEP basis); loss+expense=combined
        "expense_pct": ct["expense_ratio"] * 100,
        "combined_pct": ct["combined_ratio"] * 100,
        "retention_pct": ct["retention"] * 100,
        "roe_pct": ct["roe"] * 100,
        "roa_pct": ct["roa"] * 100,
        "np_m": ct["net_profit"] / 1e6,
    })
    return out


def _market_metrics(db: str, year: int) -> dict | None:
    """Market benchmark column (same units as the comparison frame)."""
    mt = cache.ins_market_totals(db)
    mp = cache.ins_market_uw_profit(db)
    if mt.empty or year not in mt.index:
        return None
    t = mt.loc[year]
    p = mp.loc[year] if (not mp.empty and year in mp.index) else None
    gwp, netprem = t.get("gwp"), t.get("net_premium")

    def pc(x):
        return (x * 100) if (x is not None and pd.notna(x)) else None

    return {
        "gwp_m": (gwp / 1e6) if pd.notna(gwp) else None,
        "share_pct": 100.0,
        "growth_pct": pc(t.get("gwp_growth")),
        "loss_pct": pc(p["loss"]) if p is not None else None,
        "expense_pct": pc(p["expense"]) if p is not None else None,
        "combined_pct": pc(p["combined"]) if p is not None else None,
        "retention_pct": (netprem / gwp * 100) if (pd.notna(gwp) and gwp and pd.notna(netprem)) else None,
        "roe_pct": pc(p["roe"]) if p is not None else None,
        "roa_pct": pc(p["roa"]) if p is not None else None,
        "np_m": (p["net_profit"] / 1e6) if (p is not None and pd.notna(p["net_profit"])) else None,
    }


def _fmt_cell(v, kind: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.1f}%" if kind == "pct" else f"{v:,.1f}"


def _render_comparison(db: str, year: int) -> None:
    import plotly.graph_objects as go

    all_years = cache.ins_market_years(db)

    # --- Year(s) · companies · metrics controls ------------------------------
    # The tab gets its OWN year multiselect (independent of the shared top-of-page
    # year pill that drives Overview/Drilldown). Default = the globally-picked year,
    # so on first open the tab looks exactly as before; add years to compare
    # companies across time.
    c_year, c_ent, c_metric = st.columns([1.2, 2, 2])
    with c_year:
        sel_years = st.multiselect(
            "Years to compare", all_years, default=[year],
            format_func=lambda y: f"FY{y}", key="ins_cmp_years",
            help="One year → the full metric grid (metrics × companies). Several "
                 "years → each company's years group together so you can compare "
                 "companies across time; a trend chart appears below.")
    sel_years = sorted(y for y in sel_years if y in all_years) or [year]
    multi = len(sel_years) > 1
    anchor = sel_years[-1]  # latest selected year drives company ordering + options

    # Per-year comparison frames + market benchmark (each a cache hit per year).
    frames = {y: _comparison_frame(db, y) for y in sel_years}
    frames_i = {
        y: (f.set_index("Insurer") if not f.empty else f) for y, f in frames.items()
    }
    mkts = {y: _market_metrics(db, y) for y in sel_years}

    anchor_cf = frames[anchor]
    if anchor_cf.empty:
        st.info("No company data for the selected year(s).")
        return

    # Company options: latest-year GWP order, then any insurer seen only in an
    # earlier selected year appended after (so nobody silently drops out).
    names = list(anchor_cf["Insurer"])
    for y in sel_years:
        for nm in frames[y]["Insurer"]:
            if nm not in names:
                names.append(nm)
    options = names + [_MARKET_LABEL]
    default = names[:8] + [_MARKET_LABEL]
    metric_labels = [lbl for lbl, _, _ in _METRIC_ROWS]

    with c_ent:
        picked = st.multiselect("Companies to compare", options, default=default,
                                key="ins_cmp_entities")
    with c_metric:
        picked_m = st.multiselect("Metrics to show (rows)", metric_labels,
                                  default=metric_labels, key="ins_cmp_metrics")
    chosen = [c for c in options if c in picked] or default
    rows = [(lbl, col, kind) for lbl, col, kind in _METRIC_ROWS
            if lbl in picked_m] or list(_METRIC_ROWS)

    def _lookup(ent: str, y: int, col: str):
        """Raw numeric value for (entity, year, column) — None when missing."""
        if ent == _MARKET_LABEL:
            return (mkts.get(y) or {}).get(col)
        fi = frames_i.get(y)
        if fi is None or getattr(fi, "empty", True) or ent not in fi.index:
            return None
        return fi.loc[ent, col]

    # --- Metrics (rows) × companies (columns [× years]) matrix ---
    matrix, groups, sub_headers = _build_comparison_matrix(
        chosen, rows, sel_years, _lookup)
    if multi:
        st.caption(
            f"FY{sel_years[0]}–FY{sel_years[-1]} · metrics in rows; each company's "
            f"years group together · **{_MARKET_LABEL}** = whole-market benchmark · "
            "hover an underlined metric for its definition.")
    else:
        st.caption(f"FY{sel_years[0]} · metrics in rows, companies in columns · "
                   f"**{_MARKET_LABEL}** = whole-market benchmark · "
                   "hover an underlined metric for its definition.")
    st.markdown(_comparison_html(matrix, groups, sub_headers), unsafe_allow_html=True)

    # --- Excel export (full per-company table for every selected year) -------
    _exp_key = "insmkt_" + "_".join(str(y) for y in sel_years)
    _rename = {
        "gwp_m": "GWP (M GEL)", "share_pct": "Share %", "growth_pct": "GWP Growth %",
        "loss_pct": "Loss Ratio %", "expense_pct": "Expense Ratio %",
        "combined_pct": "Combined Ratio %", "retention_pct": "Retention %",
        "roe_pct": "ROE %", "roa_pct": "ROA %", "np_m": "Net Profit (M GEL)"}
    _yr_lbl = f"FY{sel_years[0]}–FY{sel_years[-1]}" if multi else f"FY{sel_years[0]}"
    cexp1, cexp2 = st.columns([1, 1])
    with cexp1:
        if st.button("📊 Prepare Excel", key="ins_cmp_xlsx_prep"):
            parts = []
            for y in sel_years:
                fp = frames[y].copy()
                if fp.empty:
                    continue
                fp.insert(0, "Year", y)
                parts.append(fp)
            full = (pd.concat(parts, ignore_index=True) if parts
                    else anchor_cf.copy()).rename(columns=_rename)
            from lib.excel_export import raw_table_to_xlsx
            st.session_state["_ins_xlsx"] = raw_table_to_xlsx(
                full, title=f"Insurance Market — {_yr_lbl}",
                subtitle="Source: insurance.gov.ge Insurance Market Statistics",
                sheet_name="Insurance")
            st.session_state["_ins_xlsx_for"] = _exp_key
    with cexp2:
        if (st.session_state.get("_ins_xlsx_for") == _exp_key
                and st.session_state.get("_ins_xlsx")):
            st.download_button(
                "⬇️ Download Excel", data=st.session_state["_ins_xlsx"],
                file_name=f"insurance_market_{_exp_key.replace('insmkt_', '')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="ins_cmp_xlsx_dl")

    companies_only = [c for c in chosen if c != _MARKET_LABEL]

    # --- Multi-year: metric trend across years (one line per company) --------
    if multi:
        _render_trend_chart(chosen, companies_only, rows, sel_years, _lookup)
        return

    # --- Single year: the two snapshot charts (unchanged) --------------------
    # Charts below compare the picked companies only (Market benchmark excluded).
    cf = anchor_cf
    sel = cf[cf["Insurer"].isin(companies_only)]
    if sel.empty:
        return

    # --- Combined-ratio decomposition: loss + expense stacked = combined ---
    st.markdown("##### Combined ratio = loss ratio + expense ratio")
    st.caption("Stacked to the combined ratio; the dashed line is the 100% underwriting "
               "break-even — bars past it ran an underwriting loss. (% of net earned premium.)")
    dec = sel.dropna(subset=["combined_pct"]).sort_values("combined_pct")
    if not dec.empty:
        figd = go.Figure()
        figd.add_trace(go.Bar(
            y=dec["Insurer"], x=dec["loss_pct"], name="Loss ratio", orientation="h",
            marker_color=_PC, hovertemplate="%{y}<br>Loss ratio: %{x:.1f}%<extra></extra>"))
        figd.add_trace(go.Bar(
            y=dec["Insurer"], x=dec["expense_pct"], name="Expense ratio", orientation="h",
            marker_color=_EXP, hovertemplate="%{y}<br>Expense ratio: %{x:.1f}%<extra></extra>"))
        figd.add_trace(go.Scatter(
            y=dec["Insurer"], x=dec["combined_pct"], mode="text",
            text=[f"{v:.0f}%" for v in dec["combined_pct"]], textposition="middle right",
            textfont=dict(size=10), showlegend=False, hoverinfo="skip", cliponaxis=False))
        figd.update_layout(barmode="stack")
        figd.add_vline(x=100, line_dash="dash", line_color="#cb4335")
        figd.update_xaxes(title_text="Ratio (% of net earned premium)")
        figd.update_yaxes(autorange="reversed")  # lowest (best) combined ratio at top
        st.plotly_chart(_layout(figd, height=max(360, 26 * len(dec) + 120)),
                        use_container_width=True, key="ins_cmp_combined")

    # --- Bubble: loss ratio vs ROE, sized by GWP, coloured by Type ---
    st.markdown("##### Underwriting vs returns")
    st.caption("x = loss ratio · y = ROE · bubble size = GWP · colour = P&C / Medical")
    fig = go.Figure()
    for typ, color in (("P&C", _PC), ("Medical", _MED)):
        sub = sel[sel["Type"] == typ]
        if sub.empty:
            continue
        sizes = (sub["gwp_m"].clip(lower=1) ** 0.5)
        fig.add_trace(go.Scatter(
            x=sub["loss_pct"], y=sub["roe_pct"], mode="markers+text", name=typ,
            text=sub["Insurer"], textposition="top center", textfont=dict(size=9),
            marker=dict(size=sizes, sizemode="area", sizeref=sizes.max() / 900 if len(sizes) else 1,
                        color=color, opacity=0.65, line=dict(width=1, color="#fff")),
            hovertemplate="%{text}<br>Loss ratio: %{x:.1f}%<br>ROE: %{y:.1f}%<extra></extra>"))
    fig.update_xaxes(title_text="Net loss ratio (%)")
    fig.update_yaxes(title_text="ROE (%)")
    fig.update_layout(hovermode="closest")
    st.plotly_chart(_layout(fig, height=440), use_container_width=True, key="ins_cmp_bubble")


def _render_trend_chart(
    chosen: list[str],
    companies_only: list[str],
    rows: list[tuple[str, str, str]],
    sel_years: list[int],
    lookup,
) -> None:
    """Multi-year payoff: pick one metric, plot it across the selected years with one
    line per company (Market benchmark drawn dashed grey when it's in the selection)."""
    import plotly.graph_objects as go

    st.markdown("##### Metric trend across years")
    row_labels = [lbl for lbl, _, _ in rows]
    # Default to Combined ratio when it's on show; else the first metric row.
    default_idx = row_labels.index("Combined ratio %") if "Combined ratio %" in row_labels else 0
    # Guard: if the metrics picker dropped the previously-trended metric, clear the
    # stale selectbox value BEFORE the widget instantiates (Sprint-26 safe).
    if st.session_state.get("ins_cmp_trend_metric") not in row_labels:
        st.session_state.pop("ins_cmp_trend_metric", None)
    label = st.selectbox("Metric to trend", row_labels, index=default_idx,
                         key="ins_cmp_trend_metric")
    col, kind = next((c, k) for l, c, k in rows if l == label)
    st.caption(
        f"{label} · one line per company across FY{sel_years[0]}–FY{sel_years[-1]}"
        + (f" · dashed = {_MARKET_LABEL}" if _MARKET_LABEL in chosen else ""))

    def _series(ent: str):
        vals = [lookup(ent, y, col) for y in sel_years]
        vals = [None if (v is None or pd.isna(v)) else float(v) for v in vals]
        return vals if any(v is not None for v in vals) else None

    fig = go.Figure()
    plotted = 0
    for i, ent in enumerate(companies_only):
        ys = _series(ent)
        if ys is None:
            continue
        fig.add_trace(go.Scatter(
            x=sel_years, y=ys, name=ent, mode="lines+markers", connectgaps=True,
            line=dict(width=2.5, color=_TREND_PALETTE[i % len(_TREND_PALETTE)]),
            marker=dict(size=7),
            hovertemplate="FY%{x}<br>" + label + ": %{y:,.1f}<extra>" + ent + "</extra>"))
        plotted += 1
    if _MARKET_LABEL in chosen:
        ys = _series(_MARKET_LABEL)
        if ys is not None:
            fig.add_trace(go.Scatter(
                x=sel_years, y=ys, name=_MARKET_LABEL, mode="lines+markers",
                connectgaps=True, line=dict(width=2.5, dash="dash", color="#888"),
                marker=dict(size=7),
                hovertemplate="FY%{x}<br>" + label + ": %{y:,.1f}<extra>"
                              + _MARKET_LABEL + "</extra>"))
            plotted += 1
    if plotted == 0:
        st.info("No data for the selected companies over these years.")
        return
    fig.update_xaxes(title_text="Year", tickmode="array", tickvals=sel_years)
    fig.update_yaxes(title_text=label)  # label already carries its unit (% or ₾M)
    fig.update_layout(hovermode="x unified")
    st.plotly_chart(_layout(fig, height=440), use_container_width=True, key="ins_cmp_trend")


# ---------------------------------------------------------------------------
# Tab 3 — Player Drilldown
# ---------------------------------------------------------------------------
def _render_drilldown(db: str, year: int) -> None:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    ct = cache.ins_company_table(db, year)
    if ct.empty:
        st.info("No company data for this year.")
        return
    ids = list(ct["IdCode"])
    labels = {idc: _short(idc, nm) for idc, nm in zip(ct["IdCode"], ct["Company"])}
    pick = st.selectbox("Insurer", ids, format_func=lambda i: labels.get(i, i),
                        key="ins_drill_company")

    rowq = ct[ct["IdCode"] == pick]
    if rowq.empty:
        return
    r = rowq.iloc[0]
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("GWP", f"₾{r['gwp'] / 1e6:,.1f}M", help=_RATIO_DEFS["GWP (₾M)"])
    k2.metric("Market share", fmt_pct(r["market_share"]), help=_RATIO_DEFS["Market share %"])
    k3.metric("Net loss ratio", fmt_pct(r["net_loss_ratio"]), help=_RATIO_DEFS["Loss ratio %"])
    k4.metric("Combined ratio", fmt_pct(r["combined_ratio"]), help=_RATIO_DEFS["Combined ratio %"])
    k5.metric("ROE", fmt_pct(r["roe"]), help=_RATIO_DEFS["ROE %"])

    mix = cache.ins_company_class_mix(db, pick)
    ts = cache.ins_company_timeseries(db, pick)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"##### Premium mix by class — FY{year}")
        m = mix[mix["FVYear"] == year].sort_values("gwp", ascending=False) if not mix.empty else mix
        if m is not None and not m.empty:
            tot = float(m["gwp"].sum()) or 1.0
            # Hide labels on tiny slices so they don't collide; colour by class.
            slice_text = [f"{v / tot * 100:.1f}%" if v / tot >= 0.03 else "" for v in m["gwp"]]
            figp = go.Figure(go.Pie(
                labels=m["label"], values=m["gwp"], hole=0.5, sort=False,
                direction="clockwise",
                marker=dict(colors=[class_color(c) for c in m["class"]],
                            line=dict(color="#fff", width=1)),
                text=slice_text, textinfo="text", textposition="inside",
                insidetextorientation="horizontal",
                hovertemplate="%{label}<br>₾%{value:,.0f}<br>%{percent}<extra></extra>"))
            figp.update_layout(legend=dict(orientation="v", x=1.0, y=0.5,
                                           xanchor="left", yanchor="middle", font=dict(size=10)))
            st.plotly_chart(_layout(figp, height=360), use_container_width=True,
                            key=safe_key("ins_drill_mix", pick))
        else:
            st.info("No class breakdown for this year.")

    with col_b:
        st.markdown("##### GWP & loss ratio trend")
        if ts is not None and not ts.empty:
            figt = make_subplots(specs=[[{"secondary_y": True}]])
            gwp_m = ts["gwp"] / 1e6
            figt.add_trace(go.Bar(
                x=ts.index, y=gwp_m, name="GWP (₾M)", marker_color=_BLUE,
                text=_bar_labels(gwp_m, "{:,.1f}"), textposition="outside", cliponaxis=False,
                textfont=dict(size=10, color="#37404a")),
                secondary_y=False)
            figt.add_trace(go.Scatter(
                x=ts.index, y=ts["net_loss_ratio"] * 100, name="Loss ratio (%)",
                mode="lines+markers", line=dict(color=_ORANGE, width=3.5),
                marker=dict(size=8)), secondary_y=True)
            figt.update_yaxes(title_text="GWP (₾M)", secondary_y=False)
            figt.update_yaxes(title_text="Loss ratio (%)", secondary_y=True, range=[0, 120])
            figt.update_xaxes(tickmode="array", tickvals=list(ts.index))
            _layout(figt, height=360)
            _dual_axis_grid(figt, bar_max=float(gwp_m.max()))
            figt.update_yaxes(title_text="Loss ratio (%)", secondary_y=True, range=[0, 120])
            st.plotly_chart(figt, use_container_width=True,
                            key=safe_key("ins_drill_trend", pick))

    # --- Class-level loss ratios (material classes), coloured to match the mix ---
    if not mix.empty:
        m = mix[(mix["FVYear"] == year) & (mix["gwp"] > 0)].copy()
        m = m[m["net_loss_ratio"].notna()].sort_values("gwp", ascending=False).head(10)
        if not m.empty:
            st.markdown(f"##### Net loss ratio by class — FY{year}")
            m = m.iloc[::-1]
            figl = go.Figure(go.Bar(
                x=m["net_loss_ratio"] * 100, y=m["label"], orientation="h",
                marker_color=[class_color(c) for c in m["class"]],
                text=[f"{v*100:.0f}%" for v in m["net_loss_ratio"]], textposition="outside",
                hovertemplate="%{y}<br>Loss ratio: %{x:.0f}%<extra></extra>"))
            figl.add_vline(x=100, line_dash="dash", line_color="#cb4335")
            figl.update_xaxes(title_text="Net loss ratio (%)")
            st.plotly_chart(_layout(figl, height=340), use_container_width=True,
                            key=safe_key("ins_drill_classloss", pick))


# ---------------------------------------------------------------------------
def render(ctx: ViewContext) -> None:
    db = ctx.db_path
    st.title("🛡️ Insurance Market")
    if not cache.ins_has_market_data(db):
        st.info("Insurance market data is not available in this database. "
                "Run `scripts/download_insurance_market.py` + `build_insurance_market.py`.")
        return
    years = cache.ins_market_years(db)
    if not years:
        st.info("No insurance market data found.")
        return

    # Clickable year picker (drives all three tabs). Seed default BEFORE the widget
    # instantiates (Sprint-26 safe); guard against a stale stored year.
    if st.session_state.get("ins_year") not in years:
        st.session_state["ins_year"] = years[-1]
    sel = st.pills("Year", years, format_func=lambda y: str(y), key="ins_year")
    year = sel if sel in years else years[-1]

    st.caption(
        f"Source: insurance.gov.ge — *Insurance Market Statistics* (premium & claims by "
        f"class), FY{years[0]}–FY{years[-1]}. **Premium = financial (collected) written premium**; "
        f"net loss ratio = net incurred claims ÷ net financial premium. Loss/expense/combined "
        f"& profitability (margin/ROE) come from the regulator's financial returns (net-earned-"
        f"premium basis). Share is vs the regulator's printed market total.")

    tab_ov, tab_cmp, tab_drill = st.tabs(
        ["Market Overview", "Company Comparison", "Player Drilldown"])
    with tab_ov:
        _render_overview(db, year)
    with tab_cmp:
        _render_comparison(db, year)
    with tab_drill:
        _render_drilldown(db, year)
