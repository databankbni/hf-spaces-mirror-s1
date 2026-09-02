import re
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from huggingface_hub import snapshot_download

from src.settings import API, DATASET_PAPER_LINK, METHOD_DESCRIPTIONS, PRETTY_NAME_TO_ADDITIONAL_INFO, PRETTY_NAME_TO_PAPER_LINK, REPO_ID


def restart_space():
    API.restart_space(repo_id=REPO_ID)


def download_leaderboard(remote_repo, local_repo, token):
    """
    Download the leaderboard dataframe from HuggingFace repo to local directory.
    """
    print(f"Loading leaderboard dataframe from HuggingFace repo {remote_repo} to {local_repo}")
    snapshot_download(
        repo_id=remote_repo,
        local_dir=local_repo,
        repo_type="dataset",
        tqdm_class=None,
        etag_timeout=30,
        token=token,
        ignore_patterns=["*.json"],
    )


def filter_leaderboard_df(df: pd.DataFrame, keep_models: list[str], keep_datasets: list[str]):
    """
    Filter the leaderboard dataframe based on the allowed models and datasets.
    """
    if keep_models:
        df = df[df["model"].isin(keep_models)]
    if keep_datasets:
        df = df[df["dataset"].isin(keep_datasets)]
    return df


def make_dataset_clickable(dataset_name):
    if dataset_name in DATASET_PAPER_LINK:
        link = DATASET_PAPER_LINK[dataset_name]
    else:
        link = f"https://huggingface.co/datasets/{dataset_name}"
    return link


def make_model_clickable(model_name):
    link = f"https://huggingface.co/{model_name}"
    return f'<a target="_blank" href="{link}" style="color: var(--link-text-color); text-decoration: underline;text-decoration-style: dotted;">{model_name}</a>'


def make_method_clickable(method_name, press_init_command=None):
    """
    Make method name clickable with optional tooltip showing press_init_command.

    Parameters
    ----------
    method_name : str
        The method name to make clickable
    press_init_command : str, optional
        The press initialization command to show as tooltip
    """
    # Handle NaN values
    if pd.isna(method_name):
        return ""

    if method_name in PRETTY_NAME_TO_PAPER_LINK:
        base_link = PRETTY_NAME_TO_PAPER_LINK[method_name]
        # If we have a press_init_command, add it as a tooltip
        if press_init_command:
            # Create a tooltip using HTML title attribute
            tooltip_html = f'<span style="cursor: help;" title="{press_init_command}">{base_link}</span>'
            return tooltip_html
        else:
            return base_link
    else:
        print(f"Method {method_name} not found in METHOD_PAPER_LINK")
        return method_name


def _extract_paper_url(method_name: str) -> Optional[str]:
    """Extract paper URL from PRETTY_NAME_TO_PAPER_LINK for clean hover display."""
    if method_name not in PRETTY_NAME_TO_PAPER_LINK:
        return None
    html = PRETTY_NAME_TO_PAPER_LINK[method_name]
    # Look for paper link
    paper_match = re.search(r"href='([^']*arxiv[^']*)'", html)
    if paper_match:
        return paper_match.group(1)
    # Try alternative quote style
    paper_match = re.search(r'href="([^"]*arxiv[^"]*)"', html)
    if paper_match:
        return paper_match.group(1)
    return None


def _extract_source_url(method_name: str) -> Optional[str]:
    """Extract source URL from PRETTY_NAME_TO_PAPER_LINK for clean hover display."""
    if method_name not in PRETTY_NAME_TO_PAPER_LINK:
        return None
    html = PRETTY_NAME_TO_PAPER_LINK[method_name]
    # Look for source link
    source_match = re.search(r"href='([^']*github[^']*)'", html)
    if source_match:
        return source_match.group(1)
    source_match = re.search(r'href="([^"]*github[^"]*)"', html)
    if source_match:
        return source_match.group(1)
    return None


def _get_extended_method_name(method_name: str) -> str:
    """Get extended method name with additional info."""
    base_info = PRETTY_NAME_TO_PAPER_LINK.get(method_name, method_name)
    # Extract just the press name (e.g., "SnapKVPress" from the full HTML)
    name_match = re.match(r"([A-Za-z]+(?:Press)?)", base_info)
    if name_match:
        press_name = name_match.group(1)
    else:
        press_name = method_name

    additional = PRETTY_NAME_TO_ADDITIONAL_INFO.get(method_name, "")
    if additional:
        return f"{press_name} {additional}"
    return press_name


