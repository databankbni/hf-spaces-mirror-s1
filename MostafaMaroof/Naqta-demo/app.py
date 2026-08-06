import os

import gradio as gr
import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer


MODEL_ID = "MostafaMaroof/Naqta"
HF_TOKEN = os.environ.get("HF_TOKEN")

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=HF_TOKEN)
model = AutoModelForTokenClassification.from_pretrained(MODEL_ID, token=HF_TOKEN)
model.eval()

id2label = model.config.id2label
label2id = model.config.label2id

# ----------------------------------------------------------------------------
# Sliding-window inference settings
#
# The model was fine-tuned on ~192-subword windows. Long inputs are therefore
# split into overlapping word windows; each window is predicted independently
# and only the central region of each window is kept, so every word is labeled
# with real left AND right context around it.
# ----------------------------------------------------------------------------
WINDOW_WORDS = 100   # words per window (~180-220 subwords for MSA)
OVERLAP_WORDS = 40   # words shared between consecutive windows
MAX_SUBWORDS = 256   # safety cap per window (headroom over training's 192)
BATCH_WINDOWS = 8    # windows per forward pass

# Per-class logit adjustments. The old blanket +0.8 on '،' pushed borderline
# '.' and '؛' predictions into commas across the whole text and is a likely
# cause of the reviewer-reported ، / . / ؛ confusion. Keep at 0.0 unless a
# guideline-annotated dev set shows a calibrated value actually helps.
LOGIT_BIAS = {
    # "،": 0.0,
}


PUNCT_COLORS = {
    ".": "#ef4444",
    "،": "#3b82f6",
    "؟": "#a855f7",
    "!": "#f97316",
    ":": "#10b981",
    "؛": "#eab308",
    "-": "#64748b",
}


def _make_windows(n_words, window=WINDOW_WORDS, overlap=OVERLAP_WORDS):
    """Return (start, end, keep_start, keep_end) word spans.

    keep_start / keep_end define which word positions take their final label
    from this window. Interior windows only contribute their central region;
    the first window keeps its left edge and the last keeps its right edge.
    """
    if n_words <= window:
        return [(0, n_words, 0, n_words)]

    stride = window - overlap
    trim = overlap // 2
    windows = []
    start = 0
    while start < n_words:
        end = min(start + window, n_words)
        if end == n_words:
            # Anchor the final window to the tail so it has full left context.
            start = max(0, n_words - window)
        keep_start = 0 if start == 0 else start + trim
        keep_end = n_words if end == n_words else end - trim
        windows.append((start, end, keep_start, keep_end))
        if end == n_words:
            break
        start += stride
    return windows


def _predict_words(text):
    text = text.strip()
    if not text:
        return [], []

    words = text.split()
    labels = ["O"] * len(words)
    windows = _make_windows(len(words))

    for i in range(0, len(windows), BATCH_WINDOWS):
        batch = windows[i : i + BATCH_WINDOWS]
        inputs = tokenizer(
            [words[s:e] for s, e, _, _ in batch],
            is_split_into_words=True,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_SUBWORDS,
            padding=True,
        )

        with torch.no_grad():
            logits = model(**inputs).logits

        for mark, bias in LOGIT_BIAS.items():
            if bias:
                logits[:, :, label2id[mark]] += bias

        pred_ids = logits.argmax(dim=-1)

        for j, (start, _end, keep_start, keep_end) in enumerate(batch):
            word_ids = inputs.word_ids(batch_index=j)
            previous_word_id = None
            for token_idx, word_id in enumerate(word_ids):
                if word_id is None or word_id == previous_word_id:
                    continue
                previous_word_id = word_id
                pos = start + word_id  # global word position
                if keep_start <= pos < keep_end:
                    labels[pos] = id2label[pred_ids[j, token_idx].item()]

    return words, labels


def _to_text(words, labels):
    if not words:
        return ""
    pieces = []
    for word, label in zip(words, labels):
        pieces.append(word + label if label != "O" else word)
    return "\u202B" + " ".join(pieces) + "\u202C"


def _to_html(words, labels):
    if not words:
        return "<div class='naqta-empty'>اكتب نصاً لرؤية الترقيم الملوّن</div>"

    spans = []
    for word, label in zip(words, labels):
        if label != "O":
            color = PUNCT_COLORS.get(label, "#9ca3af")
            spans.append(
                f"<span class='naqta-word'>{word}"
                f"<span class='naqta-mark' style='color:{color}'>{label}</span>"
                f"</span>"
            )
        else:
            spans.append(f"<span class='naqta-word'>{word}</span>")

    body = " ".join(spans)
    return f"<div class='naqta-output' dir='rtl'>{body}</div>"


def restore_punctuation(text):
    words, labels = _predict_words(text)
    return _to_text(words, labels)


def run(text):
    # Single forward pass shared by both outputs (was two full inferences).
    words, labels = _predict_words(text)
    return _to_text(words, labels), _to_html(words, labels)


