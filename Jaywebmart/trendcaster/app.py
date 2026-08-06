"""
TrendCaster
===========
A short-form video trend trajectory classifier.

Given pre-posting features of a TikTok or YouTube Shorts video,
the model predicts whether the trajectory will be rising, stable,
declining, or seasonal.

Model: XGBoost classifier trained on 2,209 labelled samples
       from a synthetic 2025 short-form video dataset.
Test accuracy: 57.1% (macro F1: 0.455)

Built for a teenage machine learning bootcamp.
"""

import json
import joblib
import numpy as np
import pandas as pd
import gradio as gr


# ============================================================
# Load model artefacts
# ============================================================

print("Loading model artefacts...")
model = joblib.load("trendcaster_model.pkl")

with open("trendcaster_features.json") as f:
    feature_columns = json.load(f)

with open("trendcaster_labels.json") as f:
    label_mapping = json.load(f)

with open("trendcaster_options.json") as f:
    categorical_options = json.load(f)

label_mapping = {int(k): v for k, v in label_mapping.items()}
print(f"Loaded. Model expects {len(feature_columns)} features.")

# ============================================================
# Language display mapping — codes to full names
# ============================================================

LANGUAGE_DISPLAY = {
    "ar": "Arabic",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "hi": "Hindi",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "pt": "Portuguese",
    "ru": "Russian",
    "tr": "Turkish",
    "zh": "Chinese",
}

# Reverse mapping: full name → code (for encoding)
LANGUAGE_CODE = {v: k for k, v in LANGUAGE_DISPLAY.items()}

# Build the display list — fall back to the raw code if not in mapping
language_display_options = [
    LANGUAGE_DISPLAY.get(code, code)
    for code in categorical_options["language"]
]


# ============================================================
# Prediction function
# ============================================================

def predict_trend(
    platform: str,
    region: str,
    language: str,
    category: str,
    creator_tier: str,
    traffic_source: str,
    device_brand: str,
    title_len: int,
    weekend_hashtag_boost: bool,
):
    """Encode inputs, predict, return formatted results."""

    # Build a single-row dataframe with all model features set to 0
    input_data = pd.DataFrame(0, index=[0], columns=feature_columns)

    # Set numeric features
    if "title_len" in input_data.columns:
        input_data.loc[0, "title_len"] = int(title_len)
    if "weekend_hashtag_boost" in input_data.columns:
        input_data.loc[0, "weekend_hashtag_boost"] = int(weekend_hashtag_boost)

    # Set one-hot encoded categorical features
    # Language comes in as a full name (e.g. "English") — convert back to code
    categorical_inputs = {
        "platform": platform,
        "region": region,
        "language": LANGUAGE_CODE.get(language, language),
        "category": category,
        "creator_tier": creator_tier,
        "traffic_source": traffic_source,
        "device_brand": device_brand,
    }

    for col_prefix, value in categorical_inputs.items():
        column_name = f"{col_prefix}_{value}"
        if column_name in input_data.columns:
            input_data.loc[0, column_name] = 1

    # Predict
    prediction = model.predict(input_data)[0]
    probabilities = model.predict_proba(input_data)[0]

    predicted_label = label_mapping[int(prediction)]
    confidence = float(probabilities[int(prediction)])

    # Build the prediction box
    prediction_html = f"""
    <div style="font-family: Inter, sans-serif; padding: 20px 0;">
        <p style="color: #888; font-size: 0.75rem; text-transform: uppercase;
                  letter-spacing: 0.15em; margin-bottom: 10px;">
            Predicted trajectory
        </p>
        <p style="font-family: Fraunces, Georgia, serif; font-size: 2.6rem;
                  font-weight: 600; color: #1a1a1a; margin: 0 0 6px 0;
                  letter-spacing: -0.02em;">
            {predicted_label.capitalize()}
        </p>
        <p style="color: #555; font-size: 0.9rem; margin: 0;">
            Confidence: {confidence:.1%}
        </p>
    </div>
    """

    # Build the probability breakdown table
    probability_rows = ""
    for i, label in label_mapping.items():
        prob = float(probabilities[i])
        is_predicted = i == int(prediction)
        weight = "600" if is_predicted else "400"
        bar_width = prob * 100

        probability_rows += f"""
        <tr>
            <td style="padding: 8px 12px; font-weight: {weight};
                       color: #1a1a1a; font-size: 0.92rem;">
                {label.capitalize()}
            </td>
            <td style="padding: 8px 12px; text-align: right;
                       font-family: 'IBM Plex Mono', monospace;
                       font-weight: {weight}; color: #1a1a1a;
                       font-size: 0.92rem;">
                {prob:.1%}
            </td>
            <td style="padding: 8px 12px; width: 50%;">
                <div style="background: #efede7; height: 6px;
                            border-radius: 2px; overflow: hidden;">
                    <div style="background: #006d77; height: 100%;
                                width: {bar_width}%;"></div>
                </div>
            </td>
        </tr>
        """

    probability_html = f"""
    <div style="font-family: Inter, sans-serif; padding-top: 16px;
                border-top: 1px solid #e5e3dd;">
        <p style="color: #888; font-size: 0.75rem; text-transform: uppercase;
                  letter-spacing: 0.15em; margin-bottom: 12px;">
            All class probabilities
        </p>
        <table style="width: 100%; border-collapse: collapse;">
            {probability_rows}
        </table>
    </div>
    """

    return prediction_html + probability_html


