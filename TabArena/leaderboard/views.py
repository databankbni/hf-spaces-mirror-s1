"""Gradio component builders for the leaderboard.

Each function creates one piece of the UI inside the surrounding Blocks/render
context. No data-path logic lives here (see ``data_loading.py``) and no copy
lives here (see ``website_texts.py``).
"""

from __future__ import annotations

import html
import math
import re
from itertools import groupby
from pathlib import Path

import gradio as gr
import pandas as pd

import website_texts
from constants import Constants, model_type_color, model_type_emoji, variant_color
from data_loading import (
    BEYOND_SUBSET_LABELS,
    DATASET_SIZE_NOTE,
    BeyondSubset,
    LBContainer,
    Subset,
    load_leaderboard_csv,
    parse_model,
    subset_name,
    unzip_png,
)

# --------------------------------------------------------------------------- #
# Full per-subset leaderboard table
# --------------------------------------------------------------------------- #

_IMPUTED_INFO = (
    "We impute the performance for models that cannot run on all datasets due to"
    " task or dataset size constraints. We impute with the performance of a"
    " default RandomForest. We add a postfix [X% IMPUTED] to the model if any"
    " results were imputed. The X% shows the percentage of datasets that were"
    " imputed. In general, imputation negatively represents the model"
    " performance, punishing the model for not being able to run on all datasets."
)


# Variants a model is evaluated in; all selected by default, and any combination is
# valid. Reference pipelines (AutoGluon) carry no variant tag of their own but are
# tuned ensembles, so they belong with those.
VARIANT_VALUES = ["default", "tuned", "tuned + ensembled"]

# Columns that drive the filters or are folded into another cell; kept on the frame,
# never rendered as their own column.
_INTERNAL_COLUMNS = ["TypeName", "RefModel", "Imputed", "_variant", "_base", "_search"]
# Shown as "(+115/-110)" after the Elo value instead of as a column of its own.
_CI_COLUMN = "Elo 95% CI"
_ELO_COLUMN = "Elo [⬆️]"
# Rendered as a ✔️ badge on the model name, the way the overview does it.
_VERIFIED_COLUMN = "Verified"
# Always shown, so they are not offered in the column picker.
_ALWAYS_SHOWN = ["#", "Type", "Model"]

# Column header -> the metric-reference entry whose text becomes its hover hint, so
# the tooltips and the documented definitions cannot drift apart.
_LB_TOOLTIP_METRIC = {
    _ELO_COLUMN: "🏆 Elo (ranking aggregation)",
    "Score [⬆️]": "📊 Score",
    "Improvability (%) [⬇️]": "📉 Improvability (%)",
    "Rank [⬇️]": "🔢 Average Rank",
    "Harmonic Rank [⬇️]": "🎯 Harmonic Rank",
    "Median Train Time (s/1K) [⬇️]": "⏱️ Train / Predict Time (s/1K)",
    "Median Predict Time (s/1K) [⬇️]": "⏱️ Train / Predict Time (s/1K)",
    "Imputed (%) [⬇️]": "🧩 Imputed (%)",
}
_LB_FIXED_TOOLTIPS = {
    "#": "Position in this subset's Elo ranking, as published.",
    "Type": "Model family — see the legend above the table.",
    "Model": (
        "The model, its configuration variant in brackets, and ✔️ when the "
        "implementation was verified by its authors or the maintainers. Links to the "
        "implementation."
    ),
    "Hardware": "The hardware the reported runtimes were measured on.",
}
# Which direction is good, per column, for the per-column heatmap. Columns absent
# from this map (#, Hardware) are left unshaded.
_LB_HIGHER_IS_BETTER = {
    _ELO_COLUMN: True,
    "Score [⬆️]": True,
    "Rank [⬇️]": False,
    "Harmonic Rank [⬇️]": False,
    "Improvability (%) [⬇️]": False,
    "Median Train Time (s/1K) [⬇️]": False,
    "Median Predict Time (s/1K) [⬇️]": False,
    "Imputed (%) [⬇️]": False,
}
# Runtimes span orders of magnitude, so shading them linearly paints every model
# the same green and only the slowest one red. Normalize those in log space.
_LB_LOG_SCALED = {
    "Median Train Time (s/1K) [⬇️]",
    "Median Predict Time (s/1K) [⬇️]",
}
# The marker the plot explorers put on an imputed method (see the generated
# *_explorer.html); reused here so the same thing looks the same everywhere.
IMPUTED_MARK = "‡"

# Per-column value formatting; everything else falls back to _format_value.
_LB_FORMATS = {
    _ELO_COLUMN: lambda v: str(int(round(v))),
    "Score [⬆️]": lambda v: f"{v:.3f}",
    "Rank [⬇️]": lambda v: f"{v:.2f}",
    "Harmonic Rank [⬇️]": lambda v: f"{v:.2f}",
    "Improvability (%) [⬇️]": lambda v: f"{v:.2f}",
    "Median Train Time (s/1K) [⬇️]": lambda v: f"{v:.2f}",
    "Median Predict Time (s/1K) [⬇️]": lambda v: f"{v:.3f}",
    "Imputed (%) [⬇️]": lambda v: f"{v:.1f}",
}


def _column_tooltip(column: str) -> str | None:
    """Hover hint for a leaderboard column header, or None when there is nothing to add."""
    if column in _LB_FIXED_TOOLTIPS:
        return _LB_FIXED_TOOLTIPS[column]
    name = _LB_TOOLTIP_METRIC.get(column)
    if not name:
        return None
    for metric in website_texts.METRICS:
        if metric["name"] == name:
            return f"{metric['details']}  ·  Why we use it: {metric['why']}"
    return None


