import logging
import re
import threading
import traceback
 
import gradio as gr
import torch
from langdetect import LangDetectException, detect
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, pipeline
 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
 
# Free CPU Spaces have 2 vCPUs; more threads = more RAM, no more speed.
torch.set_num_threads(2)
 
# --- Configuration ---
MODEL_HUB_ID = "abhinandansamal/nllb-200-distilled-600M-full-finetuned-odia-german-bidirectional"
ODIA_LANG_CODE = "ory_Orya"
GERMAN_LANG_CODE = "deu_Latn"
 
PREFIX_ORI_TO_DEU = "translate Odia to German: "
PREFIX_DEU_TO_ORI = "translate German to Odia: "
 
GEN_CONFIG = {
    "max_new_tokens": 256,
    "num_beams": 2,
    "length_penalty": 1.0,
    "early_stopping": True,
}
 
# --- Lazy model loading ---
_translator = None
_load_error = None
_load_lock = threading.Lock()
 
 
def get_translator():
    """Load the model on first use and cache it for subsequent calls."""
    global _translator, _load_error
 
    if _translator is not None or _load_error is not None:
        return _translator
 
    with _load_lock:
        if _translator is not None or _load_error is not None:
            return _translator
        try:
            logger.info("Loading full fine-tuned model: %s", MODEL_HUB_ID)
            use_gpu = torch.cuda.is_available()
 
            tokenizer = AutoTokenizer.from_pretrained(MODEL_HUB_ID)
            model = AutoModelForSeq2SeqLM.from_pretrained(
                MODEL_HUB_ID,
                dtype=torch.float16 if use_gpu else torch.float32,
                low_cpu_mem_usage=True,
            )
            model.eval()
 
            _translator = pipeline(
                "translation",
                model=model,
                tokenizer=tokenizer,
                device=0 if use_gpu else -1,
                **GEN_CONFIG,
            )
            logger.info("Model loaded successfully.")
        except Exception as exc:  # noqa: BLE001
            _load_error = str(exc)
            logger.error("Model load failed: %s", traceback.format_exc())
 
    return _translator
 
 
# --- Helper functions ---
ODIA_PATTERN = re.compile(r"[଀-୿]")
 
 
def is_odia_text(text: str) -> bool:
    """True if the text contains any character from the Odia Unicode block."""
    if not text or not text.strip():
        return False
    return bool(ODIA_PATTERN.search(text))
 
 
def translate_process(input_text: str, source_lang: str = "auto") -> str:
    """Detect the source language, apply the training prefix, and translate."""
    if not input_text or not input_text.strip():
        return "Error: Input text is empty."
 
    translator = get_translator()
    if translator is None:
        return f"Error: model could not be loaded on the server. ({_load_error})"
 
    try:
        if source_lang == "auto":
            if is_odia_text(input_text):
                detected_lang = "or"
            else:
                try:
                    detected_lang = detect(input_text)
                except LangDetectException:
                    return "Error: could not detect language. Please select it manually."
        else:
            detected_lang = source_lang
 
        if detected_lang == "or":
            prompt = PREFIX_ORI_TO_DEU + input_text
            result = translator(prompt, src_lang=ODIA_LANG_CODE, tgt_lang=GERMAN_LANG_CODE)
        elif detected_lang == "de":
            prompt = PREFIX_DEU_TO_ORI + input_text
            result = translator(prompt, src_lang=GERMAN_LANG_CODE, tgt_lang=ODIA_LANG_CODE)
        else:
            return f"Error: language '{detected_lang}' is not supported. Use Odia or German."
 
        return result[0]["translation_text"]
 
    except Exception as exc:  # noqa: BLE001
        logger.error("Translation failure: %s", traceback.format_exc())
        return f"Error during processing: {exc}"
 
 
# --- Gradio interface ---
title = "💎 Full Fine-Tuned NLLB Odia-German Translator"
description = """
### Full weight update (FFT)
This app uses the **fully fine-tuned NLLB-200 (600M)** model, where all internal
weights were optimized for this language pair.
 
*Running on a free CPU Space: the first translation takes 1-2 minutes while the
model downloads and loads. Later requests are much faster.*
"""
 
examples = [
    ["ଆଜି ପାଗ ବହୁତ ଭଲ ଅଛି।", "or"],
    ["Wie ist deine Gesundheit?", "de"],
    ["ମନ୍ତ୍ରୀ ଘୋଷଣା କଲେ ଯେ ଏହି ନୂଆ ରାଜପଥ ଆସନ୍ତା ବର୍ଷ ସୁଦ୍ଧା ସମ୍ପୂର୍ଣ୍ଣ ହେବ।", "or"],
]
 
iface = gr.Interface(
    fn=translate_process,
    inputs=[
        gr.Textbox(lines=4, label="Input sentence", placeholder="Type here..."),
        gr.Radio(choices=["auto", "or", "de"], label="Source language", value="auto"),
    ],
    outputs=gr.Textbox(lines=4, label="FFT translation output"),
    title=title,
    description=description,
    examples=examples,
    cache_examples=False,   # never run the model at startup
    theme=gr.themes.Monochrome(),
    flagging_mode="never",
)
 
if __name__ == "__main__":
    iface.queue(max_size=8).launch(server_name="0.0.0.0", server_port=7860)