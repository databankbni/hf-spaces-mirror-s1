"""
Myanmar TTS — VoxCPM-0.5B
HuggingFace Spaces (CPU) · Gradio 6+

Fixes applied:
1. CUDA_VISIBLE_DEVICES="" → CPU only
2. torchaudio torchcodec monkey-patch (CPU/ROCm environments)
3. voxcpm core.py warmup monkey-patch → skip broken CPU warmup
4. load with optimize=False + load_denoiser=False
"""

import os, sys, tempfile, time, inspect
import torch, numpy as np, soundfile as sf, gradio as gr

# ── 1. Force CPU BEFORE any torch import ─────────────────────────
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# ── 2. torchaudio torchcodec monkey-patch ────────────────────────
import torchaudio
def _fake_load_with_torchcodec(path, *args, **kwargs):
    return torchaudio.load(path, *args, **kwargs)
def _fake_save_with_torchcodec(path, tensor, sample_rate, *args, **kwargs):
    return torchaudio.save(path, tensor, sample_rate, *args, **kwargs)
torchaudio.load_with_torchcodec  = _fake_load_with_torchcodec
torchaudio.save_with_torchcodec  = _fake_save_with_torchcodec
try:
    torchaudio.set_audio_backend("soundfile")
except Exception:
    pass