def _format_value(column: str, value) -> str:
    """Display string for one cell; `data-sort` keeps the raw value for sorting."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "–"
    formatter = _LB_FORMATS.get(column)
    if formatter and isinstance(value, (int, float)) and not isinstance(value, bool):
        return formatter(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def filter_leaderboard(
    df: pd.DataFrame,
    *,
    models: list[str],
    variants: list[str],
    show_imputed: bool,
    search: str = "",
) -> pd.DataFrame:
    """Apply the table's row filters.

    Pure so it can be tested without a Gradio context. `df` carries the internal
    ``_base`` / ``_variant`` / ``Imputed`` / ``_search`` columns added by
    :func:`_prepare_leaderboard`. `models` is the selected individual models: family
    chips are bulk selectors over that list, not a filter of their own. Column
    selection is applied when rendering, not here.
    """
    sub = df[df["_base"].isin(models)]
    # Only narrow when the reader has actually deselected something, so a row whose
    # variant we failed to classify can never be dropped silently.
    if variants is not None and set(variants) != set(VARIANT_VALUES):
        sub = sub[sub["_variant"].isin(variants)]
    if not show_imputed:
        sub = sub[~sub["Imputed"].astype(bool)]
    term = (search or "").strip().lower()
    if term:
        sub = sub[sub["_search"].str.contains(re.escape(term), regex=True)]
    return sub


def _prepare_leaderboard(raw: pd.DataFrame) -> pd.DataFrame:
    """Add the internal columns the filters and the renderer need."""
    df = raw.copy()
    parsed = [parse_model(str(m)) for m in raw["Model"]]
    df["_base"] = [base for base, _, _ in parsed]
    df["_variant"] = [
        "tuned + ensembled" if not variant and "AutoGluon" in base else variant
        for base, variant, _ in parsed
    ]
    df["_search"] = [
        f"{base} {variant} {type_name}".lower()
        for (base, variant, _), type_name in zip(parsed, raw["TypeName"], strict=True)
    ]
    return df


def leaderboard_families(df: pd.DataFrame) -> list[tuple[str, list[str]]]:
    """(family, models) pairs present in `df`, in the legend's family order."""
    families = []
    for type_name in model_type_emoji:
        models = sorted(set(df.loc[df["TypeName"] == type_name, "_base"]))
        if models:
            families.append((type_name, models))
    return families


def fam_chip_colors(families: list[tuple[str, list[str]]]) -> str:
    """`--fam` per family, so each chiprow carries its family's colour."""
    rules = [
        f".ta-fam-{re.sub(r'[^a-z0-9]+', '-', type_name.lower())}"
        f"{{--fam:{model_type_color.get(type_name, '#9e9e9e')};}}"
        for type_name, _ in families
    ]
    # The variant toggles take their colours from the Leaderboard Overview explorer.
    # Generated from the same list the choices come from, so the nth-of-type index
    # cannot drift from the option order.
    rules += [
        f".ta-variants label:nth-of-type({i + 1}){{--fam:{variant_color[value]};}}"
        for i, value in enumerate(VARIANT_VALUES)
        if value in variant_color
    ]
    return "".join(rules)


def _group_handler(index: int, models: list[str], render):
    """A model chip group changed: bring its family chip in line, redraw the table."""

    def handler(*values):
        selected = values[index] or []
        return gr.update(value=set(selected) == set(models)), render(*values)

    return handler


def _family_handler(index: int, models: list[str], render):
    """A family chip was toggled: select or clear all of its models, redraw the table."""

    def handler(checked, *values):
        updated = list(values)
        updated[index] = list(models) if checked else []
        return gr.update(value=updated[index]), render(*updated)

    return handler


def _heatmap_bounds(df: pd.DataFrame, columns: list[str]) -> dict[str, tuple[float, float]]:
    """Per-column (lo, hi) over the rendered rows, in the scale used for shading."""
    bounds = {}
    for column in columns:
        if column not in _LB_HIGHER_IS_BETTER or column not in df.columns:
            continue
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if column in _LB_LOG_SCALED:
            values = values[values > 0]
            values = values.apply(math.log10)
        if len(values) < 2 or values.min() == values.max():
            continue
        bounds[column] = (float(values.min()), float(values.max()))
    return bounds


def _heatmap_style(column: str, value: float, bounds: dict[str, tuple[float, float]]) -> str:
    """Inline background for one shaded cell, or "" when the column is not shaded."""
    if column not in bounds:
        return ""
    lo, hi = bounds[column]
    scaled = value
    if column in _LB_LOG_SCALED:
        if value <= 0:
            return ""
        scaled = math.log10(value)
    frac_best = (scaled - lo) / (hi - lo)
    if not _LB_HIGHER_IS_BETTER[column]:
        frac_best = 1 - frac_best
    frac_best = max(0.0, min(1.0, frac_best))
    return f' style="background:{_interp_color(1 - frac_best)};color:#f7f7f7;"'


def _model_cell(row: pd.Series) -> str:
    """The Model cell, styled like the cross-subset overview's."""
    color = model_type_color.get(row["TypeName"], "#9e9e9e")
    _, variant, url = parse_model(str(row["Model"]))
    name = html.escape(row["_base"])
    if variant:
        name += f' <span class="ta-variant">({html.escape(variant)})</span>'
    if str(row.get(_VERIFIED_COLUMN, "")).strip() == "✔️":
        name += ' <span class="ta-verified" title="Verified implementation">✔️</span>'
    if bool(row.get("Imputed", False)):
        name += (
            f' <span class="ta-imp" title="Some results are imputed">{IMPUTED_MARK}</span>'
        )
    if url:
        return (
            f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener" '
            f'style="color:{color};font-weight:600;">{name}'
            f'<span class="ta-link-icon">↗</span></a>'
        )
    return f'<span style="color:{color};font-weight:600;">{name}</span>'