CUSTOM_CSS = """
.gradio-container { max-width: 1100px !important; margin: auto; }
#naqta-header {
    text-align: center;
    padding: 28px 16px 8px 16px;
}
#naqta-header h1 {
    font-size: 2.6rem;
    margin: 0;
    background: linear-gradient(90deg,#6366f1,#a855f7,#ec4899);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    font-weight: 800;
    letter-spacing: 0.5px;
}
#naqta-header p {
    margin-top: 8px;
    color: #6b7280;
    font-size: 1rem;
}
.naqta-card {
    border-radius: 16px;
    padding: 8px;
}
.naqta-output {
    direction: rtl;
    text-align: right;
    line-height: 2.4;
    font-size: 1.25rem;
    padding: 18px 20px;
    border-radius: 14px;
    background: #0f172a08;
    min-height: 120px;
    font-family: "Segoe UI", "Tahoma", "Amiri", serif;
}
.naqta-empty {
    color: #9ca3af;
    text-align: center;
    padding: 40px 0;
    font-style: italic;
}
.naqta-word {
    display: inline-block;
    margin: 2px 4px;
    padding: 4px 8px;
    border-radius: 8px;
    background: #ffffff10;
    border: 1px solid #ffffff15;
}
.naqta-mark {
    font-weight: 800;
    margin-right: 2px;
    font-size: 1.35rem;
}
#naqta-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    justify-content: center;
    padding: 8px 0 4px 0;
}
.naqta-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    background: #ffffff10;
    border: 1px solid #ffffff20;
    font-size: 0.85rem;
}
.naqta-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
}
#naqta-footer {
    text-align: center;
    color: #9ca3af;
    font-size: 0.85rem;
    padding: 12px;
}
"""


LEGEND_HTML = """
<div id='naqta-legend'>
  <span class='naqta-legend-item'><span class='naqta-dot' style='background:#ef4444'></span> . نقطة</span>
  <span class='naqta-legend-item'><span class='naqta-dot' style='background:#3b82f6'></span> ، فاصلة</span>
  <span class='naqta-legend-item'><span class='naqta-dot' style='background:#a855f7'></span> ؟ استفهام</span>
  <span class='naqta-legend-item'><span class='naqta-dot' style='background:#f97316'></span> ! تعجب</span>
  <span class='naqta-legend-item'><span class='naqta-dot' style='background:#10b981'></span> : نقطتان</span>
  <span class='naqta-legend-item'><span class='naqta-dot' style='background:#eab308'></span> ؛ فاصلة منقوطة</span>
  <span class='naqta-legend-item'><span class='naqta-dot' style='background:#64748b'></span> - شَرطة</span>
</div>
"""


EXAMPLES = [
    ["بلغت نسبة النمو الاقتصادي 4.7 بالمئة خلال الربع الثالث من عام 2024 وهو اعلى مستوى منذ خمس سنوات"],
    ["اذا اردت ان تنجح في حياتك فعليك ان تحدد اهدافك بوضوح وان تعمل بجد واستمرارية ولا تيأس عند اول عقبة تواجهها"],
    ["يقول المثل العربي من جد وجد ومن زرع حصد وهذا يعني ان النجاح لا يأتي بدون عمل وتعب واجتهاد"],
    ["يتكون الجهاز الهضمي من عدة اعضاء رئيسية وهي الفم والمريء والمعدة والامعاء الدقيقة والامعاء الغليظة"],
    ["هل تعلم ان اللغة العربية تحتوي على اكثر من اثني عشر مليون كلمة وهي اغنى لغات العالم"],
]


with gr.Blocks(title="Naqta · Arabic Punctuation Restoration") as demo:

    gr.HTML(
        """
        <div id='naqta-header'>
            <h1>Naqta · نقطة</h1>
            <p>Arabic punctuation restoration powered by XLM-RoBERTa Large</p>
        </div>
        """
    )

    gr.HTML(LEGEND_HTML)

    with gr.Row():
        with gr.Column(scale=1):
            input_text = gr.Textbox(
                label="النص بدون ترقيم",
                lines=8,
                placeholder="اكتب النص العربي هنا بدون علامات ترقيم...",
                rtl=True,
                text_align="right",
                elem_classes=["naqta-card"],
            )
            with gr.Row():
                run_btn = gr.Button("استعادة الترقيم", variant="primary", size="lg")
                clear_btn = gr.Button("مسح", variant="secondary", size="lg")

        with gr.Column(scale=1):
            output_text = gr.Textbox(
                label="النص بعد الترقيم",
                lines=8,
                rtl=True,
                text_align="right",
                elem_classes=["naqta-card"],
            )
            output_html = gr.HTML(label="عرض ملوّن")

    gr.Examples(
        examples=EXAMPLES,
        inputs=input_text,
        label="أمثلة جاهزة",
    )

    gr.HTML(
        "<div id='naqta-footer'>"
        "Built with ❤ · Model: "
        "<a href='https://huggingface.co/MostafaMaroof/Naqta' target='_blank'>MostafaMaroof/Naqta</a>"
        "</div>"
    )

    run_btn.click(fn=run, inputs=input_text, outputs=[output_text, output_html])
    input_text.submit(fn=run, inputs=input_text, outputs=[output_text, output_html])
    clear_btn.click(
        fn=lambda: ("", "", ""),
        outputs=[input_text, output_text, output_html],
    )


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(primary_hue="indigo", secondary_hue="purple"),
        css=CUSTOM_CSS,
    )