# ── 3. voxcpm warmup monkey-patch ────────────────────────────────
#    from_pretrained() calls __init__ which runs a warmup generate()
#    that crashes on CPU with bfloat16 + scaled_dot_product_attention.
#    We patch VoxCPMModel.generate to be a no-op during warmup only.
def _patch_voxcpm_warmup():
    try:
        import voxcpm.model.voxcpm as _vox_mod
        _real_generate = _vox_mod.VoxCPMModel.generate

        _warmup_done = {"done": False}

        def _safe_generate(self, *args, **kwargs):
            if not _warmup_done["done"]:
                print("  ⏩ warmup skipped (CPU patch)")
                _warmup_done["done"] = True
                # Return a silent 0.5s audio as dummy
                sr = getattr(self, "sample_rate", 16000)
                silent = np.zeros(sr // 2, dtype=np.float32)
                return torch.from_numpy(silent)
            return _real_generate(self, *args, **kwargs)

        _vox_mod.VoxCPMModel.generate = _safe_generate
        print("  ✅ warmup patch applied")
    except Exception as e:
        print(f"  ⚠️ warmup patch failed (will try anyway): {e}")

# ── Global model cache ────────────────────────────────────────────
_model = None

def load_model():
    global _model
    if _model is not None:
        return _model

    print("⏳ VoxCPM-0.5B loading on CPU …")

    # Apply warmup patch BEFORE importing VoxCPM
    _patch_voxcpm_warmup()

    from voxcpm import VoxCPM

    # Detect available kwargs
    sig    = inspect.signature(VoxCPM.from_pretrained)
    params = sig.parameters
    print(f"  from_pretrained params: {list(params.keys())}")

    load_kwargs = {}
    if "optimize"      in params: load_kwargs["optimize"]      = False
    if "load_denoiser" in params: load_kwargs["load_denoiser"] = False
    # do NOT pass device= (not supported in 0.5B API)

    print(f"  Loading with: {load_kwargs}")
    _model = VoxCPM.from_pretrained("openbmb/VoxCPM-0.5B", **load_kwargs)
    _model.eval()
    print("✅ Model ready!")
    return _model


def generate_speech(text, cfg_value, inference_steps, ref_audio, ref_text):
    if not text.strip():
        return None, "❌ စာသားထည့်ပါ။"

    try:
        m = load_model()
    except Exception as e:
        return None, f"❌ Model load မအောင်မြင်ပါ:\n{e}"

    start = time.time()
    try:
        # Detect generate() params
        try:
            gen_params = inspect.signature(m.generate).parameters
        except Exception:
            gen_params = {}

        kwargs = dict(text=text, cfg_value=float(cfg_value))
        if "inference_timesteps" in gen_params:
            kwargs["inference_timesteps"] = int(inference_steps)
        elif "inference_steps" in gen_params:
            kwargs["inference_steps"] = int(inference_steps)

        if ref_audio is not None:
            for k in ("prompt_wav_path", "reference_wav_path"):
                if k in gen_params:
                    kwargs[k] = ref_audio
                    break
            if ref_text.strip() and "prompt_text" in gen_params:
                kwargs["prompt_text"] = ref_text.strip()

        with torch.no_grad():
            wav = m.generate(**kwargs)

        if isinstance(wav, torch.Tensor):
            wav = wav.detach().cpu().numpy()
        wav = np.asarray(wav, dtype=np.float32)
        if wav.ndim > 1:
            wav = wav.squeeze()

        sr = getattr(getattr(m, "tts_model", None), "sample_rate", 16000)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        sf.write(tmp, wav, sr)

        elapsed  = time.time() - start
        duration = len(wav) / sr
        rtf      = elapsed / duration if duration > 0 else 0
        return tmp, f"✅ ပြီးပါပြီ!  ⏱ {elapsed:.1f}s │ 🎵 {duration:.1f}s │ RTF {rtf:.2f}"

    except Exception as e:
        import traceback
        return None, f"❌ Error:\n{traceback.format_exc()}"


# ─────────────────────── Gradio UI ────────────────────────────────
CSS   = ".title{text-align:center} .warn{color:#e67e22;font-size:.85em}"
THEME = gr.themes.Soft(primary_hue="purple")

with gr.Blocks(title="🇲🇲 Myanmar TTS — VoxCPM-0.5B") as demo:

    gr.Markdown("# 🇲🇲 Myanmar TTS — VoxCPM-0.5B\n**CPU Mode · Tokenizer-Free**",
                elem_classes="title")

    with gr.Tabs():
        with gr.Tab("🎙️ TTS"):
            with gr.Row():
                with gr.Column(scale=3):
                    txt   = gr.Textbox(
                        label="📝 စာသား (Myanmar / English)",
                        placeholder=(
                            "မင်္ဂလာပါ၊ ဒီနေ့ ကျန်းမာသလား?\n"
                            "Voice design: (gentle female)မင်္ဂလာပါ"
                        ),
                        lines=5,
                    )
                    cfg   = gr.Slider(1.0, 3.5, 2.0, step=0.1, label="🌡️ CFG",
                                      info="နည်း=လွတ်လပ် │ များ=တိကျ")
                    steps = gr.Slider(5, 20, 8, step=1,
                                      label="⚙️ Steps (CPU: 8 recommended)")
                    btn   = gr.Button("🔊 Generate", variant="primary", size="lg")
                with gr.Column(scale=2):
                    out_audio  = gr.Audio(label="🎧 Output", type="filepath")
                    out_status = gr.Textbox(label="ℹ️ Status", lines=3, interactive=False)

            gr.Markdown("⚠️ CPU မိုလို့ steps 8 → ~25–50s ကြာနိုင်သည်။", elem_classes="warn")
            btn.click(generate_speech,
                      [txt, cfg, steps, gr.State(None), gr.State("")],
                      [out_audio, out_status])

        with gr.Tab("🔁 Voice Cloning"):
            gr.Markdown("⚠️ CPU + 0.5B တွင် voice cloning error ဖြစ်နိုင်သည်။",
                        elem_classes="warn")
            with gr.Row():
                with gr.Column(scale=3):
                    c_txt   = gr.Textbox(label="📝 စာသား", lines=4,
                                         placeholder="နောက်ဆုံး သတင်းများကို နားထောင်ကြပါ။")
                    c_ref   = gr.Audio(label="🎤 Reference Audio (3–10s)",
                                       type="filepath", sources=["upload", "microphone"])
                    c_rtxt  = gr.Textbox(label="📄 Reference Transcript (optional)", lines=2)
                    c_cfg   = gr.Slider(1.0, 3.5, 2.0, step=0.1, label="🌡️ CFG")
                    c_steps = gr.Slider(5, 20, 8, step=1, label="⚙️ Steps")
                    c_btn   = gr.Button("🔊 Clone & Generate", variant="primary", size="lg")
                with gr.Column(scale=2):
                    c_audio  = gr.Audio(label="🎧 Cloned Output", type="filepath")
                    c_status = gr.Textbox(label="ℹ️ Status", lines=3, interactive=False)

            c_btn.click(generate_speech,
                        [c_txt, c_cfg, c_steps, c_ref, c_rtxt],
                        [c_audio, c_status])

    gr.Markdown(
        "---\n"
        "**Model:** [openbmb/VoxCPM-0.5B](https://huggingface.co/openbmb/VoxCPM-0.5B) · Apache-2.0  \n"
        "Voice design — text ရှေ့တွင် `(ဖော်ပြချက်)` ထည့်ပါ: `(gentle female)မင်္ဂလာပါ`"
    )

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        theme=THEME,
        css=CSS,
        max_threads=1,
        ssr_mode=False,
    )
