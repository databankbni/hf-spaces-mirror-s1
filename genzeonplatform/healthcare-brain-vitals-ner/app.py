import gradio as gr
from transformers import pipeline

MODEL_ID = "genzeonplatform/healthcare-brain-vitals-ner"

_nlp = pipeline(
    "token-classification",
    model=MODEL_ID,
    aggregation_strategy="simple",
)

ENTITY_TYPES = [
    "BLOOD_PRESSURE",
    "HEART_RATE",
    "RESPIRATORY_RATE",
    "TEMPERATURE",
    "SPO2",
    "WEIGHT",
    "HEIGHT",
    "BMI",
    "PAIN_SCORE",
    "GCS",
    "BLOOD_GLUCOSE",
    "VITAL_DATE",
    "VITAL_TIME",
    "MEASUREMENT_UNIT",
    "MEASUREMENT_VALUE",
]

ENTITY_COLORS = {
    "BLOOD_PRESSURE": "#2563eb",       # blue
    "HEART_RATE": "#dc2626",           # red
    "RESPIRATORY_RATE": "#0891b2",     # cyan
    "TEMPERATURE": "#d97706",          # orange
    "SPO2": "#0d9488",                 # teal
    "WEIGHT": "#16a34a",              # green
    "HEIGHT": "#65a30d",              # lime
    "BMI": "#ca8a04",                 # amber
    "PAIN_SCORE": "#9333ea",          # purple
    "GCS": "#db2777",                 # pink
    "BLOOD_GLUCOSE": "#e11d48",       # rose
    "VITAL_DATE": "#475569",          # slate
    "VITAL_TIME": "#6b7280",          # gray
    "MEASUREMENT_UNIT": "#7c3aed",    # violet
    "MEASUREMENT_VALUE": "#059669",   # emerald
}


def _merge_entities(text: str, entities):
    """Post-merge adjacent same-group entity spans whose offsets touch."""
    if not entities:
        return entities
    merged = [dict(entities[0])]
    for ent in entities[1:]:
        prev = merged[-1]
        if (ent["entity_group"] == prev["entity_group"]
                and ent["start"] <= prev["end"]):
            prev["end"] = ent["end"]
            prev["word"] = text[prev["start"]:prev["end"]]
            prev["score"] = (prev["score"] + ent["score"]) / 2
        else:
            merged.append(dict(ent))
    return merged


def _entities_to_highlights(text: str, entities):
    """Convert merged entities to Gradio HighlightedText tuples."""
    out = []
    cursor = 0
    for ent in entities:
        start = ent["start"]
        end = ent["end"]
        group = ent["entity_group"]
        if start > cursor:
            out.append((None, text[cursor:start]))
        out.append((group, text[start:end]))
        cursor = end
    if cursor < len(text):
        out.append((None, text[cursor:]))
    return out


def extract_vital_entities(text: str):
    """Extract vital sign and measurement entities from clinical text.

    Recognizes 15 vital sign entity types — BLOOD_PRESSURE, HEART_RATE,
    RESPIRATORY_RATE, TEMPERATURE, SPO2, WEIGHT, HEIGHT, BMI, PAIN_SCORE,
    GCS, BLOOD_GLUCOSE, VITAL_DATE, VITAL_TIME, MEASUREMENT_UNIT,
    MEASUREMENT_VALUE — from free-text clinical narratives such as nursing
    notes, triage assessments, and vital sign flowsheets.

    Args:
        text: Clinical narrative to annotate.

    Returns:
        A tuple of (highlighted_text, entities_table, summary_markdown)
        suitable for the three Gradio outputs.
    """
    text = (text or "").strip()
    if not text:
        return [], [], "Please enter some clinical text to annotate."

    raw_entities = _nlp(text)
    entities = _merge_entities(text, raw_entities)

    highlights = _entities_to_highlights(text, entities)

    table_rows = [
        [ent["entity_group"], text[ent["start"]:ent["end"]], f"{ent['score']:.3f}"]
        for ent in entities
    ]

    counts = {}
    for ent in entities:
        counts[ent["entity_group"]] = counts.get(ent["entity_group"], 0) + 1
    if counts:
        summary_lines = [f"**{count}** \u00d7 `{name}`"
                         for name, count in sorted(counts.items(),
                                                   key=lambda kv: -kv[1])]
        summary_md = "### Extraction summary\n\n" + "\n".join(summary_lines)
        summary_md += f"\n\n**Total entities found:** {len(entities)}"
    else:
        summary_md = "### Extraction summary\n\nNo vital sign entities detected in the provided text."

    return highlights, table_rows, summary_md


