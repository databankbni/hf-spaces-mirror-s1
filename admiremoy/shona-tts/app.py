from typing import Optional

import torch
import gradio as gr
from transformers import VitsModel, AutoTokenizer

# Your trained Shona voice model on the Hugging Face Hub (private repo —
# the Space reads it via its HF_TOKEN secret). The deploy cell injects
# the real id; edit here if you retrain to a new repo.
MODEL_ID = "admiremoy/shona-tts-voice-v1"

MAX_CHARS = 250  # keep generations short — no long scripted messages

# Words that should never be synthesized. Add Shona/English entries
# (lowercase); any input containing one is refused.
BLOCKLIST: list[str] = []

model = VitsModel.from_pretrained(MODEL_ID)
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)


def synth(text, profile: Optional[gr.OAuthProfile]):
    if profile is None:
        raise gr.Error("Pindai kutanga — please sign in (top of the page) to generate audio.")
    text = (text or "").strip()
    if not text:
        raise gr.Error("Nyora chiShona kutanga — please type some Shona text.")
    if len(text) > MAX_CHARS:
        raise gr.Error(f"Chinyorwa chirefu — please keep it under {MAX_CHARS} characters.")
    low = text.lower()
    if any(w in low for w in BLOCKLIST):
        raise gr.Error("Mashoko aya haabvumidzwe — this text is not allowed.")
    inputs = tokenizer(text, return_tensors="pt")
    with torch.no_grad():
        wav = model(**inputs).waveform[0].cpu().numpy()
    return (model.config.sampling_rate, wav)


CSS = """
.gradio-container{
  max-width: 720px !important; margin: 0 auto !important;
  background: linear-gradient(180deg,#f8f2e6 0%,#efe3cd 100%) !important;
  font-family: "Segoe UI", system-ui, -apple-system, Roboto, sans-serif !important;
}
#hero{ text-align:center; padding: 26px 16px 4px; }
.flagbar{
  height:6px; max-width:132px; margin:0 auto 20px; border-radius:6px;
  background:linear-gradient(90deg,#1a7a45 0 25%,#f4b41a 25% 50%,#d8232a 50% 75%,#141414 75% 100%);
}
.emblem{
  width:66px; height:66px; border-radius:50%; margin:0 auto 12px;
  background:radial-gradient(circle at 32% 30%,#ffdd7a,#f4b41a);
  display:flex; align-items:center; justify-content:center; font-size:32px;
  box-shadow:0 8px 22px rgba(244,180,26,.45);
}
.brand{ font-size:36px; font-weight:800; letter-spacing:.5px; color:#241c10; margin:2px 0; }
.brand span{ color:#1a7a45; }
.tagline{ color:#7a6f5d; font-size:15.5px; margin:4px 0 2px; }
.tagline b{ color:#d8232a; font-weight:700; }
.sub{ color:#9a8d76; font-size:13px; margin-top:2px; }

.card{
  background:#fffdf8 !important; border:1px solid #ece0c8 !important;
  border-top:4px solid #f4b41a !important; border-radius:18px !important;
  box-shadow:0 12px 34px rgba(60,40,10,.09) !important; padding:18px !important;
}
.card textarea{ font-size:18px !important; line-height:1.5 !important; }
.speak button{
  background:linear-gradient(180deg,#1e8a4e,#0f5e33) !important; color:#fff !important;
  font-weight:700 !important; font-size:17px !important; border:none !important;
  border-radius:13px !important; padding:14px !important;
  box-shadow:0 8px 18px rgba(26,122,69,.35) !important;
}
.speak button:hover{ filter:brightness(1.08); }

#foot{ text-align:center; color:#8a7d67; font-size:13px; padding:18px 10px 26px; line-height:1.7; }
#foot a{ color:#1a7a45; text-decoration:none; font-weight:600; }
footer{ display:none !important; }
"""

HERO = """
<div id="hero">
  <div class="flagbar"></div>
  <div class="emblem">🕊️</div>
  <div class="brand">Mazwi<span> AI</span></div>
  <div class="tagline">Nyora chiShona, unzwe <b>richitaurwa</b> — type Shona, hear it spoken.</div>
  <div class="sub">Izwi reZimbabwe · chiShona Text-to-Speech</div>
</div>
"""

FOOT = """
<div id="foot">
  ⚠️ Inzwi rakagadzirwa nemushina — this is a <b>synthetic voice</b>, not a real
  recording of any person. Misuse (impersonation, harassment, scams) is
  prohibited and accounts are traceable.<br>
  Yakagadzirwa muZimbabwe · Built in Zimbabwe 🇿🇼 ·
  <a href="https://github.com/admiremoyo/ShonaTTS" target="_blank">Project on GitHub</a>
</div>
"""

with gr.Blocks(css=CSS, title="Mazwi AI — chiShona TTS",
               theme=gr.themes.Soft(primary_hue="green", secondary_hue="yellow")) as demo:
    gr.HTML(HERO)
    gr.LoginButton()
    with gr.Column(elem_classes="card"):
        txt = gr.Textbox(
            label="Chinyorwa (Shona text)",
            placeholder="Semuenzaniso: Mhoro, wakadii nhasi?",
            lines=2,
            value="Mhoro, wakadii nhasi?",
            max_length=MAX_CHARS,
        )
        btn = gr.Button("🔊 Taura · Speak", elem_classes="speak")
        out = gr.Audio(label="Izwi (Listen)")
        gr.Examples(
            examples=[
                "Mhoro, wakadii nhasi?",
                "Ndinoda kudya sadza nenyama.",
                "Zuva rakanaka, mvura iri kunaya.",
                "Maita basa, famba zvakanaka.",
            ],
            inputs=txt,
            label="Mienzaniso (Examples)",
        )
    gr.HTML(FOOT)

    btn.click(synth, inputs=txt, outputs=out)
    txt.submit(synth, inputs=txt, outputs=out)

if __name__ == "__main__":
    demo.launch()
