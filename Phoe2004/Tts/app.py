"""
Voice Studio – Gradio UI for Hugging Face Spaces (CPU-compatible)
Built on top of VoxCPM (https://github.com/OpenBMB/VoxCPM)
"""

from __future__ import annotations
import os, sys, re, warnings
import numpy as np
import soundfile as sf
import gradio as gr
from pathlib import Path

# ── VoxCPM path setup
ROOT = Path(__file__).resolve().parent
VOXCPM_SRC = ROOT / "VoxCPM" / "src"
if str(VOXCPM_SRC) not in sys.path:
    sys.path.insert(0, str(VOXCPM_SRC))

warnings.filterwarnings("ignore", message=".*PySoundFile failed.*")
warnings.filterwarnings("ignore", message=".*librosa.core.audio.*")
warnings.filterwarnings("ignore", message=".*weight_norm is deprecated.*")
warnings.filterwarnings("ignore", message=".*FutureWarning.*")

LOCAL_MODEL_PATH = str(ROOT / "VoxCPM" / "pretrained_models" / "VoxCPM2")
DEFAULT_MODEL_ID = LOCAL_MODEL_PATH if Path(LOCAL_MODEL_PATH).exists() else "openbmb/VoxCPM2"
OUTPUT_DIR = ROOT / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# CPU ထည့်စဉ်းစားပြီး timesteps နည်းချပေးထားတယ်
QUALITY_PRESETS = {
    "Fast (CPU-friendly)": {"inference_timesteps": 4,  "cfg_value": 1.8},
    "Balanced":            {"inference_timesteps": 8,  "cfg_value": 2.0},
    "High Similarity":     {"inference_timesteps": 12, "cfg_value": 2.3},
}

STYLE_PRESETS = {
    "Natural":          "natural spoken delivery, clear and grounded",
    "Deep Reflective":  "deep reflective delivery, calm, philosophical, deliberate, intimate",
    "Warm Storyteller": "warm storyteller delivery, grounded, expressive, gentle pauses",
    "Soft Intimate":    "soft intimate delivery, tender, close, quiet, slow",
    "Documentary":      "documentary narration delivery, deep, composed, deliberate rhythm",
}

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_model_cache: dict = {}
_prompt_cache: dict = {}


def _get_model(model_source: str):
    from voxcpm import VoxCPM
    source = model_source.strip() or DEFAULT_MODEL_ID
    if source not in _model_cache:
        # device="auto" → cuda မရှိရင် mps → မရှိရင် cpu auto fallback
        _model_cache[source] = VoxCPM.from_pretrained(source, device="auto")
    return _model_cache[source]


def _get_prompt_cache(model, ref_path: str, prompt_text):
    key = (ref_path, prompt_text or "")
    if key not in _prompt_cache:
        _prompt_cache[key] = model.tts_model.build_prompt_cache(
            reference_wav=ref_path,
            reference_text=prompt_text or None,
        )
    return _prompt_cache[key]


def _split_text(text: str, max_chars: int = 170) -> list[str]:
    parts = re.compile(r"(?<=[.!?])\s+").split(text.strip())
    chunks, current = [], ""
    for s in parts:
        s = s.strip()
        if not s:
            continue
        if len(s) > max_chars:
            for w in s.split():
                c = f"{current} {w}".strip()
                if current and len(c) > max_chars:
                    chunks.append(current); current = w
                else:
                    current = c
            continue
        c = f"{current} {s}".strip()
        if current and len(c) > max_chars:
            chunks.append(current); current = s
        else:
            current = c
    if current:
        chunks.append(current)
    return chunks


def _tensor_to_numpy(t) -> np.ndarray:
    import torch
    if isinstance(t, torch.Tensor):
        t = t.detach().cpu()
        if t.ndim > 1: t = t.squeeze()
        return t.float().numpy()
    return np.array(t, dtype=np.float32)


def _synthesize(model, prompt_cache, text, timesteps, cfg) -> np.ndarray:
    chunks = _split_text(text)
    if not chunks: raise ValueError("Text is empty.")
    silence = np.zeros(int(model.tts_model.sample_rate * 0.12), dtype=np.float32)
    parts = []
    for i, chunk in enumerate(chunks):
        wav_t, _, _ = model.tts_model.generate_with_prompt_cache(
            target_text=chunk, prompt_cache=prompt_cache,
            inference_timesteps=timesteps, cfg_value=cfg, max_len=2048,
        )
        parts.append(_tensor_to_numpy(wav_t))
        if i < len(chunks) - 1: parts.append(silence)
    return np.concatenate(parts)