CSS = """
#col-container { max-width: 1100px; margin: 0 auto; }
.dark .gradio-container { color: var(--body-text-color); }
.legend { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
.legend-chip { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; padding: 2px 8px; border-radius: 999px; color: #fff; }
"""

legend_html = '<div class="legend">' + "".join(
    f'<span class="legend-chip" style="background:{color}">{name}</span>'
    for name, color in ENTITY_COLORS.items()
) + "</div>"


with gr.Blocks() as demo:
    gr.Markdown(
        "# Healthcare Brain Vitals NER\n"
        "Extract vital sign and measurement entities (blood pressure, heart rate, "
        "respiratory rate, temperature, SpO2, weight, height, BMI, pain score, "
        "GCS, blood glucose, dates, times, units, values) from unstructured "
        "clinical text. Built on [genzeonplatform/healthcare-brain-vitals-ner]"
        f"(https://huggingface.co/{MODEL_ID}) \u2014 a Bio_ClinicalBERT "
        "fine-tuned for 15 vital sign entity types."
    )

    with gr.Column(elem_id="col-container"):
        with gr.Row():
            text_in = gr.Textbox(
                label="Clinical text",
                placeholder="Paste a nursing note, triage assessment, or vital sign flowsheet\u2026",
                lines=8,
                scale=4,
            )
            run_btn = gr.Button("Extract entities", variant="primary", scale=1)

        highlighted = gr.HighlightedText(
            label="Annotated text",
            combine_adjacent=True,
            color_map=ENTITY_COLORS,
            show_legend=True,
        )

        gr.HTML(legend_html)

        with gr.Row():
            with gr.Column(scale=2):
                summary_md = gr.Markdown(label="Summary")
            with gr.Column(scale=3):
                entities_table = gr.Dataframe(
                    headers=["Entity type", "Text", "Confidence"],
                    datatype=["str", "str", "str"],
                    label="Extracted entities",
                    wrap=True,
                )

        gr.Examples(
            examples=[
                ["Vitals on admission: BP 142/88 mmHg, HR 96 bpm, RR 22 breaths/min, Temp 38.6 C, SpO2 94% on room air. Weight 82.3 kg, Height 175 cm, BMI 26.9. Pain score 7/10."],
                ["Nursing assessment 03/15/2024 at 0600: Blood pressure 118/72 mmHg, heart rate 78 bpm regular, respiratory rate 16, temperature 36.8 degrees Celsius, oxygen saturation 98% on 2L NC."],
                ["GCS 11 (E3 V4 M4). Blood glucose 245 mg/dL at 14:30. Pain score 4/10, improved from 8/10 pre-medication."],
                ["Serial vitals q4h: 0800 BP 130/82, HR 88, RR 18, T 37.2, SpO2 96%. 1200 BP 124/76, HR 82, RR 16, T 37.0, SpO2 97%. Weight stable at 74.5 kg."],
            ],
            inputs=text_in,
            outputs=[highlighted, entities_table, summary_md],
            fn=extract_vital_entities,
            cache_examples=True,
            cache_mode="lazy",
        )

    run_btn.click(
        fn=extract_vital_entities,
        inputs=text_in,
        outputs=[highlighted, entities_table, summary_md],
        api_name="extract",
    )

if __name__ == "__main__":
    demo.launch(mcp_server=True, theme=gr.themes.Citrus(), css=CSS)