def create_interactive_leaderboard_plot(
    df: pd.DataFrame,
    score_column: str = "score",
    title: Optional[str] = None,
    all_methods: Optional[list] = None,
):
    """
    Create a clean, professional plot with rich hover information.
    Faceted by model for clarity. Click legend items to isolate/compare methods.

    Hover shows:
    - All methods sorted by score (best first)
    - No Compression baseline for comparison
    - Extended method names with additional info
    - Paper/source links
    - Relative performance vs best and baseline

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with columns: method, compression_ratio, score_column, model
    score_column : str
        Column name containing the score values
    title : str
        Plot title
    all_methods : list, optional
        Full list of all methods (for consistent color assignment across filters).
        If None, uses methods from df.

    Returns
    -------
    plotly.graph_objects.Figure
        Interactive plotly figure
    """
    from plotly.subplots import make_subplots

    df = df.copy()

    # Separate no_press data
    if "No Compression" in df["method"].unique():
        no_press_df = df[df["method"] == "No Compression"]
        df = df[df["method"] != "No Compression"]
    else:
        no_press_df = None

    # Get unique models and methods
    unique_models = sorted(df["model"].unique().tolist())
    unique_methods = sorted(df["method"].unique().tolist())
    n_models = len(unique_models)

    # Use all_methods for consistent color assignment (if provided)
    # This ensures colors stay consistent when filtering by models
    color_method_list = sorted([m for m in (all_methods or unique_methods) if m != "No Compression"])

    # Return empty figure if no models selected
    if n_models == 0:
        fig = go.Figure()
        fig.update_layout(
            title=dict(text=title, x=0.5, font=dict(size=18)),
            annotations=[
                dict(
                    text="No models selected. Please select at least one model.",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(size=16, color="#666"),
                )
            ],
            height=700,
        )
        return fig

    # Professional color palette - vibrant and distinguishable
    COLOR_PALETTE = [
        "#2563eb",  # vivid blue
        "#dc2626",  # vivid red
        "#16a34a",  # vivid green
        "#9333ea",  # vivid purple
        "#ea580c",  # vivid orange
        "#0891b2",  # vivid cyan
        "#c026d3",  # vivid fuchsia
        "#ca8a04",  # vivid amber
        "#4f46e5",  # indigo
        "#059669",  # emerald
        "#e11d48",  # rose
        "#7c3aed",  # violet
        "#0284c7",  # sky
        "#65a30d",  # lime
        "#d97706",  # amber
        "#8b5cf6",  # purple
        "#06b6d4",  # teal
        "#f59e0b",  # yellow
        "#10b981",  # green
        "#6366f1",  # indigo light
    ]

    # Create color mapping - No Compression gets a special dark color
    # Use color_method_list (based on all_methods) for consistent colors across filters
    method_color_map = {method: COLOR_PALETTE[i % len(COLOR_PALETTE)] for i, method in enumerate(color_method_list)}
    no_compress_color = "#1e293b"  # slate-800

    # Create subplots - one column per model
    fig = make_subplots(
        rows=1,
        cols=n_models,
        subplot_titles=[f"<b>{m.split('/')[-1]}</b>" for m in unique_models],
        shared_yaxes=True,
        horizontal_spacing=0.06,
    )

    # Track which methods have been added to legend
    legend_added = set()

    # Pre-compute method info for hover
    method_info = {}
    for method in unique_methods + ["No Compression"]:
        paper_url = _extract_paper_url(method)
        source_url = _extract_source_url(method)
        extended_name = _get_extended_method_name(method)
        additional_info = PRETTY_NAME_TO_ADDITIONAL_INFO.get(method, "")
        method_info[method] = {
            "paper_url": paper_url,
            "source_url": source_url,
            "extended_name": extended_name,
            "additional_info": additional_info,
        }

    # Add traces for each model
    for col_idx, model in enumerate(unique_models, 1):
        model_df = df[df["model"] == model]

        # Get no_press score for this model for comparison
        no_press_score = None
        if no_press_df is not None:
            model_no_press = no_press_df[no_press_df["model"] == model]
            if not model_no_press.empty:
                no_press_score = model_no_press[score_column].iloc[0]

        for method in unique_methods:
            method_df = model_df[model_df["method"] == method].sort_values("compression_ratio")

            if method_df.empty:
                continue

            color = method_color_map[method]
            show_legend = method not in legend_added

            # Build rich hover text for each point
            hover_texts = []
            for _, row in method_df.iterrows():
                cr = row["compression_ratio"]

                # Get all methods at this compression ratio, sorted by score descending
                cr_data = model_df[model_df["compression_ratio"] == cr].sort_values(score_column, ascending=False)

                # Build hover content
                lines = []
                lines.append(f"<b>Compression {cr:.0%}</b>")
                lines.append("─" * 42)

                # Get max name length for alignment
                max_name_len = max(len(m_row["method"]) for _, m_row in cr_data.iterrows())
                max_name_len = max(max_name_len, len("No Compression"))

                # Add No Compression baseline first if available
                if no_press_score is not None:
                    nc_dot = f"<span style='color:{no_compress_color}'>◆</span>"
                    nc_padding = "\u00a0" * (max_name_len - len("No Compression") + 2)
                    lines.append(f"{nc_dot} <b>No Compression</b>{nc_padding}{no_press_score:6.2f}  (baseline)")
                    lines.append("")

                # Add all methods at this compression ratio
                for _, m_row in cr_data.iterrows():
                    m_name = m_row["method"]
                    m_score = m_row[score_column]
                    m_color = method_color_map.get(m_name, "#666")
                    m_info = method_info.get(m_name, {})

                    # Calculate relative performance vs baseline
                    rel_text = ""
                    if no_press_score is not None and no_press_score > 0:
                        diff = ((m_score - no_press_score) / no_press_score) * 100
                        if diff >= 0:
                            rel_text = f"(+{diff:.1f}%)"
                        else:
                            rel_text = f"({diff:.1f}%)"

                    # Pad name for alignment (using non-breaking spaces)
                    padding = "\u00a0" * (max_name_len - len(m_name) + 2)

                    # Colored dot - bold if this is the hovered method
                    if m_name == method:
                        dot = f"<span style='color:{m_color};font-size:14px'>●</span>"
                        name_display = f"<b>{m_name}</b>{padding}"
                    else:
                        dot = f"<span style='color:{m_color}'>●</span>"
                        name_display = f"{m_name}{padding}"

                    # Format score with fixed width
                    score_display = f"{m_score:6.2f}"

                    # Add additional info if present
                    additional = m_info.get("additional_info", "")
                    if additional:
                        additional_display = f"  {additional}"
                    else:
                        additional_display = ""

                    lines.append(f"{dot} {name_display}{score_display}  {rel_text}{additional_display}")

                # Add paper/source links for current method at bottom
                info = method_info.get(method, {})
                if info.get("paper_url") or info.get("source_url"):
                    lines.append("")
                    lines.append(f"─ {method} ─")
                    if info.get("paper_url"):
                        lines.append(f"📄 {info['paper_url']}")
                    if info.get("source_url"):
                        # Shorten the source URL for display
                        source_url = info["source_url"]
                        short_url = source_url.replace("https://github.com/NVIDIA/kvpress/blob/main/", "") if source_url else ""
                        lines.append(f"💻 {short_url}")

                hover_texts.append("<br>".join(lines))

            fig.add_trace(
                go.Scatter(
                    x=method_df["compression_ratio"],
                    y=method_df[score_column],
                    mode="lines+markers",
                    name=method,
                    legendgroup=method,
                    showlegend=show_legend,
                    visible="legendonly" if "query-aware" in method else True,
                    line=dict(color=color, width=2.5),
                    marker=dict(
                        color=color,
                        size=9,
                        line=dict(width=2, color="white"),
                    ),
                    opacity=0.9,
                    hovertemplate="%{customdata}<extra></extra>",
                    customdata=hover_texts,
                ),
                row=1,
                col=col_idx,
            )

            if show_legend:
                legend_added.add(method)

        # Add no_press as actual data points (not just a line) for hover
        if no_press_df is not None:
            model_no_press = no_press_df[no_press_df["model"] == model]
            if not model_no_press.empty:
                no_press_score = model_no_press[score_column].iloc[0]

                # Get x-range for baseline line
                if len(df["compression_ratio"]) > 0:
                    x_min = df["compression_ratio"].min() - 0.02
                    x_max = df["compression_ratio"].max() + 0.02
                else:
                    x_min, x_max = 0.0, 1.0

                # Hover text for No Compression
                separator = "─" * 32
                nc_hover = (
                    f"<b>No Compression Baseline</b><br>"
                    f"{separator}<br>"
                    f"Score: {no_press_score:.2f}<br><br>"
                    f"Baseline score without any<br>"
                    f"KV cache compression applied."
                )

                # Add dashed baseline line
                fig.add_trace(
                    go.Scatter(
                        x=[x_min, x_max],
                        y=[no_press_score] * 2,
                        mode="lines",
                        name="No Compression",
                        legendgroup="No Compression",
                        showlegend=(col_idx == 1),
                        line=dict(color=no_compress_color, width=2.5, dash="dash"),
                        opacity=0.8,
                        hoverinfo="skip",
                    ),
                    row=1,
                    col=col_idx,
                )

                # Add visible marker at left edge for hover
                fig.add_trace(
                    go.Scatter(
                        x=[x_min + 0.01],
                        y=[no_press_score],
                        mode="markers",
                        name="No Compression",
                        legendgroup="No Compression",
                        showlegend=False,
                        marker=dict(
                            color=no_compress_color,
                            size=12,
                            symbol="diamond",
                            line=dict(width=2, color="white"),
                        ),
                        hovertemplate=nc_hover + "<extra></extra>",
                    ),
                    row=1,
                    col=col_idx,
                )

    # Clean, professional layout
    fig.update_layout(
        title=dict(
            text=title or "KVPress Benchmark",
            font=dict(size=20, family="Inter, -apple-system, BlinkMacSystemFont, sans-serif", color="#1e293b"),
            x=0.5,
            xanchor="center",
        ),
        height=700,
        plot_bgcolor="#f8fafc",
        paper_bgcolor="white",
        font=dict(family="Inter, -apple-system, BlinkMacSystemFont, sans-serif", size=11, color="#334155"),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.12,
            xanchor="center",
            x=0.5,
            font=dict(size=11, color="#1e293b"),
            bgcolor="rgba(255,255,255,0.98)",
            bordercolor="rgba(0,0,0,0.08)",
            borderwidth=1,
            itemclick="toggle",
            itemdoubleclick="toggleothers",
            itemsizing="constant",
        ),
        hovermode="closest",
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.98)",
            bordercolor="rgba(0,0,0,0.1)",
            font=dict(size=12, family="'JetBrains Mono', 'SF Mono', 'Fira Code', Menlo, Consolas, monospace", color="#1e293b"),
            align="left",
            namelength=-1,
        ),
        margin=dict(t=60, b=110, l=60, r=35),
    )

    # Style subplot titles
    for annotation in fig.layout.annotations:
        annotation.font.size = 14
        annotation.font.color = "#1e293b"
        annotation.font.family = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"

    # Clean axis styling
    for i in range(1, n_models + 1):
        fig.update_xaxes(
            title_text="Compression Ratio" if i == (n_models + 1) // 2 else "",
            title_font=dict(size=12, color="#475569"),
            showgrid=True,
            gridwidth=1,
            gridcolor="rgba(0,0,0,0.05)",
            showline=True,
            linewidth=1,
            linecolor="rgba(0,0,0,0.12)",
            tickfont=dict(size=10, color="#64748b"),
            tickformat=".0%",
            row=1,
            col=i,
        )
        fig.update_yaxes(
            title_text="Score" if i == 1 else "",
            title_font=dict(size=12, color="#475569"),
            showgrid=True,
            gridwidth=1,
            gridcolor="rgba(0,0,0,0.05)",
            showline=True,
            linewidth=1,
            linecolor="rgba(0,0,0,0.12)",
            tickfont=dict(size=10, color="#64748b"),
            row=1,
            col=i,
        )

    return fig