def leaderboard_table_html(df: pd.DataFrame, columns: list[str], table_id: str) -> str:
    """Render the leaderboard as a sortable HTML table in the overview's style.

    Every header is clickable (``taSortTable`` in ``main.py``'s head) and carries the
    column's definition as a hover hint. Numeric cells put the raw value in
    ``data-sort`` and the formatted one in the text, which is what lets the Elo cell
    show its confidence interval without that text taking part in the sort.
    """
    metric_columns = [c for c in columns if c not in _ALWAYS_SHOWN]
    header = [
        '<th class="ta-th-sort ta-th-info" data-type="num" title="'
        + html.escape(_LB_FIXED_TOOLTIPS["#"], quote=True)
        + '">#</th>',
        '<th class="ta-th-sort ta-th-info" title="'
        + html.escape(_LB_FIXED_TOOLTIPS["Type"], quote=True)
        + '">Type</th>',
        '<th class="ta-th-sort ta-th-info ta-th-left" title="'
        + html.escape(_LB_FIXED_TOOLTIPS["Model"], quote=True)
        + '">Model</th>',
    ]
    for column in metric_columns:
        tooltip = _column_tooltip(column)
        label = html.escape(column)
        marker = ""
        if column == _ELO_COLUMN:
            label += ' <span class="ta-ci-head">(95% CI)</span>'
            # Tells taExportTable to split the interval into its own CSV column.
            marker = ' data-col="elo"'
        classes = "ta-th-sort" + (" ta-th-info" if tooltip else "")
        title = f' title="{html.escape(tooltip, quote=True)}"' if tooltip else ""
        header.append(
            f'<th class="{classes}" data-type="num"{marker}{title}>{label}</th>'
        )

    # No medals, unlike the cross-subset overview: this table is the full ranking and
    # already carries the # column, so podium marks only added a competing ordering.
    bounds = _heatmap_bounds(df, metric_columns)

    body = []
    for _, row in df.iterrows():
        color = model_type_color.get(row["TypeName"], "#9e9e9e")
        cells = [
            f'<td class="ta-num" data-sort="{row["#"]}">{row["#"]}</td>',
            f'<td class="ta-type-cell" data-sort="{html.escape(str(row["TypeName"]), quote=True)}">'
            f'<span class="ta-pill" style="background:{color}22;color:{color};'
            f'border:1px solid {color}66;">{row["Type"]}</span></td>',
            # data-export="text": the CSV should carry the displayed name, not the
            # lowercased key this cell sorts on.
            f'<td class="ta-model-cell" data-export="text" '
            f'data-sort="{html.escape(row["_base"].lower(), quote=True)}">'
            f"{_model_cell(row)}</td>",
        ]
        for column in metric_columns:
            value = row.get(column)
            text = _format_value(column, value)
            if text == "–":
                cells.append('<td class="ta-na">–</td>')
                continue
            numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
            shade = _heatmap_style(column, float(value), bounds) if numeric else ""
            if column == _ELO_COLUMN:
                ci = row.get(_CI_COLUMN)
                interval, ci_attr = "", ""
                if ci is not None and not pd.isna(ci):
                    interval = f' <span class="ta-ci">({html.escape(str(ci))})</span>'
                    ci_attr = f' data-ci="{html.escape(str(ci), quote=True)}"'
                cells.append(
                    f'<td class="ta-num" data-sort="{value}"{ci_attr}{shade}>'
                    f"{text}{interval}</td>"
                )
                continue
            sort_key = value if numeric else html.escape(str(value), quote=True)
            cells.append(f'<td class="ta-num" data-sort="{sort_key}"{shade}>{text}</td>')
        body.append(f"<tr>{''.join(cells)}</tr>")

    caption = f"{len(df)} row{'' if len(df) == 1 else 's'}"
    shaded = "green is better, red is worse, per column" if bounds else "unshaded"
    return (
        f'<div class="ta-scroll"><table class="ta-overview ta-lbtable" id="{table_id}">'
        f"<thead><tr>{''.join(header)}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
        f'<p class="ta-cap">{caption} · click a column header to sort, hover one for its '
        f"definition · {shaded} · {IMPUTED_MARK} marks a model with imputed results</p>"
    )


def make_leaderboard(lb: LBContainer) -> None:
    """The full leaderboard table for one subset.

    The table is a generated artifact (`leaderboard_table.html`, built by
    `tabarena.plot.interactive.leaderboard_table`), embedded the same way as the
    other interactive plots. It lives upstream so that it reuses the explorers'
    family and variant colours, chip components and imputation markers rather than
    reimplementing them here, where they drifted.

    Subsets whose artifacts predate it fall back to :func:`make_leaderboard_gradio`,
    this app's own table.
    """
    content = lb.html_content("leaderboard_table")
    if content is None:
        make_leaderboard_gradio(lb)
        return
    with gr.Column(elem_classes="ta-lb"):
        gr.HTML(
            '<div class="ta-lb-bar">'
            '<span class="ta-lb-title">⭐ Full Leaderboard Table</span>'
            '<span class="ta-lb-sub">every column sorts · hover a header for what it '
            "means · filter by family, model or variant</span>"
            # The frame owns the download: only it knows the current filters,
            # columns and sort order (see main.taLeaderboardCsv).
            '<button class="ta-viewbtn ta-exportbtn ta-csvbtn" '
            'onclick="taLeaderboardCsv(this)" '
            'title="Download the rows and columns shown, in the current sort order">'
            "Download CSV</button></div>"
        )
        gr.HTML(
            _interactive_plot_iframe(
                content, f"Full leaderboard table — {lb.name}", height=1100
            )
        )


