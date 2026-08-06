from __future__ import annotations

import gradio as gr

from api import register_api
from pages import PAGES, render_page
from website_texts import COI_HTML, TITLE

CSS = """
/* Use the full page width instead of gradio's narrow centered column. */
.gradio-container { max-width: 100% !important; }

/* --- Colour emoji ----------------------------------------------------------
   Gradio's own font stack ends "… "Noto Sans", sans-serif, "Apple Color Emoji",
   "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji"" — the colour emoji
   fonts sit *after* the generic `sans-serif`, which matches everything, so the
   browser never reaches them and resolves emoji through its own fallback
   instead. On Linux that commonly lands on the monochrome Noto Emoji, which is
   why 🧠⚡ / 🤖 / 🥇 render flat there and in colour on macOS and Windows.
   Same stack in Gradio 5, so this is long-standing rather than new.
   Naming the colour fonts before the generic fixes it for every emoji on the
   page; Latin glyphs are unaffected because those fonts carry none.

   Overriding the two variables rather than `font-family` directly is what makes
   it stick for Gradio's components: its own rules set `font-family: var(--font)` /
   `var(--font-sans)` on individual elements, which would beat a container-level
   declaration. Raw HTML (`gr.HTML`) has no such rule and is handled by the
   element-level block below. */
:root, .gradio-container, html body {
    --font: "IBM Plex Sans", ui-sans-serif, system-ui, -apple-system,
        "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans",
        "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif;
    --font-sans: var(--font);
    font-family: var(--font);
}

/* A colour-emoji family restricted to emoji codepoints.

   The emoji fonts have to lead the stack below to win over the browser's own
   fallback, but they must not serve anything else: Noto Color Emoji carries a
   SPACE glyph 1.25 em wide (2550/2048 units, i.e. emoji-width, against ~0.2 em
   in a text font), so leading with the raw family names stretched every gap
   between words wherever that font is installed — Latin letters fell through to
   IBM Plex Sans, but U+0020 did not, because the emoji font *does* have it.
   Binding the fonts through `unicode-range` keeps them first for emoji while
   spaces and Latin resolve from the text font. */
@font-face {
    font-family: "TA Color Emoji";
    src: local("Apple Color Emoji"), local("Segoe UI Emoji"),
        local("Noto Color Emoji"), local("Twemoji Mozilla");
    unicode-range: U+00A9, U+00AE, U+203C, U+2049, U+2122, U+2139, U+2194-21AA,
        U+231A-231B, U+2328, U+23CF, U+23E9-23FA, U+24C2, U+25AA-25FE,
        U+2600-27BF, U+2934-2935, U+2B00-2BFF, U+3030, U+303D, U+3297, U+3299,
        U+200D, U+20E3, U+FE0E-FE0F, U+1F000-1FAFF, U+E0020-E007F;
}

/* Overriding the variables above fixes Gradio's own components (buttons, tabs),
   which resolve `font-family: var(--font)` per element. It does not reach content
   inside `gr.HTML`, which has no per-element rule of its own — so the elements we
   write by hand are listed here and get the colour fonts forced.

   The emoji family leads and `!important` settles the cascade; every other
   character, space included, resolves from IBM Plex Sans because the family
   above answers only for emoji codepoints. Add a selector here if an emoji
   shows up flat somewhere new. */
.ta-card-ico,
.ta-path-ico,
.ta-pill,
.ta-lb-title,
.ta-figbar-title,
.ta-section-head h2,
.ta-jump,
.ta-viewbtn,
.coi-badge,
.ta-legend,
.ta-lbtable td.ta-type-cell,
.ta-verified,
.ta-link-icon,
.ta-cap,
.coi-cta,
.markdown-text h1, .markdown-text h2, .markdown-text h3, .markdown-text h4 {
    font-family: "TA Color Emoji", "IBM Plex Sans", ui-sans-serif, system-ui,
        "Segoe UI", Roboto, sans-serif !important;
}

/* Gradio 6 pads every anchor inside a gr.HTML / gr.Markdown block:

       .gradio-container-6-22-0 .gradio-style a { padding: 2px 8px; text-align: center }

   That is a link-button style, and it lands on inline links too, which is where the
   gaps around "(see paper)" / "(see code)" in the hero cards came from. Reset for
   the links we write as running text — they are the ones with no class of their own
   — at a specificity that beats Gradio's two-class selector whatever the stylesheet
   order turns out to be. The pill-shaped links keep their own padding (below, where
   the same Gradio rule is why they have to say `!important`). */
.gradio-container .gradio-style a:not([class]) { padding: 0; }

.markdown-text-box {
    padding: 4px;
    border-radius: 2px;
}

/* Intro tagline as a full-width card inside the hero group, above the stat boxes.
   Tinted with the app accent (blue) so it stands out from the neutral stat cards. */
.ta-intro {
    flex: 1 1 100%;
    padding: 11px 16px;
    border: 1px solid rgba(110, 140, 245, 0.5);
    border-radius: 10px;
    background: linear-gradient(135deg, rgba(110, 140, 245, 0.22), rgba(110, 140, 245, 0.07));
    text-align: center;
    font-size: 1.05em;
    font-weight: 600;
    line-height: 1.4;
    color: #e6ebff;
}

/* --- Subset filter rows ----------------------------------------------------
   The two content axes (task, dataset size) and the two view modifiers are one
   control cluster, so they are drawn as three rows of the same panel: same frame,
   same height, and a small uppercase label on the left saying which axis the row
   switches. Before this the tab bars were bare text above a bordered toggle box,
   which read as two unrelated controls.

   Gradio 6 renders a Tabs as .tabs > .tab-wrapper > .tab-container > button and
   marks the active tab .selected, styling it with a 2px underline. Here the row
   frame lives on .tab-wrapper and the choices are flat chips with the active one
   filled. Note .tab-wrapper holds a *second*, visually hidden .tab-container that
   Gradio measures to decide which tabs go into its overflow menu, which is why the
   chip rules deliberately hit every .tab-container: styling only the visible copy
   would make it mis-measure. */
.tab-buttons {
    gap: 0 !important;
    /* Cancel the column gap the surrounding Blocks layout adds between the rows,
       then set the row spacing here. */
    margin: 0 0 calc(5px - var(--layout-gap)) !important;
}
.tab-buttons .tab-wrapper {
    height: auto;
    align-items: center;
    margin-bottom: 0;
    padding: 5px 12px 5px 14px;
    background: #ffffff0a;
    border: 1px solid #ffffff26;
    border-radius: 10px;
}
/* The rule Gradio draws under a tab bar; the row frame replaces it. */
.tab-buttons .tab-container::after { display: none; }
.tab-buttons .tab-container { gap: 3px; height: auto; }
.tab-buttons .tab-container > button {
    /* One neutral slate, and how strongly a chip is tinted says how deep in the axis
       it sits: the row's "all" chip is the whole set, the next level is a subset of
       it, and the lightest chips are subsets of a subset. Peers share a step, so
       nothing in the row reads as ranked above anything else — Small and Medium are
       the same tint, and so are Binary and Multiclass. Selection is the one place a
       colour changes hue, and it is the app accent, the same as everywhere else. */
    --depth: 0.62;
    height: auto;
    padding: 5px 12px;
    font-size: 0.86em;
    font-weight: 600;
    color: #cbd5ef;
    background: rgba(158, 176, 208, calc(0.3 * var(--depth)));
    border: none;
    border-radius: 8px;
    transition: background .14s ease, color .14s ease;
}
.tab-buttons .tab-container > button:hover:not(.selected) {
    background: rgba(158, 176, 208, calc(0.62 * var(--depth)));
    color: #ffffff;
}
.tab-buttons .tab-container > button.selected {
    color: #ffffff;
    background: rgba(110, 140, 245, 0.92);
    box-shadow: 0 1px 3px #0000005c;
}

/* The depth steps. Gradio gives the tabs no per-tab class, so they are addressed by
   position — the nth-child order is the insertion order of TASK_LABELS /
   DATASET_LABELS: all, classification, regression, binary, multiclass and all,
   small, medium. Chips 4 and 5 of the task row are the two classification
   flavours, one level further in than Classification itself. */
.axis-tasks .tab-container > button:nth-child(1),
.axis-datasets .tab-container > button:nth-child(1) { --depth: 1; }
.axis-tasks .tab-container > button:nth-child(n+4) { --depth: 0.34; }

/* The filled chip is the selection cue; Gradio's underline would sit inside it. */
.tab-buttons .tab-container > button.selected::after { display: none; }

/* The row labels: one style, one width, so the three rows line up on the left. */
.axis-tasks .tab-wrapper::before,
.axis-datasets .tab-wrapper::before,
.view-toggles::before {
    flex: 0 0 auto;
    min-width: 74px;
    font-size: 0.68em;
    font-weight: 700;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    opacity: 0.5;
    white-space: nowrap;
    align-self: center;
}
.axis-tasks .tab-wrapper::before { content: "Task"; }
.axis-datasets .tab-wrapper::before { content: "Datasets"; }

/* Third row of the same panel: the view modifiers (imputation / Lite). */
.view-toggles {
    margin: 0 0 16px 0;
    padding: 7px 12px 7px 14px;
    gap: 14px;
    align-items: center;
    background: #ffffff0a;
    border: 1px solid #ffffff26;
    border-radius: 10px;
}
.view-toggles::before { content: "View"; }
.view-toggles label span {
    font-size: 0.86em !important;
}

/* --- Figure panel with an interactive / static view switch -----------------
   One card per figure: a header row (title + toggle) above two stacked views,
   exactly one of which is visible. Both are in the DOM so the toggle is
   instant; see main.taSwitchView and views._switchable_figure. */
.ta-figpanel {
    margin: 18px 0 22px 0;
    padding: 0;
    overflow: hidden;
    border: 1px solid #ffffff33;
    border-left: 3px solid rgba(110, 140, 245, 0.55);
    border-radius: 12px;
    background: #ffffff14;
    gap: 0 !important;
}
/* A titled header strip, full-bleed across the card: the earlier borderless
   version left the three figure blocks running into one another, so it was hard
   to see where one ended. The toggles sit right beside the title, where the eye
   already is — pushed to the far edge they read as decoration and get missed. */
.ta-figbar {
    display: flex;
    align-items: center;
    gap: 4px 12px;
    flex-wrap: wrap;
    margin: 0;
    padding: 10px 15px;
    background: #ffffff21;
    border-bottom: 1px solid #ffffff38;
    border-radius: 9px 9px 0 0;
}
.ta-figbar-title { font-weight: 650; font-size: 1.1em; letter-spacing: 0.01em; align-self: baseline; }
/* The subset qualifier: present, but it should not compete with the name. */
.ta-figbar-sub { font-size: 0.85em; opacity: 0.6; font-weight: 400; align-self: baseline; }
.ta-viewbtn {
    flex: 0 0 auto;
    cursor: pointer;
    /* Gradio's stylesheet gives every button but the last a 4px bottom margin,
       which under centre alignment lifts it 2px above its neighbours. */
    margin: 0 !important;
    padding: 5px 14px;
    font-size: 0.85em;
    font-weight: 600;
    color: #cdd7ff;
    background: rgba(110, 140, 245, 0.18);
    border: 1px solid rgba(110, 140, 245, 0.55);
    border-radius: 999px;
    transition: background .15s ease, border-color .15s ease;
}
.ta-viewbtn:hover { background: rgba(110, 140, 245, 0.34); border-color: rgba(110, 140, 245, 0.95); }
/* The way into the controls, so it carries more weight than its neighbours. */
.ta-editbtn {
    font-size: 0.95em;
    font-weight: 700;
    padding: 8px 18px;
    color: #ffffff;
    background: rgba(110, 140, 245, 0.9);
    border-color: rgba(110, 140, 245, 1);
}
.ta-editbtn:hover { background: rgba(130, 158, 255, 1); border-color: rgba(150, 175, 255, 1); }
/* The chart / image itself, inset from the card edge. */
.ta-figview { padding: 0 13px 13px 13px; }
/* Download controls: pinned to the right of the header and deliberately louder
   than the view toggles, since exporting the figure is what paper view is for. */
.ta-exportgroup { display: inline-flex; align-items: center; gap: 6px; margin-left: auto; }
.ta-exportgroup[hidden] { display: none !important; }
.ta-exportlabel { font-size: 0.82em; font-weight: 700; letter-spacing: 0.04em; color: #7ee0b8; }
.ta-exportbtn { color: #063; background: #7ee0b8; border-color: #7ee0b8; }
.ta-exportbtn:hover { background: #a6efcd; border-color: #a6efcd; }
.ta-hidden { display: none !important; }
/* The static figure spans the panel and rescales with it — Gradio's default
   image box would letterbox the very wide bar figures inside a fixed height. */
.ta-figpanel .image-container,
.ta-figpanel .image-frame { width: 100% !important; height: auto !important; max-height: none !important; }
.ta-figpanel .image-frame img {
    width: 100% !important;
    height: auto !important;
    max-height: none !important;
    object-fit: contain;
}

/* Row of external links/buttons (e.g. on a linked-leaderboard page).
   Rendered as real <a target="_blank"> anchors so they open in a new tab
   instead of navigating inside the embedded Hugging Face Space iframe. */
.link-row {
    display: flex;
    margin: 12px 0;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
}
.ta-link-btn {
    display: inline-block;
    padding: 10px 20px !important;
    border-radius: 8px;
    font-weight: 600;
    text-decoration: none;
    border: 1px solid transparent;
    transition: background .15s ease, border-color .15s ease;
}
.ta-link-btn.primary {
    background: rgba(110, 140, 245, 0.85);
    border-color: rgba(110, 140, 245, 1);
    color: #ffffff;
}
.ta-link-btn.primary:hover { background: rgba(110, 140, 245, 1); }
.ta-link-btn.secondary {
    background: #ffffff14;
    border-color: #ffffff3d;
    color: #e6ebff;
}
.ta-link-btn.secondary:hover { background: #ffffff24; border-color: #ffffff5c; }

/* Compact "Metric:" selector panel above the overview table. */
.metric-select {
    margin: -18px 0 0 0;
    padding: 6px 14px;
    gap: 12px;
    align-items: center;
    background: #ffffff0a;
    border: 1px solid #ffffff26;
    border-radius: 8px;
}
.metric-select::before {
    content: "📈 Aggregation:";
    font-size: 0.85em;
    font-weight: 600;
    opacity: 0.7;
    white-space: nowrap;
}
.metric-tldr { font-size: 0.85em; opacity: 0.75; font-style: italic; }
.metric-tldr p { margin: 0; }
/* Pull the overview (type legend + table) up tight under the aggregation box. */
.ta-overview-block { margin-top: -8px; }

/* "Jump to detailed results" pill link. */
.ta-jump {
    display: inline-block;
    margin: 0;
    font-size: 0.9em;
    padding: 4px 14px !important;
    border: 1px solid #ffffff2e;
    border-radius: 999px;
    text-decoration: none;
    opacity: 0.85;
}
.ta-jump:hover { opacity: 1; border-color: #ffffff5c; }

/* Section header: title (and optional jump link) on one row, summary directly below. */
.ta-section-head { margin: 10px 0 6px 0; }
.ta-section-head h2 { margin: 0; }
.ta-section-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
}
.ta-section-sub { margin: 3px 0 0 0; font-size: 0.95em; opacity: 0.8; line-height: 1.4; }

/* Info topic pills + the single reveal panel (replaces the stacked accordions). */
.info-pills {
    gap: 8px;
    flex-wrap: wrap;
    justify-content: center;
    margin: -6px 0 2px 0;
}
.info-pills button {
    border-radius: 999px !important;
    flex: 0 0 auto !important;
    font-weight: 600 !important;
    font-size: 1em !important;
    padding: 8px 20px !important;
    color: #cdd7ff !important;
    background: rgba(110, 140, 245, 0.18) !important;
    border: 1px solid rgba(110, 140, 245, 0.55) !important;
}
.info-pills button:hover {
    background: rgba(110, 140, 245, 0.32) !important;
    border-color: rgba(110, 140, 245, 0.9) !important;
}
.info-pills button.primary {
    background: rgba(110, 140, 245, 0.85) !important;
    border-color: rgba(110, 140, 245, 1) !important;
    color: #ffffff !important;
}
.info-panel {
    margin: 6px 0 12px 0;
    padding: 4px 18px;
    border: 1px solid #ffffff1f;
    border-radius: 12px;
    background: #ffffff08;
}

/* --- The full leaderboard table, as one card -------------------------------
   Title strip, then the filters, then the column key, then the table itself.
   The controls and the key used to sit outside the table (the key in its own
   floating panel, the filters inside the old third-party widget); keeping them
   in the same bordered card is what makes them read as belonging to it. */
.ta-lb {
    margin: 16px 0 10px 0;
    padding: 0;
    overflow: visible;
    border: 1px solid #ffffff33;
    border-left: 3px solid rgba(110, 140, 245, 0.55);
    border-radius: 12px;
    background: #ffffff10;
    gap: 0 !important;
}
.ta-lb-bar {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 3px 12px;
    padding: 11px 16px;
    background: #ffffff21;
    border-bottom: 1px solid #ffffff38;
    border-radius: 9px 9px 0 0;
}
.ta-lb-title { font-weight: 650; font-size: 1.25em; letter-spacing: 0.01em; }
.ta-lb-sub { font-size: 0.85em; opacity: 0.6; }
/* One padded band for the filters, so four controls fit on a line without
   looking cramped. Nothing here may set pointer-events, position or z-index:
   these are live Gradio inputs and must stay clickable. */
.ta-lb-controls {
    padding: 12px 16px 2px 16px;
    gap: 18px;
    align-items: flex-start;
}
.ta-lb .ta-lb-imputed { padding: 0 16px 6px 16px; }
.ta-lb .ta-legend { padding: 4px 16px 0 16px; }
.ta-lb .ta-scroll { margin: 4px 16px 0 16px; max-height: 720px; }
.ta-lb .ta-cap { padding: 0 16px 10px 16px; }

/* --- Chip selectors, matching the plot explorers' edit view ------------------
   The same shape, dot and pressed treatment as the method chips in the generated
   *_explorer.html: a pill with a family-colored dot, no fill until selected, then
   a tinted background and a matching border. Variables are the explorers' own
   dark-theme values (the site forces dark).

   These are real Gradio inputs underneath. The native box is visually hidden but
   left in the layout and in the label, so a click on the chip still reaches it;
   nothing here sets pointer-events, position or z-index on anything clickable.
   Both `:has(input:checked)` and Gradio's own `.selected` drive the pressed look,
   so a change to either survives. */
.ta-chips, .ta-btns, .ta-famchip {
    --line: #2e2e33;
    --muted: #9b9a92;
    --pt-muted: #55555c;
    --chip-bg: #232327;
    --fam: #9b9a92;
}
.ta-btns-imputed { --fam: #e6c14d; }
.ta-chips label {
    display: inline-flex !important;
    align-items: center;
    gap: 6px;
    /* Spacing lives on the chips themselves rather than as a gap on Gradio's
       internal container, so this does not depend on Gradio's DOM. */
    margin: 0 5px 5px 0 !important;
    padding: 5px 11px 5px 9px !important;
    font: 500 12.5px/1 system-ui, sans-serif !important;
    color: #f0efea;
    background: none !important;
    border: 1px solid var(--line) !important;
    border-radius: 999px !important;
    box-shadow: none !important;
    cursor: pointer;
    transition: border-color 120ms ease, background-color 120ms ease;
}
.ta-chips label::before {
    content: "";
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--pt-muted);
    flex: none;
}
.ta-chips label:hover { border-color: var(--muted) !important; }
.ta-chips label:has(input:checked),
.ta-chips label.selected {
    border-color: var(--fam) !important;
    background: color-mix(in srgb, var(--fam) 13%, transparent) !important;
    font-weight: 650 !important;
}
.ta-chips label:has(input:checked)::before,
.ta-chips label.selected::before { background: var(--fam); }
/* Visually hidden, still hit-testable through its label. */
.ta-chips label input[type="checkbox"],
.ta-chips label input[type="radio"] {
    width: 0 !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    opacity: 0;
    flex: none;
}
/* The chip rows carry their own label above; keep Gradio's block label small. */
.ta-chips > .block-label, .ta-chips span[data-testid="block-info"] { font-size: 0.85em; }

/* The family chip that heads each row of model chips: the explorers' .famchip —
   uppercase, dashed until selected, then solid in the family's colour. */
.ta-famchip label {
    display: inline-flex !important;
    align-items: center;
    gap: 6px;
    margin: 0 !important;
    padding: 5px 11px !important;
    font: 650 10.5px/1.3 system-ui, sans-serif !important;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted);
    background: var(--chip-bg) !important;
    border: 1px dashed var(--line) !important;
    border-radius: 999px !important;
    box-shadow: none !important;
    cursor: pointer;
    white-space: nowrap;
}
.ta-famchip label::before {
    content: "";
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--fam);
    flex: none;
}
.ta-famchip label:hover { border-color: var(--fam) !important; color: #f0efea; }
.ta-famchip label:has(input:checked),
.ta-famchip label.selected {
    border: 1px solid var(--fam) !important;
    background: color-mix(in srgb, var(--fam) 13%, transparent) !important;
    color: #f0efea;
}
.ta-famchip label input { width: 0 !important; height: 0 !important; margin: 0 !important; opacity: 0; }
/* Family chip left, its models filling the rest of the row. */
.ta-chiprow { gap: 10px; align-items: flex-start; margin: 0 !important; padding: 0 16px; }

/* --- Button-style toggles, as in the Leaderboard Overview explorer -----------
   That explorer uses buttons rather than chips for the variants ("since they
   filter the series rather than the rows"), each carrying its variant colour from
   --var-*; see constants.variant_color. Same shape here. */
.ta-btns label {
    display: inline-flex !important;
    align-items: center;
    margin: 0 5px 5px 0 !important;
    padding: 6px 11px !important;
    font: 600 12.5px/1 system-ui, sans-serif !important;
    color: #f0efea;
    background: var(--chip-bg) !important;
    border: 1px solid var(--line) !important;
    border-radius: 7px !important;
    box-shadow: none !important;
    cursor: pointer;
    white-space: nowrap;
    transition: border-color 120ms ease, background-color 120ms ease;
}
.ta-btns label:hover { border-color: var(--muted) !important; }
.ta-btns label:has(input:checked),
.ta-btns label.selected {
    border-color: var(--fam) !important;
    background: color-mix(in srgb, var(--fam) 20%, #232327) !important;
}
.ta-btns label input { width: 0 !important; height: 0 !important; margin: 0 !important; opacity: 0; }

/* The CSV export button sits at the right end of the card's title strip. */
.ta-csvbtn { margin-left: auto !important; }

/* Sortable headers. The overview's info headers use a help cursor; here the same
   header is also the sort control, so pointer wins and the dotted underline is
   what still signals "hover me for a definition". */
.ta-lbtable thead th.ta-th-sort { cursor: pointer; user-select: none; white-space: nowrap; }
.ta-lbtable thead th.ta-th-sort:hover { background: #262632; }
.ta-lbtable thead th.ta-th-sort::after {
    content: "↕";
    font-size: 0.72em;
    opacity: 0.28;
    margin-left: 5px;
}
.ta-lbtable thead th[aria-sort="ascending"]::after { content: "▲"; opacity: 0.85; }
.ta-lbtable thead th[aria-sort="descending"]::after { content: "▼"; opacity: 0.85; }
.ta-lbtable th.ta-th-left { text-align: left; }
/* Two-emoji type symbols (🧠⚡, 🧠🔁) must never break across lines, in the table
   cell or in the legend chip that explains it. */
.ta-pill { white-space: nowrap; }
.ta-lbtable td.ta-type-cell { white-space: nowrap; width: 1%; }
/* The Elo interval rides along with the value but stays visibly secondary. */
.ta-ci { opacity: 0.5; font-weight: 400; font-size: 0.82em; }
.ta-ci-head { opacity: 0.55; font-weight: 400; font-size: 0.82em; }

/* Hero stat cards shown above the info boxes (emoji on the left of the text, compact). */
.ta-hero {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin: -8px 0 0 0;
}
.ta-hero .ta-card {
    flex: 1 1 210px;
    min-width: 210px;
    display: flex;
    align-items: center;
    gap: 11px;
    padding: 9px 13px;
    border: 1px solid #ffffff1f;
    border-radius: 10px;
    background: linear-gradient(135deg, #ffffff12, #ffffff05);
    text-align: left;
    transition: transform .15s ease, border-color .15s ease;
}
.ta-hero .ta-card:hover {
    transform: translateY(-2px);
    border-color: #ffffff40;
}
.ta-hero .ta-card-ico { font-size: 1.5em; line-height: 1; flex: 0 0 auto; }
.ta-hero .ta-card-body { min-width: 0; }
.ta-hero .ta-card-num { font-size: 1.1em; font-weight: 700; line-height: 1.2; }
.ta-hero .ta-card-lbl { font-size: 0.8em; opacity: 0.75; margin-top: 1px; line-height: 1.3; }
.ta-hero .ta-card-lbl a { color: inherit; }

/* "Your Benchmark?" invite page: two "path" cards side by side. */
.ta-paths {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    margin: 18px 0 6px 0;
}
.ta-path {
    flex: 1 1 320px;
    min-width: 280px;
    padding: 18px 22px;
    border: 1px solid rgba(110, 140, 245, 0.45);
    border-radius: 12px;
    background: linear-gradient(135deg, rgba(110, 140, 245, 0.16), rgba(110, 140, 245, 0.04));
    transition: transform .15s ease, border-color .15s ease;
}
.ta-path:hover { transform: translateY(-2px); border-color: rgba(110, 140, 245, 0.85); }
.ta-path-ico { font-size: 1.9em; line-height: 1; }
.ta-path h3 { margin: 8px 0 8px 0; font-size: 1.18em; }
.ta-path p { margin: 0; opacity: 0.88; line-height: 1.55; }

/* Soft "independent benchmarks" note on the invite page (mirrors the RamanBench callout). */
.ta-invite-note {
    margin: 14px 0 4px 0;
    padding: 11px 16px;
    border: 1px solid rgba(110, 140, 245, 0.4);
    border-left: 4px solid rgba(110, 140, 245, 0.85);
    border-radius: 8px;
    background: rgba(110, 140, 245, 0.08);
    font-size: 0.95em;
    line-height: 1.5;
    opacity: 0.95;
}

/* --- Conflict-of-interest corner hint + CSS-only popup ---------------------
   A small pill pinned to the top-right corner; clicking it reveals a modal.
   Built with the checkbox hack so it needs no JS and works inside the embedded
   Hugging Face Space iframe. */
.coi-toggle { position: absolute; opacity: 0; width: 0; height: 0; pointer-events: none; }
.coi-badge {
    position: fixed;
    top: 10px;
    right: 14px;
    z-index: 1000;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    padding: 6px 13px;
    font-size: 0.85em;
    font-weight: 600;
    color: #cdd7ff;
    background: rgba(110, 140, 245, 0.2);
    border: 1px solid rgba(110, 140, 245, 0.6);
    border-radius: 999px;
    user-select: none;
    transition: background .15s ease, border-color .15s ease;
}
.coi-badge:hover { background: rgba(110, 140, 245, 0.34); border-color: rgba(110, 140, 245, 0.95); }

.coi-overlay {
    display: none;
    position: fixed;
    inset: 0;
    z-index: 1001;
    align-items: flex-start;
    justify-content: center;
    padding: 32px 20px;
    overflow-y: auto;
    background: rgba(0, 0, 0, 0.66);
}
.coi-toggle:checked ~ .coi-overlay { display: flex; }
.coi-backdrop { position: absolute; inset: 0; cursor: default; }

.coi-modal {
    position: relative;
    width: 100%;
    max-width: min(1040px, 94vw);
    margin: 0 auto;
    /* Fixed base font (in rem) so the popup does not inherit Gradio's smaller
       in-app font; all sizes below scale from this. */
    font-size: 1.06rem;
    padding: 34px 44px 38px;
    border-radius: 16px;
    background: #1b1b24;
    border: 1px solid rgba(110, 140, 245, 0.45);
    box-shadow: 0 18px 55px rgba(0, 0, 0, 0.55);
    color: #eef1ff;
    line-height: 1.7;
}
.coi-modal h2 { margin: 0 0 6px 0; font-size: 1.85em; line-height: 1.25; }
.coi-modal h3 { margin: 26px 0 8px 0; font-size: 1.28em; color: #cdd7ff; }
.coi-modal p, .coi-modal li { font-size: 1em; opacity: 0.96; }
.coi-modal ul { margin: 8px 0; padding-left: 24px; }
.coi-modal li { margin: 7px 0; }
.coi-modal a { color: #9db4ff; }
.coi-lead { font-size: 1.18em !important; opacity: 1 !important; line-height: 1.55; }
.coi-tldr {
    margin: 16px 0 4px 0;
    padding: 16px 20px;
    border: 1px solid rgba(110, 140, 245, 0.4);
    border-left: 4px solid rgba(110, 140, 245, 0.85);
    border-radius: 8px;
    background: rgba(110, 140, 245, 0.1);
    font-size: 1.05em;
    line-height: 1.6;
}
.coi-x {
    position: absolute;
    top: 14px;
    right: 20px;
    font-size: 2em;
    line-height: 1;
    cursor: pointer;
    opacity: 0.55;
    user-select: none;
}
.coi-x:hover { opacity: 1; }
.coi-cta {
    display: block;
    width: fit-content;
    margin: 28px auto 0;
    text-align: center;
    padding: 12px 24px !important;
    border-radius: 8px;
    font-weight: 600;
    font-size: 1.02em;
    text-decoration: none;
    color: #ffffff !important;
    background: rgba(110, 140, 245, 0.85);
    border: 1px solid rgba(110, 140, 245, 1);
}
.coi-cta:hover { background: rgba(110, 140, 245, 1); }

/* On wider screens, give the prose a touch more size still. */
@media (min-width: 900px) {
    .coi-modal { font-size: 1.12rem; }
}

/* BeyondArena "What do the subsets mean?" expander: larger label + blue highlight box. */
.beyond-subsets-accordion {
    border: 1px solid #5aa9e6 !important;
    border-radius: 10px !important;
    background: rgba(90, 169, 230, 0.08) !important;
}
.beyond-subsets-accordion .label-wrap,
.beyond-subsets-accordion .label-wrap span,
.beyond-subsets-accordion > button {
    font-size: 1.15rem !important;
    font-weight: 600 !important;
    color: #8cc4f0 !important;
}
"""

