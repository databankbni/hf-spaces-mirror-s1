# ZeroGPU: `spaces` must be imported before torch. Present on any HF Spaces
# Gradio SDK image regardless of hardware tier; absent locally.
try:
    import spaces

    _HAS_SPACES = True
except ImportError:
    _HAS_SPACES = False

import html

import gradio as gr
import torch
import torch.nn.functional as F
from transformers import AutoModelForMaskedLM, AutoTokenizer

MODEL_ID = "doctolib-lab/doctomodernbert-fr-base"
BASELINE_ID = "camembert-base"  # general-French encoder of similar size

# torch.cuda.is_available() is the single source of truth for whether a CUDA
# device is actually usable here -- true on real GPU hardware, true on a
# properly-attached ZeroGPU Space (its emulation mode makes this report
# correctly outside @spaces.GPU functions too), false on cpu-basic. No need to
# infer it from whether `spaces` merely imported, which says nothing about
# the Space's actual hardware tier.
if torch.cuda.is_available():
    DEVICE = "cuda"
elif torch.backends.mps.is_available():
    DEVICE = "mps"
else:
    DEVICE = "cpu"
print(f"[doctobert-fill-mask] device={DEVICE} has_spaces={_HAS_SPACES}", flush=True)

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForMaskedLM.from_pretrained(MODEL_ID).to(DEVICE).eval()
MASK = tokenizer.mask_token  # ModernBERT -> "[MASK]"

# Similar-size general-French baseline for side-by-side comparison. Its tokenizer
# uses a different mask string ("<mask>"), so inputs are normalized per model.
baseline_tokenizer = AutoTokenizer.from_pretrained(BASELINE_ID)
baseline_model = AutoModelForMaskedLM.from_pretrained(BASELINE_ID).to(DEVICE).eval()


def gpu(fn):
    """@spaces.GPU is documented as effect-free outside real ZeroGPU hardware,
    so it's always safe to apply once `spaces` is importable; no-op locally,
    where the package isn't installed at all."""
    return spaces.GPU(duration=15)(fn) if _HAS_SPACES else fn


def _card(inner: str) -> str:
    return f'<div class="fm">{inner}</div>'


def _err(msg: str) -> str:
    return _card(f'<div class="fm-err">{html.escape(msg)}</div>')


def _render(title: str, text: str, toks: list[str], scores: list[float]) -> str:
    left, right = text.split(MASK, 1)
    top1 = toks[0] if toks else ""
    sentence = (
        f'<span class="fm-txt">{html.escape(left)}</span>'
        + f'<span class="fm-slot">{html.escape(top1) or "·"}</span>'
        + f'<span class="fm-txt">{html.escape(right)}</span>'
    )
    maxp = max(scores) if scores else 1.0
    rows = []
    for r, (t, s) in enumerate(zip(toks, scores), 1):
        w = (s / maxp * 100) if maxp else 0
        rows.append(
            f'<div class="fm-row"><span class="fm-rank">{r}</span>'
            f'<span class="fm-tok">{html.escape(t) or "∅"}</span>'
            f'<div class="fm-bar"><i style="--w:{w:.1f}%"></i></div>'
            f'<span class="fm-pct">{s * 100:.1f}%</span></div>'
        )
    return _card(
        f'<div class="fm-title">{html.escape(title)}</div>'
        f'<div class="fm-sentence">{sentence}</div>'
        '<div class="fm-cap">Top predictions</div>' + "".join(rows)
    )


def _topk(tok, mdl, text: str, top_k: int):
    """Run one masked-LM over `text` (canonical [MASK] normalized to the
    model's own mask token) and return its top-k (tokens, scores)."""
    enc = tok(text.replace(MASK, tok.mask_token), return_tensors="pt").to(DEVICE)
    ids = enc["input_ids"][0]
    pos = (ids == tok.mask_token_id).nonzero(as_tuple=True)[0]
    if pos.numel() == 0:
        return None
    mp = int(pos[0])

    with torch.no_grad():
        logits = mdl(**enc).logits
    probs = F.softmax(logits[0, mp].float(), dim=-1)
    k = min(int(top_k), probs.shape[-1])
    tp, ti = torch.topk(probs, k)
    toks = [
        tok.decode([i], clean_up_tokenization_spaces=False).strip()
        for i in ti.tolist()
    ]
    return toks, [float(x) for x in tp.tolist()]