# Color palette matching the plot for consistent visual language
CARD_COLOR_PALETTE = [
    "#2563eb",  # vivid blue
    "#dc2626",  # vivid red
    "#16a34a",  # vivid green
    "#9333ea",  # vivid purple
    "#ea580c",  # vivid orange
    "#0891b2",  # vivid cyan
    "#c026d3",  # vivid fuchsia
    "#ca8a04",  # vivid amber
    "#4f46e5",  # indigo
    "#059669",  # emerald
    "#e11d48",  # rose
    "#7c3aed",  # violet
    "#0284c7",  # sky
    "#65a30d",  # lime
    "#d97706",  # amber
    "#8b5cf6",  # purple
    "#06b6d4",  # teal
    "#f59e0b",  # yellow
    "#10b981",  # green
    "#6366f1",  # indigo light
]


def get_method_color(method_name: str, all_methods: list) -> str:
    """Get consistent color for a method based on its index in the sorted list."""
    sorted_methods = sorted([m for m in all_methods if m != "No Compression"])
    if method_name == "No Compression":
        return "#1e293b"  # slate-800
    try:
        idx = sorted_methods.index(method_name)
        return CARD_COLOR_PALETTE[idx % len(CARD_COLOR_PALETTE)]
    except ValueError:
        return "#64748b"  # slate-500 fallback