# Gradio 6 ships this inside `window.gradio_config` and the client appends it to
# <head> once the config is read — early, but *after* the bundle has picked a
# theme, which is why the block below overrides that choice rather than pre-empting
# it. (`THEME` in main() handles the frame before the bundle runs.)
HEAD = """
<style>
/* --- Dark, and only dark ---------------------------------------------------
   The site has one theme: every colour in `CSS` above is a dark-theme value and
   the figures in `data/` are exported for a dark background, so a light render
   is broken rather than an alternative. `color-scheme` puts the browser's own
   furniture — scrollbars, form controls, the canvas behind an over-scroll — on
   the same side; the script below does the rest. */
:root { color-scheme: dark; }
html, body, gradio-app { background: #0f0f11; }
</style>
<script>
/* --- Dark, and only dark (see the <style> above) ---------------------------
   Gradio 6 picks the theme in this order: the `theme-mode` attribute on
   `<gradio-app>`, then the `__theme` query parameter, then `system` — which
   follows the viewer's OS `prefers-color-scheme` and keeps a `matchMedia`
   listener around to re-apply itself on every change. Setting `__theme=dark`
   therefore only wins for a viewer who has neither of the other two against
   them, which is how Hugging Face visitors on a light OS, or in a light-mode
   embed, still landed in white mode. Reloading the page to append the
   parameter (what this used to do) does not help: it loses the same race
   again, one full page load later.

   So don't negotiate with the theme picker — outlast it. Gradio's stylesheet
   keys the whole dark palette off `:root.dark, :root .dark`, so adding the
   class is enough on its own, and holding it is enough to survive the OS-theme
   listener. Deliberately nothing else: the `theme-mode` attribute is a live
   Svelte prop on the `<gradio-app>` custom element, so writing it re-enters the
   boot it is meant to correct, and rewriting the URL moves ground the app is
   standing on. A class is inert. */
(function () {
    const DARK = "dark";
    const observer = new MutationObserver(paint);

    function hold(el) {
        if (!el) return;
        // Test before adding. `classList.add` re-serializes and re-sets the
        // attribute whether or not the class is already there, and *that* queues
        // a mutation record — so an unguarded add feeds this very observer and
        // spins forever, freezing the page on Gradio's loading state.
        if (!el.classList.contains(DARK)) el.classList.add(DARK);
        // Same element, same options: re-observing replaces the registration
        // rather than stacking another one.
        observer.observe(el, { attributes: true, attributeFilter: ["class"] });
    }

    function paint() {
        hold(document.documentElement);
        hold(document.body);
        // Embedded, Gradio marks the *parent* of <gradio-app> rather than
        // <body> (`is_embed` in its bundle); holding both covers either mount.
        for (const app of document.getElementsByTagName("gradio-app")) {
            hold(app);
            hold(app.parentElement);
        }
    }
    // These few elements are the only ones Gradio ever marks, so watch them by
    // name rather than subtree-watching a document this large.
    paint();
    document.addEventListener("DOMContentLoaded", paint);
    window.addEventListener("load", paint);
})();
</script>
<script>
/* --- One decimal separator, everywhere ------------------------------------
   Every number the site publishes uses a "." decimal separator and no
   thousands grouping: the figures are rendered in Python, the CSVs are written
   that way, and the interactive plots format with `toFixed`. Anything routed
   through `toLocaleString` / `Intl.NumberFormat` would instead follow the
   *viewer's* browser locale — a visitor in Germany would read "0,886" for a
   score of 0.886, disagreeing with the figure beside it. Pin those two to
   en-US, and default grouping off so the pin cannot introduce "1,765" either.
   Number formatting only: dates are untouched, and an explicit locale or an
   explicit `useGrouping` from the caller still wins. */
(function () {
    const US = "en-US";
    // Only fill in defaults when the caller asked for none — code that names a
    // locale explicitly means it, and is left alone.
    const pinned = (locales, options) =>
        locales === undefined ? [US, { useGrouping: false, ...(options || {}) }] : [locales, options];
    for (const proto of [Number.prototype, typeof BigInt !== "undefined" ? BigInt.prototype : null]) {
        if (!proto) continue;
        const original = proto.toLocaleString;
        proto.toLocaleString = function (locales, options) {
            return original.apply(this, pinned(locales, options));
        };
    }
    const NumberFormat = Intl.NumberFormat;
    function PinnedNumberFormat(locales, options) {
        return new NumberFormat(...pinned(locales, options));
    }
    PinnedNumberFormat.prototype = NumberFormat.prototype;
    PinnedNumberFormat.supportedLocalesOf = NumberFormat.supportedLocalesOf.bind(NumberFormat);
    Intl.NumberFormat = PinnedNumberFormat;
})();

/* --- Figure panels: interactive <-> static view switch ---------------------
   Each panel renders both views and flips them here, so switching costs no
   server round trip. `uid` identifies the panel; `<uid>-i` / `<uid>-s` are the
   interactive and static wrappers and `<uid>-btn` the toggle
   (see views._switchable_figure). */
window.taSwitchView = function (uid) {
    const interactive = document.getElementById(uid + "-i");
    const staticView = document.getElementById(uid + "-s");
    const btn = document.getElementById(uid + "-btn");
    if (!interactive || !staticView || !btn) return;
    interactive.classList.toggle("ta-hidden");
    staticView.classList.toggle("ta-hidden");
    const showingStatic = !staticView.classList.contains("ta-hidden");
    btn.textContent = showingStatic ? "\\u26a1 Interactive view" : "\\u{1f5bc}\\ufe0f Static figure";
    btn.setAttribute("aria-pressed", String(showingStatic));
};

/* Paper view — white background, chart + legend only — is the state a panel
   *opens* in, since the figure is what a reader wants first. This flips to the
   editing view and back. The panel header owns the control; the frame is
   sandboxed and cross-origin, so the command travels over postMessage.
   `aria-pressed` on the button tracks whether paper view is on. */
window.taPaperView = function (uid) {
    const interactive = document.getElementById(uid + "-i");
    const staticView = document.getElementById(uid + "-s");
    const btn = document.getElementById(uid + "-paper");
    const frame = interactive && interactive.querySelector("iframe.ta-explorer");
    if (!frame || !btn) return;
    // It only applies to the interactive chart, so bring that one back first.
    if (staticView && !staticView.classList.contains("ta-hidden")) taSwitchView(uid);
    const on = btn.getAttribute("aria-pressed") !== "true";
    frame.contentWindow.postMessage({ type: "tabarena-explorer-paper", on: on }, "*");
    btn.setAttribute("aria-pressed", String(on));
    btn.textContent = on ? "\\u270f\\ufe0f Edit view" : "\\u{1f4c4} Paper view";
    const exportGroup = document.getElementById(uid + "-export");
    if (exportGroup) exportGroup.hidden = !on;
};

/* --- Leaderboard table sorting ---------------------------------------------
   Click a header to sort the rows beneath it; click again to reverse. Numeric
   columns are marked `data-type="num"` and every cell carries the raw value in
   `data-sort`, so the Elo column can print its confidence interval beside the
   number without that text taking part in the comparison. Missing values ("–")
   always sink to the bottom, whichever direction is active. Sorting is local to
   the browser: the server sends the rows in published order and re-sending them
   (when a filter changes) resets the sort. See views.leaderboard_table_html. */
window.taSortTable = function (th) {
    const table = th.closest("table");
    const body = table.tBodies[0];
    if (!body) return;
    const index = Array.prototype.indexOf.call(th.parentNode.children, th);
    const numeric = th.dataset.type === "num";
    const direction = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
    table.querySelectorAll("th[aria-sort]").forEach((other) => other.removeAttribute("aria-sort"));
    th.setAttribute("aria-sort", direction);
    const sign = direction === "ascending" ? 1 : -1;
    const keyOf = (row) => {
        const cell = row.children[index];
        if (!cell) return null;
        const raw = cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent.trim();
        if (raw === "" || raw === "–") return null;
        if (!numeric) return raw.toLowerCase();
        const value = parseFloat(raw);
        return isNaN(value) ? null : value;
    };
    const rows = Array.prototype.slice.call(body.rows);
    rows.sort((a, b) => {
        const ka = keyOf(a), kb = keyOf(b);
        if (ka === null || kb === null) return ka === kb ? 0 : ka === null ? 1 : -1;
        return ka < kb ? -sign : ka > kb ? sign : 0;
    });
    const fragment = document.createDocumentFragment();
    rows.forEach((row) => fragment.appendChild(row));
    body.appendChild(fragment);
};

/* Delegated so it keeps working after the server replaces the table's HTML. */
document.addEventListener("click", (ev) => {
    const th = ev.target.closest && ev.target.closest("table.ta-lbtable th.ta-th-sort");
    if (th) window.taSortTable(th);
});

/* --- Leaderboard CSV export -------------------------------------------------
   Exports what the reader is actually looking at: the rows the filters left, the
   columns they picked, in the order they sorted. Reading the rendered table is
   what buys that last part — the server does not know the browser's sort. Values
   come from `data-sort` where a cell has one (the raw unrounded number, and the
   family name rather than its emoji), and the Elo cell's interval is split back
   out into its own column. */
window.taExportTable = function (tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;
    const quote = (v) => '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"';
    const headers = [];
    table.querySelectorAll("thead th").forEach((th) => {
        const label = th.cloneNode(true);
        label.querySelectorAll(".ta-ci-head").forEach((n) => n.remove());
        headers.push(label.textContent.trim());
        if (th.dataset.col === "elo") headers.push("Elo 95% CI");
    });
    const lines = [headers.map(quote).join(",")];
    table.tBodies[0] && Array.prototype.forEach.call(table.tBodies[0].rows, (row) => {
        if (row.hidden) return;
        const values = [];
        Array.prototype.forEach.call(row.cells, (cell) => {
            if (cell.dataset.ci !== undefined) {
                values.push(cell.dataset.sort);
                values.push(cell.dataset.ci);
                return;
            }
            values.push(cell.dataset.sort !== undefined && cell.dataset.export !== "text"
                ? cell.dataset.sort
                : cell.textContent.trim());
        });
        lines.push(values.map(quote).join(","));
    });
    /* Escaped twice: this file's HEAD is a plain Python string, so a lone \n here
       would reach the browser as a real newline inside a JS string literal and
       break the whole script (as it once did). */
    const blob = new Blob([lines.join("\\n") + "\\n"], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = (table.dataset.name || tableId) + ".csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
};

/* The leaderboard table's CSV export. The button lives in the panel header, in
   the same row as the title, and the download itself happens inside the frame —
   only it knows the current filters, columns and sort order. Same channel as the
   figure exports below. */
window.taLeaderboardCsv = function (button) {
    const card = button.closest(".ta-lb");
    const frame = card && card.querySelector("iframe.ta-explorer");
    if (frame) frame.contentWindow.postMessage({ type: "tabarena-leaderboard-csv" }, "*");
};

/* Figure download, handed to the explorer over the same channel. */
window.taExport = function (uid, format) {
    const frame = document.querySelector("#" + uid + "-i iframe.ta-explorer");
    if (frame) frame.contentWindow.postMessage({ type: "tabarena-explorer-export", format: format }, "*");
};

/* The interactive explorer iframes (sandboxed srcdoc pages, see
   views._interactive_plot_iframe) post their content height; resize each frame
   to fit so it never shows an inner scrollbar. Height is clamped defensively —
   the frames are sandboxed, but the message is still external input. */
window.addEventListener("message", (ev) => {
    const d = ev.data;
    if (!d || d.type !== "tabarena-explorer-height" || typeof d.height !== "number") return;
    for (const frame of document.querySelectorAll("iframe.ta-explorer")) {
        if (frame.contentWindow === ev.source) {
            frame.style.height = Math.min(Math.max(Math.ceil(d.height), 300), 2600) + 8 + "px";
            break;
        }
    }
});
</script>
"""