def make_leaderboard_gradio(lb: LBContainer) -> None:
    """The fallback table, rendered by this app rather than embedded.

    Kept for subsets whose artifacts were generated before `leaderboard_table.html`
    existed. :func:`make_leaderboard` is the current path; prefer fixing the
    upstream generator over this.

    Replaces the third-party `gradio_leaderboard` widget (which pinned Gradio < 6)
    with the same hand-rolled HTML table the cross-subset overview uses: type pills,
    dotted-underline model links, tooltip-carrying headers, sticky header and scroll
    box. Model selection mirrors the plot explorers' edit view — a family chip above
    its models, in the family's colour. Sorting and CSV export are client-side
    (`taSortTable` / `taExportTable`); the filters round-trip to rebuild the HTML.
    """
    raw = lb.load_df()
    has_imputed = bool(raw["Imputed"].any())
    df = _prepare_leaderboard(raw)
    if not has_imputed:
        df = df.drop(columns=["Imputed (%) [⬇️]"])

    # The CI and Verified columns are folded into the Elo and Model cells.
    renderable = [
        c
        for c in df.columns
        if c not in _INTERNAL_COLUMNS + [_CI_COLUMN, _VERIFIED_COLUMN]
    ]
    optional = [c for c in renderable if c not in _ALWAYS_SHOWN]
    families = leaderboard_families(df)
    table_id = f"lb-{lb.subset.rel_path.replace('/', '-')}"

    def render(*values) -> str:
        """Redraw the table from the controls' values, positional as Gradio passes them."""
        count = len(families)
        models = [m for group in values[:count] for m in (group or [])]
        variants, show_imputed, columns, search = values[count : count + 4]
        sub = filter_leaderboard(
            df,
            models=models,
            variants=variants,
            show_imputed=show_imputed or not has_imputed,
            search=search,
        )
        chosen = [c for c in renderable if c in set(columns or []) or c in _ALWAYS_SHOWN]
        return leaderboard_table_html(sub, chosen, table_id)

    with gr.Column(elem_classes="ta-lb"):
        gr.HTML(
            # The table borrows the overview's stylesheet; inject it here rather than
            # relying on the legend, which this card no longer draws (the family chips
            # below say the same thing, in colour).
            _OVERVIEW_CSS
            + f"<style>{fam_chip_colors(families)}</style>"
            + '<div class="ta-lb-bar">'
            '<span class="ta-lb-title">⭐ Full Leaderboard Table</span>'
            '<span class="ta-lb-sub">every column sorts · hover a header for what it '
            "means</span>"
            # Same green as the figure panels' export controls (.ta-exportbtn).
            f'<button class="ta-viewbtn ta-exportbtn ta-csvbtn" '
            f'onclick="taExportTable(\'{table_id}\')" '
            'title="Download the rows and columns currently shown, in the current sort '
            'order">⬇️ CSV</button>'
            "</div>"
        )

        # Model selection, laid out like the Pareto explorer's chiprows: one row per
        # family, the family chip toggling all of its models at once.
        fam_toggles, model_groups = [], []
        for type_name, models in families:
            fam_class = f"ta-fam-{re.sub(r'[^a-z0-9]+', '-', type_name.lower())}"
            with gr.Row(elem_classes="ta-chiprow"):
                fam_toggles.append(
                    gr.Checkbox(
                        value=True,
                        label=f"{model_type_emoji.get(type_name, '')} {type_name} ×{len(models)}",
                        show_label=False,
                        container=False,
                        interactive=True,
                        elem_classes=["ta-famchip", fam_class],
                        scale=0,
                        min_width=210,
                    )
                )
                model_groups.append(
                    gr.CheckboxGroup(
                        choices=models,
                        value=models,
                        show_label=False,
                        container=False,
                        interactive=True,
                        elem_classes=["ta-chips", fam_class],
                        scale=1,
                    )
                )

        with gr.Row(elem_classes="ta-lb-controls"):
            variant = gr.CheckboxGroup(
                choices=VARIANT_VALUES,
                value=VARIANT_VALUES,
                label="⚙️ Variants",
                interactive=True,
                elem_classes=["ta-btns", "ta-variants"],
                scale=3,
                min_width=290,
            )
            show_imputed = gr.Checkbox(
                value=True,
                label=f"{IMPUTED_MARK} Include imputed",
                info=_IMPUTED_INFO,
                interactive=True,
                visible=has_imputed,
                elem_classes=["ta-btns", "ta-btns-imputed"],
                scale=1,
                min_width=190,
            )
            columns = gr.Dropdown(
                choices=optional,
                value=optional,
                multiselect=True,
                label="📋 Columns",
                info="# / Type / Model always shown",
                interactive=True,
                scale=2,
                min_width=220,
            )
            search = gr.Textbox(
                label="🔍 Search",
                placeholder="model or type…",
                interactive=True,
                scale=1,
                min_width=150,
            )

        state = [*model_groups, variant, show_imputed, columns, search]
        table = gr.HTML(render(*[c.value for c in state]))

        # `.input` rather than `.change`: a family chip rewrites its group's value and
        # each group rewrites its family chip, so reacting to programmatic changes too
        # would let the two bounce off each other.
        for index, (models, group, fam) in enumerate(
            zip([m for _, m in families], model_groups, fam_toggles, strict=True)
        ):
            group.input(
                _group_handler(index, models, render),
                state,
                [fam, table],
                api_visibility="private",
            )
            fam.input(
                _family_handler(index, models, render),
                [fam, *state],
                [group, table],
                api_visibility="private",
            )
        for control in (variant, show_imputed, columns, search):
            control.input(render, state, table, api_visibility="private")


# --------------------------------------------------------------------------- #
# Per-subset figures
# --------------------------------------------------------------------------- #


def _interactive_plot_iframe(content: str, title: str, height: int = 720) -> str:
    """Wrap a self-contained interactive plot page in a sandboxed iframe.

    ``srcdoc`` + a ``sandbox`` runs the page's inline JS without granting it
    same-origin access; the page has no external dependencies by construction.
    ``allow-downloads`` is the one extra capability, for the paper view's
    SVG/PNG figure export — without it the sandbox silently drops the download.
    Three integration details:

    - The site forces the dark theme, so stamp ``data-theme="dark"`` on the
      page's root element (the explorer's CSS honors it) — otherwise the frame
      would follow the viewer's OS preference and could render light-on-dark.
    - The explorer posts its content height via ``postMessage``; the listener
      registered in ``main.py``'s ``head`` resizes the iframe to fit, so the
      frame never shows an inner scrollbar. ``height`` is only the initial
      placeholder until the first message arrives.
    - The paper view is toggled from the panel header over the same channel
      (see ``main.taPaperView``), since the frame is cross-origin.
    """
    content = content.replace('<html lang="en">', '<html lang="en" data-theme="dark">', 1)
    return (
        f'<iframe srcdoc="{html.escape(content, quote=True)}" class="ta-explorer" '
        f'style="width:100%;height:{height}px;border:1px solid var(--border-color-primary,#80808033);'
        'border-radius:8px;background:transparent" '
        f'sandbox="allow-scripts allow-downloads" loading="lazy" '
        f'title="{html.escape(title, quote=True)}"></iframe>'
    )


def _panel_uid(lb: LBContainer, key: str) -> str:
    """A DOM-safe id unique to one (subset, figure) panel."""
    return "ta-fig-" + re.sub(r"[^a-z0-9]+", "-", f"{lb.subset.rel_path}-{key}".lower()).strip("-")


