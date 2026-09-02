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
    SYSTEM_CATEGORY_LABELS,
    BeyondSubset,
    LBContainer,
    Subset,
    TASK_LABELS,
    available_categories,
    entrants_categories,
    beyond_subset_blurb,
    beyond_subset_name,
    entrants_key,
    subset_blurb,
    subset_name,
)
from views import (
    CARE_LABELS,
    CONTROLS_ANCHOR,
    make_figure_contents,
    make_selection_bar,
    METRIC_LABELS,
    METRIC_TO_OVERVIEW,
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
    make_per_dataset_block,
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
    ("models", "🤖📊 Models & Systems"),
    ("metrics", "📈 Metrics & Imputation"),
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
                    # Gradio 6 replaced `show_copy_button=True` with the `buttons` list. The old
                    # argument raised a TypeError, and because this component is only built when
                    # the Citation pill is opened, the crash only surfaced on click.
                    buttons=["copy"],
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


def _render_control_band(
    data_root: Path,
    entrants_state: gr.State,
    care_state: gr.State,
    metric_state: gr.State,
    impute_state: gr.State,
    splits_state: gr.State,
    tasks_state: gr.State,
    datasets_state: gr.State,
) -> None:
    """Every selector, in one card at the top of the page.

    They belong together because they all describe *which leaderboard you are looking at*, and
    they belong at the top because the first of them changes the numbers themselves rather than
    filtering them: each combination of entrant categories is its own evaluation, since Elo is
    pairwise over the participants and improvability is the gap to the best of them.

    The system categories are independent checkboxes, not a ladder, so "LLM-based systems but
    not the plain open-source ones" is expressible. A category nobody has submitted to yet is
    rendered disabled rather than silently doing nothing.
    """
    available = available_categories(str(data_root))
    gr.HTML(
        '<div class="ta-section-head">'
        "<h2>🎛️ Select Your Leaderboard</h2>"
        '<p class="ta-section-sub">Pick what you care about and build the leaderboard around your '
        "constraints. Who competes changes the numbers themselves, since the metrics are relative "
        "and depend on which methods are being compared.</p>"
        "</div>"
    )

    with gr.Column(elem_classes="ta-controls", elem_id=CONTROLS_ANCHOR):
        # The row caption is a CSS ::before like the chip bars', not an HTML block: a gr.HTML
        # label brings its own padded wrapper, which is what made these two rows sit at a
        # different size and alignment from the rest of the card.
        with gr.Row(elem_classes=["ta-controlrow", "ta-row-entrants"]):
            gr.Checkbox(
                value=True,
                label="🤖 Models",
                interactive=False,
                container=False,
                scale=0,
                min_width=150,
                # Not `ta-soon`: this one is on and staying on, which is the opposite of the
                # dimmed "no entrant yet" state next to it.
                elem_classes=["ta-catchip", "ta-always"],
            )
            category_boxes = []
            for key, label in SYSTEM_CATEGORY_LABELS.items():
                is_available = key in available
                category_boxes.append(
                    gr.Checkbox(
                        value=False,
                        label=label,
                        interactive=is_available,
                        container=False,
                        scale=0,
                        min_width=230,
                        elem_classes=["ta-catchip"] if is_available else ["ta-catchip", "ta-soon"],
                    )
                )

        # The single-select axes are all chip bars, so "I care about" reads the same way as
        # task and dataset size rather than as a different kind of control.
        with gr.Tabs(elem_classes=["tab-buttons", "axis-care"]) as care_bar:
            for value, label in CARE_LABELS.items():
                with gr.TabItem(label, id=f"care_{value}"):
                    pass
        with gr.Tabs(elem_classes=["tab-buttons", "axis-metric"]) as metric_bar:
            for value, label in METRIC_LABELS.items():
                with gr.TabItem(label, id=f"metric_{value}"):
                    pass

        # One chip bar per content axis, the layout these had before they moved into the card:
        # a labelled row of chips reads faster than a radio list when there are five choices.
        with gr.Tabs(elem_classes=["tab-buttons", "axis-tasks"]) as task_bar:
            for value, label in TASK_LABELS.items():
                with gr.TabItem(label, id=f"task_{value}"):
                    pass
        with gr.Tabs(elem_classes=["tab-buttons", "axis-datasets"]) as dataset_bar:
            for value, label in DATASET_LABELS.items():
                with gr.TabItem(label, id=f"ds_{value}"):
                    pass

        with gr.Row(elem_classes=["ta-controlrow", "ta-row-protocol"]):
            impute_cb = gr.Checkbox(
                value=True,
                label="Include imputed models",
                container=False,
                scale=0,
                min_width=205,
                elem_classes=["ta-catchip"],
            )
            lite_cb = gr.Checkbox(
                value=False,
                label="TabArena-Lite (single split)",
                container=False,
                scale=0,
                min_width=245,
                elem_classes=["ta-catchip"],
            )

    # Each category box maps to one bit of the pool key; recompute the whole key on any change
    # so the folder segment stays order-independent.
    def _set_entrants(*flags):
        return entrants_key([key for key, on in zip(SYSTEM_CATEGORY_LABELS, flags, strict=True) if on])

    for box in category_boxes:
        box.change(_set_entrants, category_boxes, entrants_state, api_visibility="private")
    care_bar.select(_axis_setter(list(CARE_LABELS)), outputs=care_state, api_visibility="private")
    # No JS hook needed: switching the metric re-renders the figure stack, and each panel's
    # wrapper carries the metric it should show as a class, which every fresh frame is told
    # when it reports its height (see views.make_overview_images and main.taSendMetric).
    metric_bar.select(_axis_setter(list(METRIC_LABELS)), outputs=metric_state, api_visibility="private")
    task_bar.select(_axis_setter(list(TASK_LABELS)), outputs=tasks_state, api_visibility="private")
    dataset_bar.select(_axis_setter(list(DATASET_LABELS)), outputs=datasets_state, api_visibility="private")
    impute_cb.change(lambda v: "yes" if v else "no", impute_cb, impute_state, api_visibility="private")
    lite_cb.change(lambda v: "lite" if v else "all", lite_cb, splits_state, api_visibility="private")

    # No standing summary of the selection: every control now carries its own text on hover, and
    # repeating it under the card was the same words twice. The comparability callout stays,
    # because that is a warning about the results rather than a description of a control.
    # A warning per system category, and only for the ones actually competing. container=False
    # so Gradio draws no block chrome of its own and each warning is a single box drawn by
    # .ta-warnbox.
    # Re-rendered on any selector change, so the bar can never describe a stale view.
    @gr.render(
        inputs=[entrants_state, care_state, metric_state, tasks_state, datasets_state, impute_state, splits_state]
    )
    def _render_selection_bar(entrants, care, metric, tasks, datasets, imputation, splits):
        make_selection_bar(
            entrants=entrants,
            care=care,
            metric=metric,
            tasks=tasks,
            datasets=datasets,
            imputation=imputation,
            splits=splits,
        )

    @gr.render(inputs=[entrants_state])
    def _render_systems_warnings(entrants):
        selected = entrants_categories(entrants)
        for key, text in (
            ("open", website_texts.WARNING_SYSTEMS),
            ("llm", website_texts.WARNING_WITH_LLM),
            ("api", website_texts.WARNING_CLOSED_API),
        ):
            if key in selected:
                gr.Markdown(text, elem_classes="ta-warnbox", container=False)


def render_internal_page(page: LeaderboardPage) -> None:
    # Corner jump menu, pinned like the COI badge (see website_texts.TOC_HTML).
    gr.HTML(website_texts.TOC_HTML)
    make_hero_stats(page.data_root)
    _render_info_boxes()

    entrants_state = gr.State("models")
    care_state = gr.State("quality")
    metric_state = gr.State("elo")
    impute_state = gr.State("yes")
    splits_state = gr.State("all")
    tasks_state = gr.State("all")
    datasets_state = gr.State("all")

    _render_control_band(
        page.data_root,
        entrants_state,
        care_state,
        metric_state,
        impute_state,
        splits_state,
        tasks_state,
        datasets_state,
    )

    # -- Cross-subset overview (the at-a-glance summary across all subsets)
    gr.HTML(
        '<div class="ta-section-head" id="ta-overview-section">'
        "<h2>🔭 Performance across leaderboards</h2>"
        '<p class="ta-section-sub">Every method variant across every task and dataset-size subset. '
        "The quickest way to spot the ones that are strong everywhere against those that shine on "
        "one subset, and to see what tuning buys. <i>One per model</i> collapses each method to its "
        "best variant.</p>"
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
        # Lives here rather than in the control card because it only decides which rows this one
        # table has. Same collapse the win-rate matrix offers and named the same, so the two read
        # as one control. Off by default: how much tuning buys a model is one of the things this
        # table is for.
        overview_one_per_model = gr.Checkbox(
            value=False,
            label="One per model",
            container=False,
            scale=0,
            min_width=180,
            elem_classes=["ta-catchip"],
        )
    overview_metric.change(
        lambda m: OVERVIEW_METRIC_TLDR.get(m, ""), overview_metric, metric_tldr, api_visibility="private"
    )

    # The overview follows the selectors too: the column each one points at leads its group and
    # is tinted, so the reader's own view is where their eye already is.
    @gr.render(
        inputs=[
            overview_metric,
            entrants_state,
            tasks_state,
            datasets_state,
            care_state,
            overview_one_per_model,
        ]
    )
    def _render_overview(metric, entrants, tasks, datasets, care, one_per_model):
        make_cross_subset_overview(
            page.data_root,
            metric,
            entrants=entrants,
            tasks=tasks,
            datasets=datasets,
            care=care,
            one_per_model=one_per_model,
        )

    # The "I care about" metric drives the overview's own selector, so the two cannot disagree
    # about which number the page is leading with.
    metric_state.change(
        lambda m: gr.update(value=METRIC_TO_OVERVIEW.get(m, "Elo")),
        metric_state,
        overview_metric,
        api_visibility="private",
    )

    # -- Leaderboards
    gr.HTML(
        '<div class="ta-section-head" id="lb-detailed">'
        "<h2>🏆 TabArena Leaderboard</h2>"
        '<p class="ta-section-sub">The full picture for the leaderboard selected above: how tuning '
        "moves each method, the accuracy-versus-time trade-off, and the complete table.</p>"
        "</div>"
    )

    @gr.render(
        inputs=[
            entrants_state,
            care_state,
            metric_state,
            impute_state,
            splits_state,
            tasks_state,
            datasets_state,
        ]
    )
    def _render_subset(ent, care, metric, imp, spl, tsk, dst):
        subset = Subset(entrants=ent, imputation=imp, splits=spl, tasks=tsk, datasets=dst)
        lb = LBContainer(data_root=page.data_root, subset=subset, name=subset_name(subset))
        gr.Markdown(subset_blurb(subset, lb.n_datasets), elem_classes="markdown-text")
        # What is below and in what order, since "I care about" reorders it.
        make_figure_contents(lb, care=care, metric=metric)
        make_overview_images(lb, care=care, metric=metric)
        # The win-rate matrix belongs with the figures above it; the table closes the section as
        # its detailed reference, collapsed because that is what a reference is for.
        make_winrate_image(lb)

    @gr.render(
        inputs=[
            entrants_state,
            care_state,
            metric_state,
            impute_state,
            splits_state,
            tasks_state,
            datasets_state,
        ]
    )
    def _render_leaderboard_table(ent, care, metric, imp, spl, tsk, dst):
        subset = Subset(entrants=ent, imputation=imp, splits=spl, tasks=tsk, datasets=dst)
        lb = LBContainer(data_root=page.data_root, subset=subset, name=subset_name(subset))
        make_leaderboard(lb, collapsible=True)

    # -- Per-dataset results
    gr.HTML(
        '<div class="ta-section-head" id="ta-perdataset-section">'
        "<h2>🔎 Per-dataset results</h2>"
        f'<p class="ta-section-sub">{website_texts.PER_DATASET_TEASER}</p>'
        "</div>"
    )

    # Its own render block so that opening it does not rebuild every figure above, and so its
    # artifact — the largest the site ships, since it carries every dataset's results — is only
    # embedded once the reader asks for it.
    per_dataset_open = gr.State(False)

    @gr.render(inputs=[per_dataset_open, entrants_state, impute_state, splits_state, tasks_state, datasets_state])
    def _render_per_dataset(opened, ent, imp, spl, tsk, dst):
        subset = Subset(entrants=ent, imputation=imp, splits=spl, tasks=tsk, datasets=dst)
        lb = LBContainer(data_root=page.data_root, subset=subset, name=subset_name(subset))
        toggle = make_per_dataset_block(lb, opened=opened)
        toggle.click(lambda now: not now, per_dataset_open, per_dataset_open, api_visibility="private")

    # -- Appendix: the two reference blocks that are about the site rather than the results.
    gr.HTML(
        '<div class="ta-section-head" id="ta-appendix-section">'
        "<h2>📎 Appendix</h2>"
        '<p class="ta-section-sub">How to reach these numbers from an agent, how to read them '
        "without over-claiming, and what changed in each release.</p>"
        "</div>"
    )

    gr.HTML('<div id="ta-agentic-section"></div>')
    with gr.Accordion("⚙️ Agentic Use & Interpretation", open=False):
        make_agentic_guide()

    gr.HTML('<div id="ta-version-section"></div>')
    with gr.Accordion("📂 Version History", open=False):
        gr.Markdown(website_texts.VERSION_HISTORY_BUTTON_TEXT, elem_classes="markdown-text")


# BeyondArena omits TabArena's "systems" topic (its own copy folds any system into the
# metrics/models topics).
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
        "subset. The quickest way to see which methods hold up beyond the IID assumption.</p>"
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
        '<p class="ta-section-sub">Pick a subset below: a split regime, dataset-size bucket, or '
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
        "stay fully owned and maintained by its authors, with us reviewing it, endorsing its methodology "
        "and crediting the team. Or we can maintain it together, and you are welcome to reuse TabArena's code "
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