# ============================================================
# UI styling — match WasteWatch aesthetic
# ============================================================
#
# Strategy: rather than target Gradio's internal compiled class names
# (which change every version and broke between Gradio 5 -> 6), we
# override Gradio's public theme CSS variables. These variables are
# part of Gradio's documented theming API and stay stable across
# versions. We set them identically for both light mode (:root) and
# dark mode (.dark) so the interface looks the same regardless of the
# visitor's system theme — this avoids the "patchy dark/light" problem
# where some boxes are hardcoded light HTML sitting inside a dark
# Gradio shell.

custom_css = """
:root, .dark {
    --body-background-fill: #fafaf7;
    --background-fill-primary: #ffffff;
    --background-fill-secondary: #fafaf7;
    --border-color-primary: #e0ddd5;
    --border-color-accent: #006d77;
    --body-text-color: #1a1a1a;
    --body-text-color-subdued: #6b6b6b;
    --block-background-fill: #ffffff;
    --block-border-color: #e0ddd5;
    --block-label-text-color: #555555;
    --block-title-text-color: #1a1a1a;
    --input-background-fill: #ffffff;
    --input-border-color: #d8d4cb;
    --color-accent: #006d77;
    --color-accent-soft: #e3f0f0;
    --button-primary-background-fill: #006d77;
    --button-primary-background-fill-hover: #004f56;
    --button-primary-text-color: #ffffff;
    --button-primary-border-color: #006d77;
    --checkbox-background-color: #ffffff;
    --checkbox-background-color-selected: #006d77;
    --checkbox-background-color-hover: #ffffff;
    --checkbox-background-color-focus: #ffffff;
    --checkbox-border-color: #b8b3a6;
    --checkbox-border-color-selected: #006d77;
    --checkbox-border-color-hover: #006d77;
    --checkbox-border-color-focus: #006d77;
    --checkbox-border-width: 2px;
    --checkbox-label-text-color: #1a1a1a;
    --checkbox-label-text-color-selected: #1a1a1a;
}

html, body {
    color-scheme: light !important;
}

footer { display: none !important; }

.gradio-container {
    font-family: 'Inter', sans-serif !important;
    width: 100% !important;
    max-width: 100% !important;
    padding-left: 48px !important;
    padding-right: 48px !important;
}

.gradio-row {
    gap: 28px !important;
}

/* Card styling for our two main panels */
.input-card, .output-card {
    background: #ffffff !important;
    border: 1px solid #e0ddd5 !important;
    border-radius: 6px !important;
    padding: 28px !important;
}

.output-card {
    min-height: 320px;
}

label span {
    font-weight: 500 !important;
    color: #555555 !important;
}

button.primary {
    font-weight: 500 !important;
    border-radius: 4px !important;
}

/* ------------------------------------------------------------
   Force readable text everywhere. Gradio's compiled CSS uses
   hashed class names that change between versions and aren't
   safe to target by name, so instead we hit stable HTML tags
   and ARIA roles directly with high specificity.
   ------------------------------------------------------------ */

/* Every label, hint, and field text */
label, label *, .label-wrap, .label-wrap *,
span, p, li, td, th, option {
    color: #1a1a1a !important;
}

/* Field hint / "info" text under labels — keep it lighter, but legible */
.gradio-container [data-testid="block-info"],
.gradio-container .info {
    color: #767676 !important;
}

/* Inputs, selects, textareas, and the dropdown's visible value box
   (checkboxes and radios are excluded — they need their own rule below
   so the checked/filled state stays visible) */
input:not([type="checkbox"]):not([type="radio"]), select, textarea,
.wrap-inner, .wrap, .secondary-wrap, .single-select {
    background: #ffffff !important;
    color: #1a1a1a !important;
    border-color: #d8d4cb !important;
}

/* Checkboxes — explicit styling so the checked state is actually visible.
   accent-color is the most reliable cross-browser way to colour a native
   checkbox without fighting Gradio's internal markup. */
input[type="checkbox"], input[type="radio"] {
    accent-color: #006d77 !important;
    width: 18px !important;
    height: 18px !important;
    border: 2px solid #b8b3a6 !important;
    background: #ffffff !important;
}

input[type="checkbox"]:checked, input[type="radio"]:checked {
    background: #006d77 !important;
    border-color: #006d77 !important;
}

input::placeholder, textarea::placeholder {
    color: #999999 !important;
}

/* Dropdown popup list (the options that appear on click) */
ul[role="listbox"], .options {
    background: #ffffff !important;
    border: 1px solid #d8d4cb !important;
}

ul[role="listbox"] li, .options .item, li[role="option"] {
    background: #ffffff !important;
    color: #1a1a1a !important;
}

ul[role="listbox"] li:hover, .options .item:hover, li[role="option"]:hover {
    background: #f3f1ec !important;
    color: #1a1a1a !important;
}

/* Secondary buttons (Clear / Undo on dropdowns and sliders) */
button.secondary {
    background: #ffffff !important;
    color: #1a1a1a !important;
    border-color: #d8d4cb !important;
}

/* Slider numbers and track */
input[type="number"] {
    background: #ffffff !important;
    color: #1a1a1a !important;
}

/* Examples table — renders as its own mini data-grid */
.dataset, .table-wrap, .gr-samples-table, table {
    background: #ffffff !important;
}

.dataset td, .dataset th,
.table-wrap td, .table-wrap th,
.gr-samples-table td, .gr-samples-table th {
    background: #ffffff !important;
    color: #1a1a1a !important;
    border-color: #e0ddd5 !important;
}

.dataset tr:hover td {
    background: #f3f1ec !important;
}

/* Checkbox label text */
.gradio-container [data-testid="checkbox"] span,
.gradio-container [data-testid="checkbox"] label {
    color: #1a1a1a !important;
}
"""