def _switchable_figure(
    lb: LBContainer,
    *,
    html_name: str,
    img_name: str,
    label: str,
    height: int = 500,
) -> None:
    """A figure panel: the interactive explorer with a switch to the static PNG.

    Both views are rendered up front and flipped client-side by
    ``main.taSwitchView`` (no server round trip). The static PNG is the
    published, paper-ready figure and stays the fallback in two senses: it is
    one click away here, and it is *all* that renders for a subset whose
    artifacts predate the explorer (or for a benchmark that does not ship one).
    """
    content = lb.html_content(html_name)
    if content is None:
        gr.Image(
            value=lb.image_path(img_name),
            label=label,
            height=height,
            show_label=True,
        )
        return

    uid = _panel_uid(lb, html_name)
    # "Name [subset]" -> the name as the heading, the subset as a quiet qualifier,
    # so the eye finds where each figure block starts.
    name, _, subset = label.partition(" [")
    subset_html = f'<span class="ta-figbar-sub">{html.escape(subset.rstrip("]"))}</span>' if subset else ""
    with gr.Column(elem_classes="ta-figpanel"):
        gr.HTML(
            f'<div class="ta-figbar"><span class="ta-figbar-title">{html.escape(name)}</span>{subset_html}'
            # The panel opens in paper view, so this invites the reader into the
            # controls; `aria-pressed` tracks whether paper view is on.
            f'<button type="button" class="ta-viewbtn ta-editbtn" id="{uid}-paper" aria-pressed="true" '
            f"onclick=\"taPaperView('{uid}')\">✏️ Edit view</button>"
            f'<button type="button" class="ta-viewbtn" id="{uid}-btn" aria-pressed="false" '
            f"onclick=\"taSwitchView('{uid}')\">🖼️ Static figure</button>"
            # Right-aligned, and shown from the start since paper view is the
            # default: downloading the figure is what that view is for.
            f'<span class="ta-exportgroup" id="{uid}-export">'
            f'<span class="ta-exportlabel">Download</span>'
            + "".join(
                f'<button type="button" class="ta-viewbtn ta-exportbtn" '
                f"onclick=\"taExport('{uid}','{fmt}')\">{fmt.upper()}</button>"
                for fmt in ("svg", "pdf", "png")
            )
            + "</span></div>"
        )
        with gr.Column(elem_id=f"{uid}-i", elem_classes="ta-figview"):
            gr.HTML(_interactive_plot_iframe(content, title=label))
        with gr.Column(elem_id=f"{uid}-s", elem_classes=["ta-figview", "ta-hidden"]):
            # No fixed height: the CSS lets the PNG span the panel width and
            # take whatever height its aspect ratio needs, so a wide figure is
            # not letterboxed inside a tall box (and a tall one is not shrunk).
            gr.Image(
                value=lb.image_path(img_name),
                show_label=False,
            )


def make_overview_images(lb: LBContainer) -> None:
    name = subset_name(lb.subset)
    # The panels are stacked full-width (side-by-side columns were too cramped
    # for the chips + chart). Each pairs an interactive explorer with the static
    # figure it replaces, switchable from the panel header.
    _switchable_figure(
        lb,
        html_name="leaderboard_overview_explorer",
        img_name="tuning-impact-elo",
        label=f"Leaderboard Overview [{name}]",
        # The static bar figure is ~7:1; a taller box only letterboxes it.
        height=320,
    )
    _switchable_figure(
        lb,
        html_name="pareto_front_explorer",
        img_name="pareto_front_improvability_vs_time_infer",
        label=f"Pareto Front [{name}]",
    )
    _switchable_figure(
        lb,
        html_name="tuning_trajectories_explorer",
        img_name="pareto_n_configs_imp",
        label=f"Tuning Trajectories [{name}]",
    )


def make_winrate_image(lb: LBContainer, *, interactive: bool = True) -> None:
    """The win-rate matrix for one subset.

    Uses ``lb.name`` (the caller-supplied subset name) so it is benchmark-agnostic and
    reusable across the TabArena and BeyondArena tabs. With `interactive` it gets the
    same interactive / static / paper panel as the other figures, falling back to the
    PNG on its own for subsets whose artifacts predate ``winrate_explorer.html``.
    BeyondArena passes ``interactive=False`` and stays on the static figure.
    """
    if interactive:
        _switchable_figure(
            lb,
            html_name="winrate_explorer",
            img_name="winrate_matrix",
            label=f"Win-rate Matrix [{lb.name}]",
            height=800,
        )
        return
    gr.Image(
        lb.image_path("winrate_matrix"),
        label=f"Win-rate Matrix [{lb.name}]",
        show_label=True,
        height=800,
    )


# --------------------------------------------------------------------------- #
# Cross-subset overview (Elo heatmap, rendered as HTML for links + grouping)
# --------------------------------------------------------------------------- #

# Columns of the overview: (label, group, subset). Always imputation=yes/splits=all.
_OVERVIEW_COLUMNS: list[tuple[str, str, Subset]] = [
    ("Overall", "overall", Subset(tasks="all", datasets="all")),
    ("Class.", "task", Subset(tasks="classification", datasets="all")),
    ("Regr.", "task", Subset(tasks="regression", datasets="all")),
    ("Binary", "task", Subset(tasks="binary", datasets="all")),
    ("Multi.", "task", Subset(tasks="multiclass", datasets="all")),
    ("Small", "size", Subset(tasks="all", datasets="small")),
    ("Medium", "size", Subset(tasks="all", datasets="medium")),
]
_GROUP_TITLE = {"task": "By Task", "size": "By Dataset Size"}
# Hover tooltips for the overview's subset column headers (rendered as a native `title=`).
# Size definitions are reused from DATASET_SIZE_NOTE so they can't drift from the subset blurbs.
_COLUMN_TOOLTIPS: dict[str, str] = {
    "Overall": "All tasks across every dataset size — the headline ranking.",
    "Class.": "Classification tasks only (binary + multiclass).",
    "Regr.": "Regression tasks only.",
    "Binary": "Binary classification tasks only.",
    "Multi.": "Multiclass classification tasks only.",
    "Small": DATASET_SIZE_NOTE["small"],
    "Medium": DATASET_SIZE_NOTE["medium"],
}
# Cross-subset overview only: top-3 per column get a medal in a fixed-width slot reserved in
# every number cell, so the numbers line up whether or not a medal is present (see
# `.ta-medal`/`.ta-val` in `_OVERVIEW_CSS`). The full leaderboard table has no medals — it
# carries a # column, which already says the same thing.
_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# Metrics selectable in the overview: label -> (csv column, higher_is_better, formatter).
# Order = display order in the selector; the two headline metrics come first.
_OVERVIEW_METRIC_SPECS: dict[str, tuple] = {
    "Elo": ("Elo [⬆️]", True, lambda v: str(int(round(v)))),
    "Improvability (%)": ("Improvability (%) [⬇️]", False, lambda v: f"{v:.1f}"),
    "Score": ("Score [⬆️]", True, lambda v: f"{v:.3f}"),
    "Average Rank": ("Rank [⬇️]", False, lambda v: f"{v:.2f}"),
    "Harmonic Rank": ("Harmonic Rank [⬇️]", False, lambda v: f"{v:.2f}"),
}
OVERVIEW_METRIC_CHOICES = list(_OVERVIEW_METRIC_SPECS)

