import gradio as gr
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from peft import PeftModel

# Multi adaptor config
BASE_MODEL_ID = "facebook/nllb-200-distilled-600M"

EN_TO_KIK = "KnoxDevelopers/English-to-Kikuyu-language-translation-LoRA"
EN_TO_LUO = "KnoxDevelopers/English-to-Luo-language-translation-LoRA"
EN_TO_KAM = "KnoxDevelopers/nllb-200-English_to_Kikamba-lang-translation-QLoRA"
EN_TO_DAV = "KnoxDevelopers/English-to-Taita-language-translation-LoRA"
EN_TO_GUZ = "KnoxDevelopers/English-to-Kisii-language-translation-LoRA"
EN_TO_MER = "KnoxDevelopers/English-to-Meru-language-translation-LoRA"
EN_TO_KLN = "KnoxDevelopers/English-to-Kalenjin-language-translation-LoRA"
EN_TO_EBU = "KnoxDevelopers/English-to-Embu-language-translation-LoRA"
EN_TO_MAS = "KnoxDevelopers/English-to-Maasai-language-translation-LoRA"

print("[*] Loading base tokenizer and model...")
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_ID)

base_model = AutoModelForSeq2SeqLM.from_pretrained(
    BASE_MODEL_ID,
    tie_word_embeddings=False
)

base_model.resize_token_embeddings(256205)

if hasattr(base_model, "config"):
    base_model.config.ensure_weight_tying = True

print("[*] adding adapters...")
model = PeftModel.from_pretrained(base_model, EN_TO_KIK, adapter_name="en_to_kik")
model.load_adapter(EN_TO_LUO, adapter_name="en_to_luo")
model.load_adapter(EN_TO_KAM, adapter_name="en_to_kam")
model.load_adapter(EN_TO_DAV, adapter_name="en_to_dav")
model.load_adapter(EN_TO_GUZ, adapter_name="en_to_guz")
model.load_adapter(EN_TO_MER, adapter_name="en_to_mer")
model.load_adapter(EN_TO_KLN, adapter_name="en_to_kln")
model.load_adapter(EN_TO_EBU, adapter_name="en_to_ebu")
model.load_adapter(EN_TO_MAS, adapter_name="en_to_mas")

device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)
model.eval()


def get_safe_token_id(lang_code, fallback_code="kik_Latn"):
    token_id = tokenizer.convert_tokens_to_ids(lang_code)
    max_vocab_limit = base_model.config.vocab_size
    if token_id is None or token_id == tokenizer.unk_token_id or token_id >= max_vocab_limit:
        token_id = tokenizer.convert_tokens_to_ids(fallback_code)
    return token_id


MAX_CHARACTER_LIMIT = 400
BANNED_WORDS = ["offensive_placeholder"]


def programmatic_guardrails(text):
    text_clean = text.strip()
    if not text_clean:
        return False, "⚠️ Please enter a valid sentence to translate."
    if len(text_clean) > MAX_CHARACTER_LIMIT:
        return False, f"⚠️ Input exceeds the safety limit of {MAX_CHARACTER_LIMIT} characters."
    for word in BANNED_WORDS:
        if word in text_clean.lower():
            return False, "🛑 Safety Violation: Input violates our translation safety policy."
    return True, text_clean


def translate_interface(source_text, direction):
    is_safe, sanitized_input = programmatic_guardrails(source_text)
    if not is_safe:
        return sanitized_input

    try:
        tokenizer.src_lang = "eng_Latn"
        inputs = tokenizer(sanitized_input, return_tensors="pt").to(device)

        if direction == "English to Kikuyu":
            model.set_adapter("en_to_kik")
            target_lang_id = get_safe_token_id("kik_Latn")
        elif direction == "English to Luo":
            model.set_adapter("en_to_luo")
            target_lang_id = get_safe_token_id("luo_Latn")
        elif direction == "English to Kikamba":
            model.set_adapter("en_to_kam")
            target_lang_id = get_safe_token_id("kam_Latn")
        elif direction == "English to Taita":
            model.set_adapter("en_to_dav")
            target_lang_id = get_safe_token_id("dav_Latn")
        elif direction == "English to Kisii":
            model.set_adapter("en_to_guz")
            target_lang_id = get_safe_token_id("guz_Latn")
        elif direction == "English to Meru":
            model.set_adapter("en_to_mer")
            target_lang_id = get_safe_token_id("mer_Latn")
        elif direction == "English to Kalenjin":
            model.set_adapter("en_to_kln")
            target_lang_id = get_safe_token_id("kln_Latn")
        elif direction == "English to Embu":
            model.set_adapter("en_to_ebu")
            target_lang_id = get_safe_token_id("ebu_Latn")
        elif direction == "English to Maasai":
            model.set_adapter("en_to_mas")
            target_lang_id = get_safe_token_id("mas_Latn")
        else:
            return "Invalid translation direction selected."

        with torch.no_grad():
            generated_tokens = model.generate(
                **inputs,
                forced_bos_token_id=target_lang_id,
                max_length=512,
                num_beams=4,
                early_stopping=True
            )

        return tokenizer.decode(generated_tokens[0], skip_special_tokens=True)
    except Exception as e:
        return f"An internal error occurred during generation: {str(e)}"


custom_theme = gr.themes.Soft(
    font=[gr.themes.GoogleFont("Arial"), "sans-serif"]
)

description_html = """
<div style='text-align: center;'>
    <h1>Multilingual Kenyan Language Translator</h1>
    <p>Translate English into <b>Kikuyu, Luo, Kikamba, Taita, Kisii, Meru, Kalenjin, Embu and Maasai</b> using fine-tuned Meta NLLB-200 LoRA adapters.</p>
    <p>Trained by <a href="https://knoxdevelopers.com/" target="_blank">Knox Systems Developers</a></p>
</div>
"""

with gr.Blocks(theme=custom_theme) as demo:
    gr.HTML(description_html)

    direction_selector = gr.Radio(
        choices=[
            "English to Kikuyu",
            "English to Luo",
            "English to Kikamba",
            "English to Taita",
            "English to Kisii",
            "English to Meru",
            "English to Kalenjin",
            "English to Embu",
            "English to Maasai"
        ],
        value="English to Kikuyu",
        label="Translation Direction"
    )

    with gr.Row():
        with gr.Column():
            input_box = gr.Textbox(
                label="Source Input Text",
                placeholder="Type your English text here...",
                lines=4
            )
            submit_btn = gr.Button("Translate Text", variant="primary")

        with gr.Column():
            output_box = gr.Textbox(
                label="Translated Output",
                interactive=False,
                lines=4
            )

    submit_btn.click(
        fn=translate_interface,
        inputs=[input_box, direction_selector],
        outputs=output_box
    )

    gr.Examples(
        examples=[
            ["The children are playing outside near the tree.", "English to Kikuyu"],
            ["Where is the market? I need to buy some food.", "English to Luo"],
            ["The children are playing outside near the tree.", "English to Kikamba"],
            ["We will meet tomorrow morning.", "English to Taita"],
            ["Please help me carry this bag.", "English to Kisii"],
            ["The children are playing outside near the tree.", "English to Meru"],
            ["Where is the market? I need to buy some food.", "English to Kalenjin"],
            ["The children are playing outside near the tree.", "English to Embu"],
            ["Where is the market? I need to buy some food.", "English to Maasai"]
        ],
        inputs=[input_box, direction_selector]
    )

demo.launch()