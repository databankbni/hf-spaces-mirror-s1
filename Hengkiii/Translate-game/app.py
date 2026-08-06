"""
============================================================
HF Spaces NLLB-200 Translator - API FIXED VERSION
============================================================
"""

import os
import time
import torch
import gradio as gr
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

MODEL_NAME = "facebook/nllb-200-distilled-600M"

LANG_CODES = {
    "id": "ind_Latn", "en": "eng_Latn", "ja": "jpn_Jpan",
    "ko": "kor_Hang", "zh": "zho_Hans", "th": "tha_Thai",
    "vi": "vie_Latn", "ms": "zsm_Latn", "tl": "tgl_Latn",
    "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn",
    "ru": "rus_Cyrl", "pt": "por_Latn", "it": "ita_Latn",
    "ar": "arb_Arab", "hi": "hin_Deva",
}

device = "cuda" if torch.cuda.is_available() else "cpu"

if device == "cpu":
    torch.set_num_threads(4)

print(f"Loading {MODEL_NAME} on {device}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)

if device == "cuda":
    model = model.half()

model = model.to(device)
model.eval()

print(f"✅ Model ready on {device}")


# =========================
# CORE FUNCTIONS
# =========================
@torch.no_grad()
def translate_batch_core(texts, source="en", target="id"):
    if not texts:
        return []

    src_lang = LANG_CODES.get(source, "eng_Latn")
    tgt_lang = LANG_CODES.get(target, "ind_Latn")

    tokenizer.src_lang = src_lang

    inputs = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=256,
        return_tensors="pt"
    )

    inputs = {k: v.to(device) for k, v in inputs.items()}
    forced_bos_token_id = tokenizer.convert_tokens_to_ids(tgt_lang)

    outputs = model.generate(
        **inputs,
        forced_bos_token_id=forced_bos_token_id,
        max_new_tokens=256,
        num_beams=4,
        early_stopping=True,
        length_penalty=1.0,
        no_repeat_ngram_size=3,
    )

    return tokenizer.batch_decode(outputs, skip_special_tokens=True)


def translate_single(text, source="en", target="id"):
    """Single translate - return string langsung"""
    if not text or not text.strip():
        return ""
    result = translate_batch_core([text], source, target)
    return result[0] if result else ""


def translate_batch(text_blob, source="en", target="id"):
    """Batch translate - return 2 values: (translated_text, info)"""
    lines = [l.strip() for l in text_blob.splitlines() if l.strip()]
    if not lines:
        return "", "No text to translate"

    BATCH_SIZE = 16
    all_results = []

    for i in range(0, len(lines), BATCH_SIZE):
        batch = lines[i:i + BATCH_SIZE]
        translated = translate_batch_core(batch, source, target)
        all_results.extend(translated)

    output = "\n".join(all_results)
    info = f"Translated {len(lines)} lines | {source} -> {target}"
    return output, info


def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "model": MODEL_NAME,
        "device": device,
        "timestamp": time.time()
    }


# =========================
# GRADIO UI - FIXED API EXPOSURE
# =========================
lang_choices = list(LANG_CODES.keys())

# PENTING: Gunakan gr.Blocks dengan api_enabled=True
with gr.Blocks(title="NLLB-200 Translator", api_enabled=True) as demo:

    gr.Markdown("# ⚡ NLLB-200 Translator (600M)")
    gr.Markdown("High-quality translation for 200+ languages")

    with gr.Tab("Single Translate"):
        with gr.Row():
            src = gr.Dropdown(lang_choices, value="en", label="Source")
            tgt = gr.Dropdown(lang_choices, value="id", label="Target")

        inp = gr.Textbox(lines=4, label="Input Text", placeholder="Enter text...")
        out = gr.Textbox(lines=4, label="Translation")

        btn = gr.Button("Translate", variant="primary")
        # PENTING: Tambahkan api_name yang unik
        btn.click(
            translate_single,
            inputs=[inp, src, tgt],
            outputs=[out],
            api_name="translate_single"  # ← API endpoint name
        )

    with gr.Tab("Batch Translate"):
        with gr.Row():
            src2 = gr.Dropdown(lang_choices, value="en", label="Source")
            tgt2 = gr.Dropdown(lang_choices, value="id", label="Target")

        inp2 = gr.Textbox(lines=10, label="Input (1 line = 1 text)")
        out2 = gr.Textbox(lines=10, label="Translation")
        info2 = gr.Textbox(label="Info")

        btn2 = gr.Button("Translate Batch", variant="primary")
        # PENTING: api_name yang unik
        btn2.click(
            translate_batch,
            inputs=[inp2, src2, tgt2],
            outputs=[out2, info2],
            api_name="translate_batch"  # ← API endpoint name
        )

    with gr.Tab("API Docs"):
        gr.Markdown("""
        ## API Endpoints
        
        ### Single Translate
        ```python
        from gradio_client import Client
        client = Client("Hengkiii/Translate-game")
        result = client.predict("Hello", "en", "id", api_name="/translate_single")
        ```
        
        ### Batch Translate
        ```python
        result, info = client.predict("Line1\\nLine2", "en", "id", api_name="/translate_batch")
        ```
        """)


# =========================
# LAUNCH - PENTING: allowed_paths untuk API
# =========================
if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        show_error=True,
        # PENTING: Enable API access
        share=False,
        allowed_paths=["*"],  # Allow all paths
    )
    