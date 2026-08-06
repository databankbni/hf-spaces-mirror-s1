"""Gradio application for the Chief Complaint Triage Education Assistant."""

import gradio as gr
from transformers import pipeline

from safety_rules import (
    CATEGORY_EMERGENCY,
    CATEGORY_PROMPT,
    CATEGORY_ROUTINE,
    CATEGORY_SELF_CARE,
    CATEGORY_UNCERTAIN,
    MODEL_LABEL_TO_CATEGORY,
    choose_final_result,
    detect_warning_phrases,
    input_is_too_short,
)


MODEL_NAME = "facebook/bart-large-mnli"
CANDIDATE_LABELS = list(MODEL_LABEL_TO_CATEGORY)

# Model loaded once when needed, then reused.
classifier = None


CATEGORY_MESSAGES = {
    CATEGORY_EMERGENCY: (
        "Emergency warning language was detected. Do not rely on this classroom "
        "demonstration to decide whether a situation is an emergency."
    ),
    CATEGORY_PROMPT: (
        "The model placed this example in the prompt-evaluation category. If this "
        "were a real situation, a licensed healthcare professional would be the "
        "appropriate source of individualized guidance."
    ),
    CATEGORY_ROUTINE: (
        "The model placed this example in the routine-follow-up category. This is "
        "an educational classification, not a recommendation about when to seek care."
    ),
    CATEGORY_SELF_CARE: (
        "The model placed this example in the lower-urgency category. This does not "
        "prove that staying home is safe or rule out a medical problem."
    ),
    CATEGORY_UNCERTAIN: (
        "The application could not produce a sufficiently usable classification. "
        "Do not rely on this demonstration for a real health decision."
    ),
}


PERMANENT_DISCLAIMER = """
---
**Permanent disclaimer:** This application is a classroom demonstration using a
general-language model. It is for educational purposes only and is not medical
advice, a diagnosis, a clinical triage tool, or a substitute for emergency
services or a licensed healthcare professional. A missing warning phrase does
not mean that a situation is safe. Do not enter identifiable patient information.
"""


def get_classifier():
    """Load the selected Hugging Face model once and reuse it."""

    global classifier
    if classifier is None:
        classifier = pipeline(
            "zero-shot-classification",
            model=MODEL_NAME,
        )
    return classifier


def format_result(result: dict, confidence: float | None = None) -> str:
    """Turn the category result into Markdown format for the interface."""

    if confidence is None:
        score_text = "Not calculated"
    else:
        score_text = f"{confidence:.1%}"

    warning_text = ""
    if result["warning_phrases"]:
        warning_text = "\n**Warning phrase found:** " + ", ".join(
            result["warning_phrases"]
        )

    resource_text = ""
    if result["show_emergency_resources"]:
        resource_text = "\n\n### Important contact information\n" + result[
            "emergency_resources"
        ]

    return f"""## Educational result

### {result['category']}

{CATEGORY_MESSAGES[result['category']]}

**How this result was selected:** {result['reason']}  
**Model classification score:** {score_text}
{warning_text}
{resource_text}

The model score only compares the three candidate labels. It is **not** the
probability of an emergency or the probability that the result is medically correct.

{PERMANENT_DISCLAIMER}
"""


def analyze_symptoms(text: str) -> str:
    """Classify one fictional or de-identified symptom description."""

    # Warning phrases and very short inputs don't need the model inference and failures default to U5.
    if detect_warning_phrases(text) or input_is_too_short(text):
        return format_result(choose_final_result(text))

    try:
        model_output = get_classifier()(
            text,
            candidate_labels=CANDIDATE_LABELS,
            multi_label=False,
        )
        top_label = model_output["labels"][0]
        confidence = float(model_output["scores"][0])
        result = choose_final_result(text, top_label, confidence)
        return format_result(result, confidence)
    except Exception:
        return format_result(choose_final_result(text))


EXAMPLES = [
    [
        "A fictional adult suddenly has severe trouble breathing and cannot finish a sentence."
    ],
    [
        "A fictional adult has painful urination and a fever that started yesterday."
    ],
    [
        "A fictional adult has mild knee soreness after jogging that has stayed stable for several weeks."
    ],
]


demo = gr.Interface(
    fn=analyze_symptoms,
    inputs=gr.Textbox(
        lines=6,
        max_lines=10,
        label="Fictional or de-identified symptom description",
        info="Enter at least six words. Do not include names or other identifying information.",
        placeholder="Example: A fictional adult has had mild knee soreness after jogging...",
    ),
    outputs=gr.Markdown(label="Educational classification"),
    title="Chief Complaint Triage Education Assistant",
    description=(
        "This classroom demonstration uses a pretrained Transformer to place a "
        "fictional symptom description into a broad educational urgency category. "
        "It must not be used for real medical decisions."
    ),
    article=PERMANENT_DISCLAIMER,
    examples=EXAMPLES,
    cache_examples=False,
    flagging_mode="never",
    analytics_enabled=False,
    submit_btn="Classify example",
    clear_btn="Clear",
)


if __name__ == "__main__":
    demo.launch()