# One-line TL;DR shown next to the overview metric selector.
OVERVIEW_METRIC_TLDR = {
    "Elo": "Pairwise win-rate rating (a 400-point gap ≈ a 91% win rate). Higher is better.",
    "Improvability (%)": "How much lower the best model's error is than this one's, per dataset. Lower is better.",
    "Score": "Error rescaled per dataset to 1 (best) … 0 (median), then averaged. Higher is better.",
    "Average Rank": "The model's mean rank across datasets. Lower is better.",
    "Harmonic Rank": "Harmonic mean of per-dataset ranks — rewards being excellent on some datasets. Lower is better.",
}


def _subset_best(df: pd.DataFrame, column: str, higher_is_better: bool) -> pd.DataFrame:
    """Best variant per model in a subset for `column`; excludes reference pipelines."""
    df = df[~df["TypeName"].isin([Constants.reference])].copy()
    df = df.dropna(subset=[column])
    parsed = df["Model"].map(parse_model)
    df["base"] = [p[0] for p in parsed]
    df["variant"] = [p[1] for p in parsed]
    df["url"] = [p[2] for p in parsed]
    df["imputed"] = df["Imputed"].astype(bool) if "Imputed" in df.columns else False
    df["verified"] = df["Verified"] if "Verified" in df.columns else ""
    grouped = df.groupby("base")[column]
    best = df.loc[grouped.idxmax() if higher_is_better else grouped.idxmin()]
    return best[
        ["base", "TypeName", "Type", "variant", "url", column, "verified", "imputed"]
    ].rename(columns={column: "val"})


def _overview_th(label: str, *, rowspan: int | None = None) -> str:
    """A subset column header `<th>`; gets a hover tooltip + 'help' affordance when defined."""
    attrs = f' rowspan="{rowspan}"' if rowspan else ""
    tooltip = _COLUMN_TOOLTIPS.get(label)
    if tooltip:
        attrs += f' class="ta-th-info" title="{html.escape(tooltip, quote=True)}"'
    return f"<th{attrs}>{label}</th>"


def _interp_color(frac: float) -> str:
    """Map 0 (best) .. 1 (worst) to a green->olive->red hex (readable on dark bg)."""
    stops = [(0.0, (28, 120, 62)), (0.5, (138, 122, 36)), (1.0, (160, 58, 58))]
    frac = max(0.0, min(1.0, frac))
    for (f0, c0), (f1, c1) in zip(stops, stops[1:]):
        if frac <= f1:
            t = 0 if f1 == f0 else (frac - f0) / (f1 - f0)
            r, g, b = (round(a + (b_ - a) * t) for a, b_ in zip(c0, c1))
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#a03a3a"


_OVERVIEW_CSS = """
<style>
.ta-overview { border-collapse: collapse; width: 100%; font-size: 1.08em; }
.ta-overview th, .ta-overview td { padding: 5px 9px; text-align: center; border: 1px solid #ffffff14; }
.ta-overview thead th { background: #1b1b22; font-weight: 600; position: sticky; z-index: 5; box-shadow: inset 0 1px 0 #ffffff14, inset 0 -1px 0 #ffffff14; }
/* Subset column headers carry an explanatory tooltip (title=); hint it with a help cursor + dotted underline. */
.ta-overview thead th.ta-th-info { cursor: help; text-decoration: underline; text-decoration-style: dotted; text-decoration-color: #ffffff66; text-underline-offset: 3px; }
.ta-overview thead tr:first-child th { top: 0; }
.ta-overview thead tr:nth-child(2) th { top: 33px; }
.ta-overview .ta-group-h { border-bottom: 2px solid #ffffff33; }
.ta-overview td.ta-model-cell { text-align: left; white-space: nowrap; }
/* Pinned to the same grey as the leaderboard table's variant tag (--muted there),
   so a "(tuned + ensembled)" reads identically in both tables. */
.ta-overview .ta-variant { color: #9b9a92; font-weight: 400; font-size: 0.9em; }
/* Numbers match the rest of the table text in size; bold keeps them emphasized. */
.ta-overview td.ta-num { font-weight: 600; }
/* Reserve a fixed-width medal slot in every number cell so the digits line up in their
   own sub-column whether or not a top-3 medal is present. */
.ta-overview td.ta-num .ta-cell { display: inline-flex; align-items: baseline; }
.ta-overview td.ta-num .ta-medal { flex: 0 0 1.45em; width: 1.45em; text-align: left; font-size: 0.78em; }
.ta-overview td.ta-na { color: #777; }
.ta-overview td.ta-model-cell a { text-decoration: underline; text-decoration-style: dotted; text-underline-offset: 3px; }
.ta-overview td.ta-model-cell a:hover { text-decoration-style: solid; }
.ta-link-icon { font-size: 0.78em; opacity: 0.65; margin-left: 2px; }
.ta-imp { color: #e6c14d; font-weight: 700; margin-left: 1px; }
.ta-verified { font-size: 0.85em; }
.ta-pill { padding: 1px 7px; border-radius: 999px; font-size: 0.95em; }
.ta-scroll {
    overflow: auto;
    max-height: 680px;
    border: 1px solid #ffffff1f;
    border-radius: 10px;
    scrollbar-width: thin;
    scrollbar-color: #ffffff3a transparent;
    scrollbar-gutter: stable;
}
.ta-scroll::-webkit-scrollbar { width: 11px; height: 11px; }
.ta-scroll::-webkit-scrollbar-track { background: transparent; }
.ta-scroll::-webkit-scrollbar-thumb { background: #ffffff33; border-radius: 8px; border: 3px solid transparent; background-clip: content-box; }
.ta-scroll::-webkit-scrollbar-thumb:hover { background: #ffffff5c; background-clip: content-box; }
.ta-scroll::-webkit-scrollbar-corner { background: transparent; }
.ta-cap { font-size: 0.85em; opacity: 0.8; margin: 6px 0 4px 0; }
.ta-legend { margin: 0 0 10px 0; }
</style>
"""


