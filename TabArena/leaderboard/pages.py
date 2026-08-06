"""Top-level leaderboard pages and their rendering.

The app shows a tab bar of :data:`PAGES`. Each page is either ``internal`` (a
full leaderboard rendered from its own data root, reusing all the machinery in
``views.py``) or ``external`` (a short description plus a link to a leaderboard
hosted elsewhere). Adding a leaderboard is a one-entry edit to :data:`PAGES`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import gradio as gr

import website_texts
from data_loading import (
    BEYOND_DATA_DIR,
    BEYOND_SUBSET_LABELS,
    DATA_DIR,
    DATASET_LABELS,
    BeyondSubset,
    LBContainer,
    Subset,
    TASK_LABELS,
    beyond_subset_blurb,
    beyond_subset_name,
    subset_blurb,
    subset_name,
)
from views import (
    OVERVIEW_METRIC_CHOICES,
    OVERVIEW_METRIC_TLDR,
    make_agentic_guide,
    make_beyond_hero_stats,
    make_beyond_overview_figure,
    make_beyond_subset_figures,
    make_cross_subset_overview,
    make_hero_stats,
    make_leaderboard,
    make_overview_images,
    make_winrate_image,
)


@dataclass
class LeaderboardPage:
    name: str  # tab label
    kind: str  # "internal" | "beyondarena" | "external" | "invite"
    data_root: Path | None = None  # internal: where this leaderboard's data lives
    url: str | None = None  # external: link target (Hugging Face Space, etc.)
    paper_url: str | None = None  # external: optional paper link
    tagline: str | None = None  # external: short one-line pitch
    blurb: str | None = None  # external: markdown description


PAGES: list[LeaderboardPage] = [
    LeaderboardPage(name="🥇 TabArena (IID)", kind="internal", data_root=DATA_DIR),
    LeaderboardPage(name="🧭 BeyondArena", kind="beyondarena", data_root=BEYOND_DATA_DIR),
    LeaderboardPage(
        name="🔬 RamanBench",
        kind="external",
        url="https://huggingface.co/spaces/HTW-KI-Werkstatt/RamanBench",
        paper_url="https://arxiv.org/abs/2605.02003",
        tagline=website_texts.RAMANBENCH_TAGLINE,
        blurb=website_texts.RAMANBENCH_BLURB,
    ),
    # A signpost to the neighbouring time-series field (forecasting + classification/
    # regression); bespoke layout in render_timeseries_page, copy in website_texts.
    LeaderboardPage(name="⏳ Time-series", kind="timeseries"),
    # An open call-to-action: invite the community to bring their own benchmark
    # into the ecosystem. Content lives in render_invite_page / website_texts.
    LeaderboardPage(name="➕ Your Benchmark?", kind="invite"),
    # To host another leaderboard here, drop its artifacts under a new data root
    # and add:  LeaderboardPage(name="…", kind="internal", data_root=Path(...))
]


_INFO_TOPICS = [
    ("datasets", "🧾 Datasets"),
    ("models", "🤖 Models"),
    ("metrics", "📈 Metrics & Imputation"),
    ("reference", "📐 Reference Pipelines"),
    ("about", "📝 About"),
    ("citation", "📙 Citation"),
]


def _render_info_boxes(
    info_text: dict[str, str] | None = None,
    *,
    topics: list[tuple[str, str]] | None = None,
    citation_label: str | None = None,
    citation_text: str | None = None,
) -> None:
    """A row of topic pills that reveal a single shared detail panel on demand.

    Replaces the stacked accordions: compact by default, no grid layout-shift,
    and only one topic open at a time (click an active pill again to close).

    Defaults to the TabArena copy; pass ``info_text`` / ``topics`` / ``citation_*``
    to reuse the same widget for another leaderboard (e.g. BeyondArena).
    """
    if info_text is None:
        info_text = {
            "datasets": website_texts.OVERVIEW_DATASETS,
            "models": website_texts.OVERVIEW_MODELS,
            "metrics": website_texts.OVERVIEW_METRICS,
            "reference": website_texts.OVERVIEW_REF_PIPE,
            "about": website_texts.ABOUT_TEXT,
        }
    if topics is None:
        topics = _INFO_TOPICS
    if citation_label is None:
        citation_label = website_texts.CITATION_BUTTON_LABEL
    if citation_text is None:
        citation_text = website_texts.CITATION_BUTTON_TEXT
    open_topic = gr.State("")

    @gr.render(inputs=[open_topic])
    def _info(topic):
        with gr.Row(elem_classes="info-pills"):
            for key, label in topics:
                btn = gr.Button(
                    label,
                    size="sm",
                    variant="primary" if key == topic else "secondary",
                    scale=0,
                    min_width=10,
                )
                btn.click(
                    lambda cur, k=key: "" if cur == k else k,
                    open_topic,
                    open_topic,
                    api_visibility="private",
                )
        if not topic:
            return
        with gr.Group(elem_classes="info-panel"):
            if topic == "citation":
                gr.Textbox(
                    value=citation_text,
                    label=citation_label,
                    lines=7,
                    elem_id="citation-button",
                    show_copy_button=True,
                )
            else:
                gr.Markdown(info_text[topic], elem_classes="markdown-text-box")


def _axis_setter(values: list[str]):
    """A tab-bar select handler that reports which subset the reader picked.

    Wired on the bar rather than on each tab, because Gradio 6 raises the two events
    by different routes: the bar's select comes straight out of the tab button's
    click handler, while a TabItem's own select comes from an effect watching the
    selected index, and that one does not fire when you come back to the tab that
    was selected on page load. The event carries the index of the tab clicked, so
    `values` is the axis in tab order.
    """

    def setter(evt: gr.SelectData) -> str:
        return values[evt.index]

    return setter


def render_internal_page(page: LeaderboardPage) -> None:
    make_hero_stats(page.data_root)
    _render_info_boxes()

    # -- Cross-subset overview (the at-a-glance summary across all subsets)
    gr.HTML(
        '<div class="ta-section-head">'
        '<div class="ta-section-row">'
        "<h2>🔭 Performance at a Glance</h2>"
        '<a href="#lb-detailed" class="ta-jump" '
        "onclick=\"document.getElementById('lb-detailed').scrollIntoView({behavior:'smooth'});return false;\">"
        "⬇️ Jump to detailed results</a>"
        "</div>"
        '<p class="ta-section-sub">Best result per model across every task and dataset-size subset — '
        "the quickest way to spot the models that are strong everywhere versus those that shine on "
        "specific subsets.</p>"
        "</div>"
    )
    with gr.Row(elem_classes="metric-select"):
        overview_metric = gr.Dropdown(
            choices=OVERVIEW_METRIC_CHOICES,
            value="Elo",
            show_label=False,
            container=False,
            filterable=False,
            scale=0,
            min_width=200,
        )
        metric_tldr = gr.Markdown(OVERVIEW_METRIC_TLDR["Elo"], elem_classes="metric-tldr")
    overview_metric.change(
        lambda m: OVERVIEW_METRIC_TLDR.get(m, ""), overview_metric, metric_tldr, api_visibility="private"
    )

    @gr.render(inputs=[overview_metric])
    def _render_overview(metric):
        make_cross_subset_overview(page.data_root, metric)

    # -- Leaderboards
    gr.HTML(
        '<div class="ta-section-head" id="lb-detailed">'
        "<h2>🏆 TabArena Leaderboards</h2>"
        '<p class="ta-section-sub">Pick a task and dataset-size subset with the tabs below, then use the '
        "toggles to switch imputation on/off or view the cheaper TabArena-Lite results.</p>"
        "</div>"
    )

    impute_state = gr.State("yes")
    splits_state = gr.State("all")
    tasks_state = gr.State("all")
    datasets_state = gr.State("all")

    # The two content axes, each labelled with the axis it switches and colour-coded
    # per choice (see the .tab-buttons rules in main.CSS), so they carry the same
    # weight as the view toggles underneath them.
    with gr.Tabs(elem_classes=["tab-buttons", "axis-tasks"]) as task_bar:
        for value, label in TASK_LABELS.items():
            with gr.TabItem(label, id=f"task_{value}"):
                pass
    task_bar.select(_axis_setter(list(TASK_LABELS)), outputs=tasks_state, api_visibility="private")
    with gr.Tabs(elem_classes=["tab-buttons", "axis-datasets"]) as dataset_bar:
        for value, label in DATASET_LABELS.items():
            with gr.TabItem(label, id=f"ds_{value}"):
                pass
    dataset_bar.select(
        _axis_setter(list(DATASET_LABELS)), outputs=datasets_state, api_visibility="private"
    )

    with gr.Row(elem_classes="view-toggles"):
        impute_cb = gr.Checkbox(
            value=True, label="Include imputed models", scale=0, min_width=205, container=False
        )
        lite_cb = gr.Checkbox(
            value=False, label="TabArena-Lite (single split)", scale=0, min_width=235, container=False
        )
        gr.Column(scale=1)
    impute_cb.change(lambda v: "yes" if v else "no", impute_cb, impute_state, api_visibility="private")
    lite_cb.change(lambda v: "lite" if v else "all", lite_cb, splits_state, api_visibility="private")

    @gr.render(inputs=[impute_state, splits_state, tasks_state, datasets_state])
    def _render_subset(imp, spl, tsk, dst):
        subset = Subset(imputation=imp, splits=spl, tasks=tsk, datasets=dst)
        lb = LBContainer(data_root=page.data_root, subset=subset, name=subset_name(subset))
        gr.Markdown(subset_blurb(subset, lb.n_datasets), elem_classes="markdown-text")
        make_overview_images(lb)
        # Figures first, then the table: the win-rate matrix belongs with the other
        # figures above it, and the table reads as the detailed reference at the end.
        make_winrate_image(lb)
        # The table card carries its own title and column key (see make_leaderboard).
        make_leaderboard(lb)

    with gr.Accordion("⚙️ Agentic Use & Interpretation", open=False):
        make_agentic_guide()

    with gr.Accordion("📂 Version History", open=False):
        gr.Markdown(website_texts.VERSION_HISTORY_BUTTON_TEXT, elem_classes="markdown-text")


# BeyondArena omits TabArena's "reference pipelines" topic (its own copy folds any
# reference into the metrics/models topics).
_BEYOND_INFO_TOPICS = [
    ("datasets", "🧾 Datasets"),
    ("models", "🤖 Models"),
    ("metrics", "📈 Metrics & Core Protocol"),
    ("about", "📝 About"),
    ("citation", "📙 Citation"),
]


def render_beyondarena_page(page: LeaderboardPage) -> None:
    """The BeyondArena leaderboard: a single subset axis, always on the ``core`` protocol.

    Reuses the per-subset leaderboard table and win-rate figure from the TabArena machinery; the
    cross-subset overview is an image (``plot_subset_results``) rather than the TabArena HTML heatmap,
    and there is no imputation / splits / task grid — just one subset tab bar.
    """
    # Graceful fallback until the artifacts are generated (see
    # scripts/run_generate_beyondarena_website_artifacts.py in the tabarena repo).
    full_csv = page.data_root / BeyondSubset("full").rel_path / "website_leaderboard.csv"
    if not full_csv.exists():
        gr.Markdown(f"## {page.name}")
        gr.Markdown(
            "### *The first unified benchmark for tabular data beyond the IID assumption.*",
            elem_classes="markdown-text",
        )
        gr.Markdown(
            "BeyondArena results are not available in this deployment yet. Generate them with "
            "`scripts/run_generate_beyondarena_website_artifacts.py` (tabarena repo) and drop the "
            f"artifacts under `{page.data_root.name}/`.",
            elem_classes="markdown-text",
        )
        return

    make_beyond_hero_stats(page.data_root)
    _render_info_boxes(
        info_text={
            "datasets": website_texts.BEYOND_OVERVIEW_DATASETS,
            "models": website_texts.BEYOND_OVERVIEW_MODELS,
            "metrics": website_texts.BEYOND_OVERVIEW_METRICS,
            "about": website_texts.BEYOND_ABOUT_TEXT,
        },
        topics=_BEYOND_INFO_TOPICS,
        citation_label=website_texts.BEYOND_CITATION_BUTTON_LABEL,
        citation_text=website_texts.BEYOND_CITATION_BUTTON_TEXT,
    )

    # -- Cross-subset overview (image, not the TabArena HTML heatmap)
    gr.HTML(
        '<div class="ta-section-head">'
        '<div class="ta-section-row">'
        "<h2>🔭 Performance across subsets</h2>"
        '<a href="#beyond-lb-detailed" class="ta-jump" '
        "onclick=\"document.getElementById('beyond-lb-detailed').scrollIntoView({behavior:'smooth'});return false;\">"
        "⬇️ Jump to detailed results</a>"
        "</div>"
        '<p class="ta-section-sub">Best result per model and per model family across every BeyondArena '
        "subset — the quickest way to see which methods hold up beyond the IID assumption.</p>"
        "</div>"
    )
    with gr.Accordion(
        "🧩 What do the subsets mean?", open=False, elem_classes="beyond-subsets-accordion"
    ):
        gr.Markdown(website_texts.BEYOND_SUBSETS_EXPLAINER, elem_classes="markdown-text-box")
    make_beyond_overview_figure(page.data_root)

    # -- Leaderboards
    gr.HTML(
        '<div class="ta-section-head" id="beyond-lb-detailed">'
        "<h2>🏆 BeyondArena Leaderboards</h2>"
        '<p class="ta-section-sub">Pick a subset below — a split regime, dataset-size bucket, or '
        "feature subset. Every leaderboard is computed on the recommended <b>core</b> protocol.</p>"
        "</div>"
    )

    subset_state = gr.State("full")
    with gr.Tabs(elem_classes="tab-buttons") as subset_bar:
        for value, label in BEYOND_SUBSET_LABELS.items():
            with gr.TabItem(label, id=f"beyond_{value}"):
                pass
    subset_bar.select(
        _axis_setter(list(BEYOND_SUBSET_LABELS)), outputs=subset_state, api_visibility="private"
    )

    @gr.render(inputs=[subset_state])
    def _render_beyond_subset(sub):
        subset = BeyondSubset(subset=sub)
        lb = LBContainer(data_root=page.data_root, subset=subset, name=beyond_subset_name(subset))
        gr.Markdown(beyond_subset_blurb(subset, lb.n_datasets), elem_classes="markdown-text")
        make_beyond_subset_figures(lb)
        # Same order as the TabArena page: figures, then the table.
        # BeyondArena keeps the static win-rate figure; the interactive panel is
        # TabArena's.
        make_winrate_image(lb, interactive=False)
        make_leaderboard(lb)


def render_external_page(page: LeaderboardPage) -> None:
    gr.Markdown(f"## {page.name}")
    if page.tagline:
        gr.Markdown(f"### *{page.tagline}*", elem_classes="markdown-text")
    if page.blurb:
        gr.Markdown(page.blurb, elem_classes="markdown-text")
    # Use real anchors with target="_blank" rather than gr.Button(link=...): Gradio's
    # link buttons render as same-tab <a> tags, which (inside the Hugging Face Space
    # iframe) navigate within the embed instead of opening the external site in a new tab.
    links: list[tuple[str, str, str]] = []
    if page.url:
        links.append(("Open on Hugging Face ↗", page.url, "primary"))
    if page.paper_url:
        links.append(("Read the paper ↗", page.paper_url, "secondary"))
    if links:
        anchors = "".join(
            f'<a class="ta-link-btn {variant}" href="{url}" '
            f'target="_blank" rel="noopener noreferrer">{label}</a>'
            for label, url, variant in links
        )
        gr.HTML(f'<div class="link-row">{anchors}</div>')


def render_invite_page(page: LeaderboardPage) -> None:
    """An open invitation for the community to add their benchmark to the ecosystem.

    Bespoke layout (not data-driven): a warm intro, two "paths" (endorse an
    existing benchmark vs. help build a new one), what makes a good fit, and
    contact buttons. All copy lives in :mod:`website_texts`.
    """
    gr.Markdown(f"## {page.name}")
    gr.Markdown(f"### *{website_texts.YOUR_BENCHMARK_TAGLINE}*", elem_classes="markdown-text")
    gr.Markdown(website_texts.YOUR_BENCHMARK_INTRO, elem_classes="markdown-text")

    # Two side-by-side path cards.
    cards = "".join(
        f'<div class="ta-path"><div class="ta-path-ico">{icon}</div>'
        f"<h3>{heading}</h3><p>{body}</p></div>"
        for icon, heading, body in website_texts.YOUR_BENCHMARK_PATHS
    )
    gr.HTML(f'<div class="ta-paths">{cards}</div>')

    gr.Markdown(website_texts.YOUR_BENCHMARK_FIT, elem_classes="markdown-text")

    # Set expectations up front: the collaboration model is flexible, not one-size-fits-all.
    gr.HTML(
        '<div class="ta-invite-note">ℹ️ <b>How it works:</b> there is no single recipe. A benchmark can '
        "stay fully owned and maintained by its authors — we review it, endorse its methodology, and "
        "credit the team — or we can maintain it together, and you are welcome to reuse TabArena's code "
        "and infrastructure to build it. We will find the setup that works best for you.</div>"
    )

    gr.Markdown(website_texts.YOUR_BENCHMARK_CONTACT, elem_classes="markdown-text")

    # Real new-tab anchors (see render_external_page for why not gr.Button(link=...)).
    anchors = "".join(
        f'<a class="ta-link-btn {variant}" href="{href}" '
        f'target="_blank" rel="noopener noreferrer">{label}</a>'
        for label, href, variant in website_texts.YOUR_BENCHMARK_LINKS
    )
    gr.HTML(f'<div class="link-row">{anchors}</div>')


def render_timeseries_page(page: LeaderboardPage) -> None:
    """A signpost page for the neighbouring time-series field.

    TabArena is tabular ML; this page introduces time series, explains how it
    differs from IID tabular ML, and links the forecasting and classification/regression
    benchmarks that BeyondArena references. All copy lives in :mod:`website_texts`.
    """
    gr.Markdown(f"## {page.name}")
    gr.Markdown(f"### *{website_texts.TIMESERIES_TAGLINE}*", elem_classes="markdown-text")
    gr.Markdown(website_texts.TIMESERIES_INTRO, elem_classes="markdown-text")

    gr.Markdown(website_texts.TIMESERIES_FORECASTING, elem_classes="markdown-text")
    gr.Markdown(website_texts.TIMESERIES_CLASSREG, elem_classes="markdown-text")
    gr.Markdown(website_texts.TIMESERIES_CLOSING, elem_classes="markdown-text")


def render_page(page: LeaderboardPage) -> None:
    if page.kind == "external":
        render_external_page(page)
    elif page.kind == "invite":
        render_invite_page(page)
    elif page.kind == "timeseries":
        render_timeseries_page(page)
    elif page.kind == "beyondarena":
        render_beyondarena_page(page)
    else:
        render_internal_page(page)