def _rewrite_gemini(text, api_key, g_model, style_preset, style_text, target_wpm):
    import requests
    style_desc = style_text.strip() or STYLE_PRESETS.get(style_preset, "natural spoken delivery")
    prompt = (
        f"Rewrite as spoken narration. Style: {style_desc}. "
        f"~{target_wpm} wpm. Return ONLY the rewritten script.\n\nTEXT:\n{text}"
    )
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{g_model}:generateContent?key={api_key}",
        json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def generate_voice(ref_audio, target_text, prompt_text, quality, style_preset,
                   style_text, rewrite_ai, gemini_key, gemini_model, target_wpm,
                   model_source, progress=gr.Progress(track_tqdm=True)):

    if ref_audio is None:   return None, "❌ Reference audio ထည့်ပေးပါ။"
    if not target_text.strip(): return None, "❌ Target text ထည့်ပေးပါ။"

    source_text = " ".join(target_text.strip().split())

    if rewrite_ai:
        if not gemini_key.strip(): return None, "❌ Gemini API key မထည့်ထားဘူး။"
        try:
            progress(0.1, desc="✨ Gemini rewriting…")
            rewritten = _rewrite_gemini(source_text, gemini_key.strip(), gemini_model,
                                        style_preset, style_text, target_wpm)
        except Exception as e: return None, f"❌ Gemini rewrite failed: {e}"
    else:
        rewritten = source_text

    full_text = re.sub(r"\s+", " ", rewritten.replace("\n", " ")).strip()

    try:
        progress(0.2, desc="🔄 Loading model… (ပထမဆုံးတစ်ကြိမ် ကြာနိုင်ပါတယ်)")
        model = _get_model(model_source.strip() or DEFAULT_MODEL_ID)
    except Exception as e: return None, f"❌ Model load failed: {e}"

    cleaned_prompt = " ".join(prompt_text.strip().split()) or None
    try:
        progress(0.4, desc="🎤 Processing reference audio…")
        pcache = _get_prompt_cache(model, str(ref_audio), cleaned_prompt)
    except Exception as e: return None, f"❌ Reference audio failed: {e}"

    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["Balanced"])
    try:
        progress(0.6, desc="🎙️ Generating audio… (CPU မှာ ကြာနိုင်ပါတယ်)")
        wav = _synthesize(model, pcache, full_text,
                          preset["inference_timesteps"], preset["cfg_value"])
    except Exception as e: return None, f"❌ Synthesis failed: {e}"

    progress(0.95, desc="💾 Saving…")
    sr = model.tts_model.sample_rate
    out = OUTPUT_DIR / f"vs_{abs(hash(full_text[:40]))}.wav"
    sf.write(str(out), wav, sr)

    mode = "high similarity" if cleaned_prompt else "quick clone"
    rw_note = f"\n\n**Rewritten:**\n{rewritten}" if rewrite_ai else ""
    status = (
        f"✅ Generated!\n\n"
        f"**Quality:** {quality} | **Mode:** {mode}\n"
        f"**Duration:** {len(wav)/sr:.2f}s | **SR:** {sr} Hz{rw_note}"
    )
    return str(out), status


# ── Gradio UI ─────────────────────────────────────────────────────────────────
with gr.Blocks(title="🎙️ Voice Studio", theme=gr.themes.Soft(primary_hue="violet"),
               css="footer{display:none!important}") as demo:

    gr.Markdown("# 🎙️ Voice Studio\nVoice cloning with **VoxCPM2** · CPU & GPU compatible")

    gr.HTML('<div style="background:#fef9c3;border-left:4px solid #eab308;padding:10px 14px;'
            'border-radius:6px;margin-bottom:12px">⚠️ <b>CPU mode:</b> Generation ကြာနိုင်ပါတယ် '
            '(short text ~1-3 min)။ <b>"Fast (CPU-friendly)"</b> preset ကို ဦးစားပေးသုံးပါ။</div>')

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🎤 Reference Voice")
            ref_audio   = gr.Audio(label="Reference Audio (WAV/MP3, 5–30s)", type="filepath")
            prompt_text = gr.Textbox(label="Reference Transcript (optional)", lines=2,
                                     placeholder="Reference clip ထဲ ပြောတဲ့ text…")
            gr.Markdown("### ✍️ Target Text")
            target_text = gr.Textbox(label="Text to Synthesise", lines=6,
                                     placeholder="ဒီနေရာမှာ synthesise လုပ်ချင်တဲ့ text ထည့်ပါ…")

        with gr.Column(scale=1):
            gr.Markdown("### ⚙️ Settings")
            quality      = gr.Radio(choices=list(QUALITY_PRESETS), value="Fast (CPU-friendly)",
                                    label="Quality Preset")
            style_preset = gr.Dropdown(choices=list(STYLE_PRESETS), value="Natural", label="Style")
            style_text   = gr.Textbox(label="Custom Style (optional)", lines=1,
                                      placeholder="e.g. warm calm podcast voice…")
            model_source = gr.Textbox(label="Model Source", value=DEFAULT_MODEL_ID)

            gr.Markdown("### ✨ Gemini Rewrite (Optional)")
            rewrite_ai  = gr.Checkbox(label="Enable Gemini AI rewrite", value=False)
            with gr.Group(visible=False) as g_group:
                gemini_key   = gr.Textbox(label="Gemini API Key", type="password", placeholder="AIza…")
                gemini_model = gr.Textbox(label="Gemini Model", value=DEFAULT_GEMINI_MODEL)
                target_wpm   = gr.Slider(label="Target WPM", minimum=60, maximum=180, value=105, step=5)
            rewrite_ai.change(lambda x: gr.update(visible=x), rewrite_ai, g_group)

            gr.Markdown("### 🔊 Output")
            gen_btn  = gr.Button("🚀 Generate Voice", variant="primary", size="lg")
            out_audio = gr.Audio(label="Generated Audio", type="filepath")
            status_md = gr.Markdown()

    gr.Markdown("""---
### 📌 Tips
- Reference audio: **5–30 seconds**, clear recording ဖြစ်ဖို့ကြည့်ပါ
- Reference transcript ထည့်ပေးရင် similarity **ပိုကောင်း**ပါတယ်
- CPU မှာ **Fast** preset + text **တို​တို** နဲ့ စသုံးကြည့်ပါ
- Model ပထမဆုံး load မှာ **HF Hub** ကနေ auto download ဆွဲပါတယ်""")

    gen_btn.click(
        fn=generate_voice,
        inputs=[ref_audio, target_text, prompt_text, quality, style_preset,
                style_text, rewrite_ai, gemini_key, gemini_model, target_wpm, model_source],
        outputs=[out_audio, status_md],
    )

if __name__ == "__main__":
    demo.launch()