@gpu
def predict(text: str, top_k: int = 8, compare: bool = False) -> str:
    text = (text or "").strip()
    if not text:
        return _err("Type a sentence first.")
    if MASK not in text:
        return _err(f"Your sentence must contain a {MASK} token.")
    if text.count(MASK) != 1:
        return _err(f"Use exactly one {MASK} token.")

    runs = [(f"{MODEL_ID.split('/')[-1]} · medical French", tokenizer, model)]
    if compare:
        runs.append((f"{BASELINE_ID} · general French, similar size", baseline_tokenizer, baseline_model))

    cards = []
    for title, tok, mdl in runs:
        res = _topk(tok, mdl, text, top_k)
        if res is None:
            cards.append(_err(f"{title}: could not locate the mask after tokenization."))
            continue
        cards.append(_render(title, text, *res))
    return '<div class="fm-stack">' + "".join(cards) + "</div>"


# Palette matches the DoctoBERT Diffusion demo (dark card, accent gradient bars).
CSS = """
#col { max-width: 900px; margin: 0 auto; }
.fm {
  --fg:#e6edf6; --dim:#7d8aa0; --line:#1e2636; --accent:#7aa2ff; --accent2:#b78bff;
  background: linear-gradient(180deg,#0e1420,#0b0f17); border:1px solid var(--line);
  border-radius:14px; padding:18px 20px; color:var(--fg);
  font-family: ui-monospace,"JetBrains Mono",Menlo,Consolas,monospace;
}
.fm-stack { display:flex; flex-direction:column; gap:14px; }
.fm-title { color:var(--accent2) !important; font-size:13px; font-weight:600;
  letter-spacing:.04em; margin-bottom:10px; }
.fm-sentence { font-size:18px; line-height:1.9; margin-bottom:14px; }
/* Gradio's own text color otherwise wins on the bare text nodes; force ours.
   Blue accent matches the DoctoBERT Diffusion demo's prompt text. */
.fm-txt { color: var(--accent) !important; }
.fm-slot { background:linear-gradient(90deg,var(--accent),var(--accent2)); color:#0b0f17;
  font-weight:600; padding:1px 9px; border-radius:6px; }
.fm-cap { color:var(--dim) !important; font-size:12px; text-transform:uppercase;
  letter-spacing:.08em; margin:6px 0 10px; }
.fm-row { display:flex; align-items:center; gap:12px; margin:7px 0; font-size:14px; }
.fm-rank { color:var(--dim) !important; width:1.5em; text-align:right; }
/* Token + probability are the actual content, not secondary metadata -- keep
   them fully bright (and !important, like .fm-txt) regardless of bar size. */
.fm-tok { min-width:130px; color:var(--fg) !important; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap; }
.fm-bar { flex:1; height:10px; background:#182034; border-radius:6px; overflow:hidden; }
.fm-bar>i { display:block; height:100%; width:var(--w);
  background:linear-gradient(90deg,var(--accent),var(--accent2)); border-radius:6px;
  animation: fmgrow .6s cubic-bezier(.2,.8,.2,1); }
@keyframes fmgrow { from { width:0 } }
.fm-pct { color:var(--fg) !important; width:4.5em; text-align:right; font-weight:600; }
.fm-err { color:#ff6b6b !important; }
"""

EXAMPLES = [
    f"Une carence en fer provoque une {MASK}.",
    f"Le patient diabétique de type 2 est traité par {MASK}.",
    f"L'auscultation révèle un {MASK} systolique.",
    f"Une douleur thoracique irradiant vers le bras gauche évoque un {MASK} du myocarde.",
    f"Le patient sous anticoagulants présente un risque accru d'{MASK}.",
]

with gr.Blocks(title="DoctoBERT Fill-Mask") as demo:
    with gr.Column(elem_id="col"):
        gr.Markdown(
            "# 🩺 DoctoBERT Fill-Mask\n"
            "Fill-mask demo of "
            f"[doctolib-lab/doctomodernbert-fr-base](https://huggingface.co/{MODEL_ID}), "
            "a French medical ModernBERT encoder.\n\n"
            f"Write a sentence with a `{MASK}` token and the model predicts the most likely "
            "words, ranked by probability."
        )
        with gr.Row():
            inp = gr.Textbox(
                label=f"Sentence (with {MASK})",
                value=EXAMPLES[0],
                placeholder=f"Le patient souffre d'une {MASK} aiguë.",
                scale=4,
            )
            btn = gr.Button("Predict", variant="primary", scale=1)
        compare = gr.Checkbox(
            value=False, label=f"Compare with {BASELINE_ID} (general French, similar size)"
        )
        with gr.Accordion("Options", open=False):
            topk = gr.Slider(1, 20, value=8, step=1, label="Top-k predictions")
        out = gr.HTML()
        gr.Examples(EXAMPLES, inputs=inp)
        btn.click(predict, [inp, topk, compare], out)
        inp.submit(predict, [inp, topk, compare], out)

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft(), css=CSS, show_error=True)