# ============================================================
# Build the interface
# ============================================================

with gr.Blocks(
    css=custom_css,
    theme=gr.themes.Base(
        primary_hue=gr.themes.colors.teal,
        neutral_hue=gr.themes.colors.gray,
        font=[gr.themes.GoogleFont("Inter"), "sans-serif"],
        font_mono=[gr.themes.GoogleFont("IBM Plex Mono"), "monospace"],
    ),
    title="TrendCaster",
) as demo:

    # Header
    gr.HTML(
        """
        <div style="padding: 24px 0 16px 0; border-bottom: 1px solid #e5e3dd;
                    margin-bottom: 32px;">
            <p style="font-family: 'Inter', sans-serif; color: #006d77;
                      font-size: 0.75rem; text-transform: uppercase;
                      letter-spacing: 0.18em; font-weight: 600;
                      margin-bottom: 12px;">
                Bootcamp project
            </p>
            <h1 style="font-family: 'Fraunces', Georgia, serif;
                       font-size: 3rem; font-weight: 600; line-height: 1;
                       letter-spacing: -0.03em; margin: 0 0 12px 0;
                       color: #1a1a1a;">
                TrendCaster
            </h1>
            <p style="font-family: 'Fraunces', Georgia, serif;
                      font-style: italic; color: #555; font-size: 1.2rem;
                      line-height: 1.35; margin: 0; max-width: 560px;">
                Predict whether a short-form video is on a rising, stable,
                declining or seasonal trajectory using only the information
                a creator knows before they post.
            </p>
        </div>
        """
    )

    with gr.Row():
        # Left column — inputs
        with gr.Column(scale=1, elem_classes="input-card"):
            gr.HTML(
                """
                <p style="font-family: 'Inter', sans-serif; color: #888;
                          font-size: 0.75rem; text-transform: uppercase;
                          letter-spacing: 0.15em; margin-bottom: 8px;">
                    Configure the post
                </p>
                <p style="font-family: 'Inter', sans-serif; color: #555;
                          font-size: 0.88rem; line-height: 1.5;
                          margin-bottom: 20px;">
                    Set the nine fields below to describe a video before it's
                    posted, then select Predict trajectory.
                    Not sure where to start? Try one of the examples underneath
                    the button.
                </p>
                """
            )

            platform_input = gr.Dropdown(
                choices=categorical_options["platform"],
                label="Platform",
                value=categorical_options["platform"][0],
                info="Where the video is posted",
            )
            category_input = gr.Dropdown(
                choices=categorical_options["category"],
                label="Content category",
                value=categorical_options["category"][0],
                info="What kind of content this is",
            )
            region_input = gr.Dropdown(
                choices=categorical_options["region"],
                label="Region",
                value=categorical_options["region"][0],
                info="Where the audience is based",
            )
            language_input = gr.Dropdown(
                choices=language_display_options,
                label="Language",
                value=language_display_options[0],
                info="Primary language of the video",
            )
            creator_tier_input = gr.Dropdown(
                choices=categorical_options["creator_tier"],
                label="Creator tier",
                value=categorical_options["creator_tier"][0],
                info="Micro, Mid, Macro or Star: based on the creator's average views",
            )
            traffic_source_input = gr.Dropdown(
                choices=categorical_options["traffic_source"],
                label="Traffic source",
                value=categorical_options["traffic_source"][0],
                info="How viewers are expected to find this video",
            )
            device_brand_input = gr.Dropdown(
                choices=categorical_options["device_brand"],
                label="Device brand",
                value=categorical_options["device_brand"][0],
                info="Device the creator filmed or uploaded on",
            )
            title_len_input = gr.Slider(
                minimum=0,
                maximum=100,
                value=20,
                step=1,
                label="Title length (characters)",
                info="How long the video title is",
            )
            weekend_input = gr.Checkbox(
                value=False,
                label="Posted on a weekend with a popular hashtag",
                info="The single strongest signal the model uses",
            )

            predict_button = gr.Button("Predict trajectory", variant="primary", size="lg")

            gr.Examples(
                examples=[
                    ["tiktok", "Americas", "en", "Sports", "macro", "ForYou", "Apple", 25, True],
                    ["youtube", "Europe", "en", "News", "micro", "Suggested", "Samsung", 40, False],
                ],
                inputs=[
                    platform_input, region_input, language_input, category_input,
                    creator_tier_input, traffic_source_input, device_brand_input,
                    title_len_input, weekend_input,
                ],
                label="Try an example",
            )

        # Right column — output
        with gr.Column(scale=1, elem_classes="output-card"):
            gr.HTML(
                """
                <p style="font-family: 'Inter', sans-serif; color: #888;
                          font-size: 0.75rem; text-transform: uppercase;
                          letter-spacing: 0.15em; margin-bottom: 8px;">
                    Result
                </p>
                <p style="font-family: 'Inter', sans-serif; color: #555;
                          font-size: 0.88rem; line-height: 1.5;
                          margin-bottom: 16px;">
                    The model's prediction and confidence will appear here.
                </p>
                """
            )
            output_html = gr.HTML(
                value="""
                <div style="font-family: Inter, sans-serif; padding: 16px 0;
                            color: #888; font-size: 0.9rem; text-align: center;
                            border: 1px dashed #d8d4cb; border-radius: 4px;">
                    Waiting for input; set the fields on the left and
                    select <em>Predict trajectory</em>.
                </div>
                """
            )

    # Methodology note
    gr.HTML(
        """
        <div style="padding-top: 40px; border-top: 1px solid #e5e3dd;
                    margin-top: 40px; font-family: 'Inter', sans-serif;
                    color: #555; font-size: 0.88rem; line-height: 1.6;">
            <p style="color: #888; font-size: 0.75rem; text-transform: uppercase;
                      letter-spacing: 0.15em; margin-bottom: 12px;">
                Honest note on what this is
            </p>
            <p style="margin-bottom: 10px;">
                The model is an XGBoost classifier trained on a synthetic 2025
                short-form video dataset. It uses only features knowable
                before a video is posted; no engagement
                metrics, no early-performance signals. This is the harder
                version of the problem and the one that's actually useful.
            </p>
            <p style="margin-bottom: 10px;">
                Test accuracy is 57.1% across four classes, with macro F1
                of 0.455. The model struggles most with the declining class
                because the features it has access to don't carry enough
                signal to separate "declining" from "stable" reliably. That
                limitation is honest data, not a hidden bug.
            </p>
            <p style="margin: 0;">
                Built for a teenage machine learning bootcamp as a worked
                example of CRISP-DM: feature filtering, encoding, SMOTE,
                three-model comparison, deployment.
            </p>
        </div>
        """
    )

    # Wire the button to the prediction function
    predict_button.click(
        fn=predict_trend,
        inputs=[
            platform_input,
            region_input,
            language_input,
            category_input,
            creator_tier_input,
            traffic_source_input,
            device_brand_input,
            title_len_input,
            weekend_input,
        ],
        outputs=output_html,
    )


# ============================================================
# Launch
# ============================================================

if __name__ == "__main__":
    demo.launch()