def generate_method_cards_html(df: pd.DataFrame, selected_method: Optional[str] = None) -> str:
    """
    Generate HTML for method cards view.

    Parameters
    ----------
    df : pd.DataFrame
        Filtered dataframe with method results
    selected_method : str, optional
        Currently selected method to highlight

    Returns
    -------
    str
        HTML string for the cards container
    """
    if df.empty:
        return "<div class='no-results'>No methods match the current filters.</div>"

    all_methods = df["method"].unique().tolist()

    # Group by method to get available compression ratios and models
    method_stats = (
        df.groupby("method")
        .agg(
            {
                "compression_ratio": lambda x: list(x.unique()),
                "model": lambda x: list(x.unique()),
            }
        )
        .reset_index()
    )
    method_stats = method_stats.sort_values("method", ascending=True)  # Sort alphabetically

    cards_html = []
    for _, row in method_stats.iterrows():
        method = row["method"]
        compression_ratios = row["compression_ratio"]
        models = row["model"]

        color = get_method_color(method, all_methods)
        paper_url = _extract_paper_url(method)
        source_url = _extract_source_url(method)
        warning = PRETTY_NAME_TO_ADDITIONAL_INFO.get(method, "")

        # Card selection state
        is_selected = method == selected_method
        selected_class = "selected" if is_selected else ""

        # Compression ratio display
        cr_display = ", ".join([f"{cr:.0%}" for cr in sorted(compression_ratios)[:3]])
        if len(compression_ratios) > 3:
            cr_display += f" +{len(compression_ratios) - 3}"

        # Model display (shortened)
        model_display = ", ".join([m.split("/")[-1] for m in models[:2]])
        if len(models) > 2:
            model_display += f" +{len(models) - 2}"

        # Build links
        links_html = ""
        if paper_url:
            links_html += f'<a href="{paper_url}" target="_blank" class="card-link paper-link" title="Read Paper">📄</a>'
        if source_url:
            links_html += f'<a href="{source_url}" target="_blank" class="card-link source-link" title="View Source">💻</a>'

        # Warning badge
        warning_html = f'<span class="warning-badge" title="{warning}">⚠️</span>' if warning else ""

        card = f"""
        <div class="method-card {selected_class}" data-method="{method}">
            <div class="card-header">
                <span class="method-dot" style="background-color: {color};"></span>
                <span class="method-name">{method}</span>
                {warning_html}
            </div>
            <div class="card-meta">
                <span class="meta-item">CR: {cr_display}</span>
                <span class="meta-divider">•</span>
                <span class="meta-item">{model_display}</span>
            </div>
            <div class="card-links">
                {links_html}
            </div>
        </div>
        """
        cards_html.append(card)

    return f"""
    <div class="method-cards-container">
        {"".join(cards_html)}
    </div>
    """