def type_legend_html(include_reference: bool = True) -> str:
    """A small legend explaining the model-type symbols (shared across tables).

    Baseline and Other share one color, so they are shown as a single entry.
    `include_reference` is False for the overview, which excludes reference pipelines.
    """
    e = model_type_emoji
    entries = [
        (Constants.foundational, e[Constants.foundational], "Foundation Model"),
        (Constants.neural_network, e[Constants.neural_network], "Neural Network"),
        (Constants.tree, e[Constants.tree], "Tree-based"),
        (Constants.baseline, f"{e[Constants.baseline]} {e[Constants.other]}", "Baseline / Other"),
    ]
    if include_reference:
        entries.append((Constants.reference, e[Constants.reference], "Reference Pipeline"))
    chips = []
    for type_name, symbols, label in entries:
        color = model_type_color.get(type_name, "#9e9e9e")
        chips.append(
            f'<span style="display:inline-block;margin:2px 12px 2px 0;white-space:nowrap;">'
            f'<span class="ta-pill" style="background:{color}22;color:{color};border:1px solid {color}66;">{symbols}</span> '
            f'<span style="color:{color};font-size:0.85em;">{label}</span></span>'
        )
    return f'{_OVERVIEW_CSS}<div class="ta-legend">{"".join(chips)}</div>'


def make_cross_subset_overview(data_root: Path, metric: str = "Elo") -> gr.HTML:
    """Heatmap of the best `metric` per model (rows) and subset (columns)."""
    if metric not in _OVERVIEW_METRIC_SPECS:
        metric = "Elo"
    column, higher_is_better, fmt = _OVERVIEW_METRIC_SPECS[metric]

    val_by_col: dict[str, dict[str, float]] = {}
    imp_by_col: dict[str, dict[str, bool]] = {}
    meta: dict[str, dict] = {}
    present: list[tuple[str, str]] = []  # (label, group)

    for label, group, subset in _OVERVIEW_COLUMNS:
        path = Path(data_root) / subset.rel_path / "website_leaderboard.csv"
        if not path.exists():
            continue
        best = _subset_best(load_leaderboard_csv(str(path.resolve())), column, higher_is_better)
        val_by_col[label] = dict(zip(best["base"], best["val"]))
        imp_by_col[label] = dict(zip(best["base"], best["imputed"]))
        present.append((label, group))
        for _, row in best.iterrows():
            meta.setdefault(
                row["base"],
                {
                    "type_name": row["TypeName"],
                    "emoji": row["Type"],
                    "variant": row["variant"],
                    "url": row["url"],
                    "verified": row["verified"],
                },
            )

    if not present:
        return gr.HTML("<p>No overview data available.</p>")

    sort_label = present[0][0]
    worst_sort = float("-inf") if higher_is_better else float("inf")
    bases = sorted(
        meta, key=lambda b: val_by_col[sort_label].get(b, worst_sort), reverse=higher_is_better
    )

    rank_by_col, bounds = {}, {}
    for label, _ in present:
        col = val_by_col[label]
        ranked = sorted(col, key=lambda b: col[b], reverse=higher_is_better)
        rank_by_col[label] = {b: i + 1 for i, b in enumerate(ranked[:3])}
        bounds[label] = (min(col.values()), max(col.values())) if col else (0.0, 1.0)

    # -- Grouped header (two rows)
    row1 = ['<th rowspan="2">Type</th>', '<th rowspan="2">Model</th>']
    row2 = []
    for group, items in groupby(present, key=lambda x: x[1]):
        items = list(items)
        if group == "overall":
            for label, _ in items:
                row1.append(_overview_th(label, rowspan=2))
        else:
            row1.append(f'<th colspan="{len(items)}" class="ta-group-h">{_GROUP_TITLE[group]}</th>')
            row2.extend(_overview_th(label) for label, _ in items)
    header = f"<thead><tr>{''.join(row1)}</tr><tr>{''.join(row2)}</tr></thead>"

    # -- Body
    body = []
    for base in bases:
        m = meta[base]
        color = model_type_color.get(m["type_name"], "#9e9e9e")
        name = html.escape(base)
        if m["variant"]:
            name += f' <span class="ta-variant">({html.escape(m["variant"])})</span>'
        if m.get("verified") == "✔️":
            name += ' <span class="ta-verified" title="Verified implementation">✔️</span>'
        if m["url"]:
            name_html = (
                f'<a href="{html.escape(m["url"])}" target="_blank" rel="noopener" '
                f'style="color:{color};font-weight:600;">{name}<span class="ta-link-icon">↗</span></a>'
            )
        else:
            name_html = f'<span style="color:{color};font-weight:600;">{name}</span>'
        cells = [
            f'<td><span class="ta-pill" style="background:{color}22;color:{color};'
            f'border:1px solid {color}66;">{m["emoji"]}</span></td>',
            f'<td class="ta-model-cell">{name_html}</td>',
        ]
        for label, _ in present:
            val = val_by_col[label].get(base)
            if val is None:
                cells.append('<td class="ta-na">–</td>')
                continue
            lo, hi = bounds[label]
            if hi <= lo:
                frac_best = 0.5
            else:
                frac_best = (val - lo) / (hi - lo) if higher_is_better else (hi - val) / (hi - lo)
            bg = _interp_color(1 - frac_best)
            medal = _MEDALS.get(rank_by_col[label].get(base), "")
            imp = (
                '<sup class="ta-imp" title="Score is (partly) imputed">*</sup>'
                if imp_by_col[label].get(base)
                else ""
            )
            cells.append(
                f'<td class="ta-num" style="background:{bg};color:#f7f7f7;">'
                f'<span class="ta-cell"><span class="ta-medal">{medal}</span>'
                f'<span class="ta-val">{fmt(val)}{imp}</span></span></td>'
            )
        body.append(f"<tr>{''.join(cells)}</tr>")

    direction = "Higher is better" if higher_is_better else "Lower is better"
    caption = (
        f'<div class="ta-cap">Best <b>{html.escape(metric)}</b> per model across subsets '
        f"(with imputation, all repeats). {direction}; 🥇🥈🥉 mark the top 3 in each column. "
        "Each model shows its best-performing variant.</div>"
        '<div class="ta-cap ta-cap-legend">✔️ = verified implementation &nbsp;·&nbsp; '
        '<span class="ta-imp">*</span> = (partly) imputed score &nbsp;·&nbsp; '
        "💡 Click any <u>underlined</u> model name (↗) to open its paper or code.</div>"
    )
    table = f'<table class="ta-overview">{header}<tbody>{"".join(body)}</tbody></table>'
    return gr.HTML(
        f'{type_legend_html(include_reference=False)}{caption}<div class="ta-scroll">{table}</div>',
        elem_classes="ta-overview-block",
    )


# --------------------------------------------------------------------------- #
# Agentic guide
# --------------------------------------------------------------------------- #


def make_agentic_guide() -> None:
    gr.Markdown(website_texts.AGENTIC_GUIDE, elem_classes="markdown-text-box")