# The one frame `HEAD` cannot reach. Gradio's served `index.html` paints a splash
# from the theme's *light* body colours and only swaps to the dark pair when the
# viewer's OS asks for dark — so a light-mode visitor got a white flash before the
# bundle (and the dark-forcing block in `HEAD`) had loaded at all. Point the light
# pair at the dark values and that first frame is dark for everyone. Nothing else
# reads them: the app always renders under `.dark`, which has its own pair.
#
# Written out rather than referenced: `set()` rejects a `*…_dark` value, since it
# normally resolves the dark half of a pair by itself. These two are what
# `gr.themes.Default()` resolves `body_background_fill_dark` / `body_text_color_dark`
# to (`neutral_950` / `neutral_100`); the background also appears in `HEAD`'s <style>.
THEME = gr.themes.Default().set(
    body_background_fill="#0f0f11",
    body_text_color="#f4f4f5",
)


def main() -> None:
    # Gradio 6 moved css / js / head from the Blocks constructor to launch(); passing
    # them here would be ignored with a warning, silently dropping every style on the
    # page. They are handed to launch() at the bottom of this function.
    with gr.Blocks(title="TabArena", fill_width=True) as website:
        gr.HTML(TITLE)
        # Conflict-of-interest corner hint (🔍 pill, top-right) + CSS-only popup.
        gr.HTML(COI_HTML)

        # Top-level navigation: one tab per leaderboard (current + future + links).
        with gr.Tabs(elem_id="top-tabs"):
            for page in PAGES:
                with gr.TabItem(page.name):
                    render_page(page)

        # The agent-facing endpoints (no UI). These are what HF's generated
        # agents.md points a coding agent at; see api.py.
        register_api()

    website.launch(
        css=CSS,
        head=HEAD,
        theme=THEME,
        show_error=True,
        ssr_mode=False,
        debug=True,
        # Serves the api.py endpoints as MCP tools at /gradio_api/mcp/, so an MCP
        # client can attach to the Space itself instead of driving the REST API.
        mcp_server=True,
    )


if __name__ == "__main__":
    main()