def generate_detail_panel_html(df: pd.DataFrame, method_name: Optional[str] = None, full_df: Optional[pd.DataFrame] = None) -> str:
    """
    Generate HTML for the method detail panel.

    Parameters
    ----------
    df : pd.DataFrame
        Filtered dataframe with method results
    method_name : str, optional
        The method to show details for
    full_df : pd.DataFrame, optional
        Full dataframe for baseline lookup (No Compression scores)

    Returns
    -------
    str
        HTML string for the detail panel
    """
    # Use full_df for baseline if provided, otherwise use df
    baseline_df = full_df if full_df is not None else df
    if not method_name:
        return """
        <div class="detail-panel empty">
            <div class="empty-state">
                <div class="empty-icon">👆</div>
                <div class="empty-text">Select a method from the cards to see details</div>
            </div>
        </div>
        """

    # Get method data
    method_df = df[df["method"] == method_name]
    if method_df.empty:
        return f"""
        <div class="detail-panel">
            <div class="empty-state">
                <div class="empty-text">No data found for {method_name}</div>
            </div>
        </div>
        """

    # Extract info
    paper_url = _extract_paper_url(method_name)
    source_url = _extract_source_url(method_name)
    description = METHOD_DESCRIPTIONS.get(method_name, "No description available.")
    warning = PRETTY_NAME_TO_ADDITIONAL_INFO.get(method_name, "")

    # Get press_init_command if available
    press_command = ""
    if "press_init_command" in method_df.columns:
        commands = method_df["press_init_command"].dropna().unique()
        if len(commands) > 0:
            press_command = commands[0]

    # Build performance table
    # Get No Compression baseline for each model (from full dataframe)
    no_press_df = baseline_df[baseline_df["method"] == "No Compression"]
    baseline_scores = {}
    for _, row in no_press_df.iterrows():
        model = row["model"]
        baseline_scores[model] = row["score"]

    # Build table rows for each model and compression ratio
    models = sorted(method_df["model"].unique())
    table_rows = []

    for model in models:
        model_data = method_df[method_df["model"] == model].sort_values("compression_ratio")
        model_short = model.split("/")[-1]
        baseline = baseline_scores.get(model, None)

        for _, row in model_data.iterrows():
            cr = row["compression_ratio"]
            score = row["score"]

            # Calculate degradation
            if baseline is not None and baseline > 0:
                diff = score - baseline
                diff_pct = (diff / baseline) * 100
                if diff >= 0:
                    diff_class = "positive"
                    diff_text = f"+{diff_pct:.1f}%"
                else:
                    diff_class = "negative"
                    diff_text = f"{diff_pct:.1f}%"
            else:
                diff_class = ""
                diff_text = "—"

            table_rows.append(
                f"""
                <tr>
                    <td class="model-cell">{model_short}</td>
                    <td class="cr-cell">{cr:.0%}</td>
                    <td class="score-cell">{score:.2f}</td>
                    <td class="diff-cell {diff_class}">{diff_text}</td>
                </tr>
            """
            )

    # Add baseline row for reference
    baseline_rows = []
    for model in models:
        model_short = model.split("/")[-1]
        baseline = baseline_scores.get(model, None)
        if baseline is not None:
            baseline_rows.append(
                f"""
                <tr class="baseline-row">
                    <td class="model-cell">{model_short}</td>
                    <td class="cr-cell">0%</td>
                    <td class="score-cell">{baseline:.2f}</td>
                    <td class="diff-cell">baseline</td>
                </tr>
            """
            )

    performance_table = f"""
    <div class="performance-section">
        <div class="section-label">Performance by Model</div>
        <table class="performance-table">
            <thead>
                <tr>
                    <th>Model</th>
                    <th>CR</th>
                    <th>Score</th>
                    <th>vs Baseline</th>
                </tr>
            </thead>
            <tbody>
                {"".join(baseline_rows)}
                {"".join(table_rows)}
            </tbody>
        </table>
    </div>
    """

    # Build links section
    links_html = '<div class="detail-links">'
    if paper_url:
        links_html += f'<a href="{paper_url}" target="_blank" class="detail-link paper"><span class="link-icon">📄</span> Read Paper</a>'
    if source_url:
        short_source = source_url.replace("https://github.com/NVIDIA/kvpress/blob/main/", "")
        links_html += (
            f'<a href="{source_url}" target="_blank" class="detail-link source"><span class="link-icon">💻</span> {short_source}</a>'
        )
    links_html += "</div>"

    # Warning section
    warning_html = f'<div class="detail-warning">{warning}</div>' if warning else ""

    # Code section
    code_html = ""
    if press_command:
        code_html = f"""
        <div class="code-section">
            <div class="code-header">
                <span>Usage</span>
                <button class="copy-btn" onclick="copyCode(this)" data-code="{press_command}">Copy</button>
            </div>
            <pre class="code-block"><code>{press_command}</code></pre>
        </div>
        """

    # Get the press class name from PRETTY_NAME_TO_PAPER_LINK
    press_class = method_name
    if method_name in PRETTY_NAME_TO_PAPER_LINK:
        match = re.match(r"([A-Za-z]+Press)", PRETTY_NAME_TO_PAPER_LINK[method_name])
        if match:
            press_class = match.group(1)

    # Use full_df for all_methods to ensure consistent colors across filters
    all_methods = baseline_df["method"].unique().tolist()
    color = get_method_color(method_name, all_methods)

    return f"""
    <div class="detail-panel">
        <div class="detail-header">
            <span class="detail-dot" style="background-color: {color};"></span>
            <h2 class="detail-title">{press_class}</h2>
        </div>
        
        {warning_html}
        
        <p class="detail-description">{description}</p>
        
        {performance_table}
        
        {links_html}
        
        {code_html}
    </div>
    """