def make_hero_stats(data_root: Path) -> gr.HTML:
    """A compact strip of headline-fact cards shown above the info boxes."""
    lb = LBContainer(data_root, Subset(), "")
    n_datasets = lb.n_datasets or "—"
    df = lb.load_df()
    df = df[~df["TypeName"].isin([Constants.reference])]
    n_models = len({parse_model(m)[0] for m in df["Model"]})
    paper = "https://tabarena.ai/paper-tabular-ml-iid-study"
    code = "https://tabarena.ai/code"

    cards = [
        (
            "🧾",
            f"{n_datasets} datasets",
            f'curated from 1,053 (<a href="{paper}" target="_blank" rel="noopener">see paper</a>)',
        ),
        ("🤖", f"{n_models}+ models", "state-of-the-art, each tuned to its peak"),
        (
            "✅",
            "Open-source",
            f'verified implementations (<a href="{code}" target="_blank" rel="noopener">see code</a>)',
        ),
        ("⚖️", "Scientifically rigorous", "strong validation, reproducible"),
    ]
    chips = "".join(
        f'<div class="ta-card"><div class="ta-card-ico">{ico}</div>'
        f'<div class="ta-card-body"><div class="ta-card-num">{num}</div>'
        f'<div class="ta-card-lbl">{lbl}</div></div></div>'
        for ico, num, lbl in cards
    )
    # Tagline rendered as a full-width card in the same group, above the stat boxes.
    intro = " ".join(website_texts.INTRODUCTION_TEXT.split())
    intro = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", intro)
    return gr.HTML(f'<div class="ta-hero"><div class="ta-intro">{intro}</div>{chips}</div>')


# --------------------------------------------------------------------------- #
# BeyondArena components
#
# BeyondArena reuses the per-subset leaderboard table (make_leaderboard) and the
# win-rate figure (make_winrate_image) unchanged; only the hero strip, the
# cross-subset overview (an image, not the TabArena HTML heatmap) and the
# per-subset figure set differ (no HPO tuning-trajectory figure — BeyondArena is
# evaluated on a single `core` protocol).
# --------------------------------------------------------------------------- #


# A distinct teal→violet accent for the BeyondArena hero, so its top reads clearly different from
# TabArena's neutral cards while staying in the same visual family (scoped to `.beyond-hero`).
_BEYOND_HERO_CSS = """
<style>
.beyond-hero .ta-card {
    border-color: #2dd4bf33;
    border-left: 3px solid #2dd4bf;
    background: linear-gradient(135deg, #2dd4bf1f, #7c5cf00d);
}
.beyond-hero .ta-card:hover { border-color: #2dd4bf99; }
.beyond-hero .ta-card-ico { color: #2dd4bf; }
.beyond-hero .ta-intro { border-left: 3px solid #7c5cf0; }
</style>
"""


def make_beyond_hero_stats(data_root: Path) -> gr.HTML:
    """A compact strip of headline-fact cards shown above the BeyondArena info boxes.

    Deliberately ordered / worded / colored differently from TabArena's hero: it leads with the
    beyond-IID identity and the curated subsets (the benchmark's focus) and uses a teal→violet accent.
    """
    lb = LBContainer(data_root, BeyondSubset("full"), "")
    n_datasets = lb.n_datasets or "—"
    df = lb.load_df()
    df = df[~df["TypeName"].isin([Constants.reference])]
    n_models = len({parse_model(m)[0] for m in df["Model"]})
    # Curated subsets = every subset tab except the "full" (whole-benchmark) view.
    n_subsets = len(BEYOND_SUBSET_LABELS) - 1
    paper = "https://arxiv.org/abs/2606.30410"
    code = "https://tabarena.ai/code"

    cards = [
        ("🌍", "Beyond IID", "non-IID, temporal &amp; grouped tabular data"),
        ("🧩", f"{n_subsets} subsets", "curated subsets of the benchmark"),
        (
            "🧾",
            f"{n_datasets} datasets",
            f'across sizes &amp; dimensionalities (<a href="{paper}" target="_blank" rel="noopener">see paper</a>)',
        ),
        (
            "🤖",
            f"{n_models} models",
            f'tuned pipelines with preprocessing, beyond IID (<a href="{code}" target="_blank" rel="noopener">see code</a>)',
        ),
    ]
    chips = "".join(
        f'<div class="ta-card"><div class="ta-card-ico">{ico}</div>'
        f'<div class="ta-card-body"><div class="ta-card-num">{num}</div>'
        f'<div class="ta-card-lbl">{lbl}</div></div></div>'
        for ico, num, lbl in cards
    )
    intro = " ".join(website_texts.BEYOND_INTRODUCTION_TEXT.split())
    intro = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", intro)
    return gr.HTML(f'{_BEYOND_HERO_CSS}<div class="ta-hero beyond-hero"><div class="ta-intro">{intro}</div>{chips}</div>')


def make_beyond_overview_figure(data_root: Path) -> None:
    """The cross-subset overview: best Elo per model / per family across every subset.

    Unlike TabArena's HTML heatmap, BeyondArena's overview is the ``plot_subset_results`` image
    (``result_plots/per_model_elo`` + ``per_family_elo``). Missing images are skipped gracefully.
    """
    result_dir = Path(data_root) / "result_plots"
    images = [
        ("per_family_elo", "Best Elo per model type (family) across subsets"),
        ("per_model_elo", "Best Elo per model across subsets"),
    ]
    shown = False
    for name, label in images:
        if (result_dir / f"{name}.png").exists() or (result_dir / f"{name}.png.zip").exists():
            gr.Image(
                unzip_png(result_dir, name),
                label=label,
                show_label=True,
                height=520,
            )
            shown = True
    if not shown:
        gr.Markdown("_The cross-subset overview figure is not available yet._", elem_classes="markdown-text")


def make_beyond_subset_figures(lb: LBContainer) -> None:
    """Per-subset figures for BeyondArena: the Elo overview and the inference-time Pareto front.

    Static figures only — BeyondArena deliberately does not use the interactive
    explorers that the TabArena tab embeds (see ``_switchable_figure``).
    """
    name = lb.name
    gr.Image(
        lb.image_path("tuning-impact-elo"),
        label=f"Leaderboard Overview [{name}]",
        show_label=True,
        height=320,
    )
    gr.Image(
        lb.image_path("pareto_front_improvability_vs_time_infer"),
        label=f"Inference Time Pareto Front [{name}]",
        show_label=True,
        height=450,
    )