def get_leaderboard_css() -> str:
    """Return custom CSS for the leaderboard cards and detail panel.

    Uses explicit colors with !important to ensure visibility regardless of
    the page theme (light or dark). All custom components have their own
    backgrounds so they remain readable.
    """
    return """
    <style>
    /* Method Cards Container */
    .method-cards-container {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 12px;
        padding: 16px;
        max-height: 500px;
        overflow-y: auto;
    }
    
    .method-card {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 12px;
        padding: 16px;
        cursor: pointer;
        transition: all 0.2s ease;
        position: relative;
    }
    
    .method-card:hover {
        border-color: #16a34a !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        transform: translateY(-2px);
    }
    
    .method-card.selected {
        border-color: #16a34a !important;
        border-width: 2px;
        background: linear-gradient(135deg, #f0fdf4 0%, #ffffff 100%) !important;
        box-shadow: 0 4px 16px rgba(22, 163, 74, 0.15);
    }
    
    .card-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
    }
    
    .method-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    
    .method-name {
        font-weight: 600;
        font-size: 15px;
        color: #1e293b !important;
        flex-grow: 1;
    }
    
    .warning-badge {
        font-size: 14px;
        cursor: help;
    }
    
    .card-meta {
        font-size: 12px;
        color: #64748b !important;
        display: flex;
        align-items: center;
        gap: 6px;
        margin-bottom: 12px;
    }
    
    .meta-divider {
        color: #cbd5e1 !important;
    }
    
    .card-links {
        display: flex;
        gap: 8px;
    }
    
    .card-link {
        font-size: 18px;
        text-decoration: none;
        opacity: 0.7;
        transition: opacity 0.2s;
    }
    
    .card-link:hover {
        opacity: 1;
    }
    
    /* Detail Panel */
    .detail-panel {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 16px;
        padding: 24px;
        min-height: 400px;
    }
    
    .detail-panel.empty {
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .empty-state {
        text-align: center;
        color: #64748b !important;
    }
    
    .empty-icon {
        font-size: 48px;
        margin-bottom: 12px;
    }
    
    .empty-text {
        font-size: 14px;
        color: #64748b !important;
    }
    
    .detail-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 16px;
    }
    
    .detail-dot {
        width: 14px;
        height: 14px;
        border-radius: 50%;
    }
    
    .detail-title {
        font-size: 24px;
        font-weight: 700;
        color: #1e293b !important;
        margin: 0;
    }
    
    .detail-description {
        color: #475569 !important;
        font-size: 14px;
        line-height: 1.6;
        margin-bottom: 20px;
    }
    
    .detail-warning {
        background: #fef3c7 !important;
        border: 1px solid #fcd34d !important;
        border-radius: 8px;
        padding: 10px 14px;
        color: #92400e !important;
        font-size: 13px;
        margin-bottom: 16px;
    }
    
    .detail-stats {
        display: flex;
        gap: 24px;
        margin-bottom: 20px;
        padding: 16px;
        background: #f8fafc !important;
        border-radius: 12px;
    }
    
    .stat-item {
        text-align: center;
        flex: 1;
    }
    
    .stat-value {
        font-size: 22px;
        font-weight: 700;
        color: #16a34a !important;
        font-family: 'JetBrains Mono', 'SF Mono', monospace;
    }
    
    .stat-label {
        font-size: 11px;
        color: #64748b !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-top: 4px;
    }
    
    .detail-links {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-bottom: 20px;
    }
    
    .detail-link {
        display: flex;
        align-items: center;
        gap: 8px;
        color: #16a34a !important;
        text-decoration: none;
        font-size: 13px;
        padding: 10px 14px;
        background: #f0fdf4 !important;
        border-radius: 8px;
        transition: background 0.2s;
    }
    
    .detail-link:hover {
        background: #dcfce7 !important;
    }
    
    .link-icon {
        font-size: 16px;
    }
    
    /* Performance Table */
    .performance-section {
        margin-bottom: 20px;
    }
    
    .section-label {
        font-size: 12px;
        color: #475569 !important;
        margin-bottom: 10px;
        font-weight: 500;
    }
    
    .performance-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
        background: #ffffff !important;
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid #e2e8f0 !important;
    }
    
    .performance-table thead {
        background: #f8fafc !important;
    }
    
    .performance-table th {
        padding: 10px 12px;
        text-align: left;
        font-weight: 600;
        color: #475569 !important;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        border-bottom: 1px solid #e2e8f0 !important;
    }
    
    .performance-table td {
        padding: 8px 12px;
        border-bottom: 1px solid #f1f5f9 !important;
        color: #334155 !important;
    }
    
    .performance-table tr:last-child td {
        border-bottom: none;
    }
    
    .performance-table .baseline-row {
        background: #f0fdf4 !important;
    }
    
    .performance-table .baseline-row td {
        font-weight: 500;
        color: #166534 !important;
    }
    
    .model-cell {
        font-weight: 500;
        color: #1e293b !important;
    }
    
    .cr-cell {
        font-family: 'JetBrains Mono', 'SF Mono', monospace;
        color: #64748b !important;
    }
    
    .score-cell {
        font-family: 'JetBrains Mono', 'SF Mono', monospace;
        font-weight: 600;
        color: #1e293b !important;
    }
    
    .diff-cell {
        font-family: 'JetBrains Mono', 'SF Mono', monospace;
        font-size: 12px;
        color: #64748b !important;
    }
    
    .diff-cell.positive {
        color: #16a34a !important;
        font-weight: 600;
    }
    
    .diff-cell.negative {
        color: #dc2626 !important;
    }
    
    .code-section {
        background: #1e293b;
        border-radius: 10px;
        overflow: hidden;
    }
    
    .code-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 14px;
        background: #334155;
        color: #94a3b8;
        font-size: 12px;
    }
    
    .copy-btn {
        background: #475569;
        border: none;
        color: #e2e8f0;
        font-size: 11px;
        padding: 4px 10px;
        border-radius: 4px;
        cursor: pointer;
        transition: background 0.2s;
    }
    
    .copy-btn:hover {
        background: #64748b;
    }
    
    .code-block {
        margin: 0;
        padding: 14px;
        color: #a5f3fc !important;
        font-size: 13px;
        font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
        overflow-x: auto;
        background: #1e293b !important;
    }
    
    .code-block code {
        white-space: pre-wrap;
        word-break: break-all;
        color: #a5f3fc !important;
        background: transparent !important;
    }
    
    .no-results {
        text-align: center;
        padding: 40px;
        color: #64748b !important;
        font-size: 14px;
    }
    
    /* Layout for cards + detail side by side */
    .leaderboard-content {
        display: grid;
        grid-template-columns: 1fr 380px;
        gap: 20px;
        align-items: start;
    }
    
    @media (max-width: 1024px) {
        .leaderboard-content {
            grid-template-columns: 1fr;
        }
    }
    
    /* Style the Radio component as a nice list */
    #method-selector-radio {
        max-height: 450px;
        overflow-y: auto;
    }
    
    #method-selector-radio .wrap {
        gap: 8px !important;
    }
    
    #method-selector-radio label {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 10px !important;
        padding: 12px 16px !important;
        cursor: pointer !important;
        transition: all 0.2s ease !important;
        margin: 0 !important;
    }
    
    #method-selector-radio label:hover {
        border-color: #16a34a !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
    }
    
    #method-selector-radio label.selected {
        border-color: #16a34a !important;
        border-width: 2px !important;
        background: linear-gradient(135deg, #f0fdf4 0%, #ffffff 100%) !important;
        box-shadow: 0 2px 12px rgba(22, 163, 74, 0.12) !important;
    }
    
    #method-selector-radio label span {
        font-weight: 500 !important;
        color: #1e293b !important;
    }
    
    #method-selector-radio input[type="radio"] {
        accent-color: #16a34a !important;
    }
    </style>
    
    <script>
    function copyCode(btn) {
        const code = btn.getAttribute('data-code');
        navigator.clipboard.writeText(code).then(() => {
            const originalText = btn.textContent;
            btn.textContent = 'Copied!';
            setTimeout(() => {
                btn.textContent = originalText;
            }, 2000);
        });
    }
    </script>
    """
