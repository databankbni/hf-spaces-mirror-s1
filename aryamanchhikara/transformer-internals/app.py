"""
Transformer Internals — a Gradio app that opens up GPT-2 small (124M).

The model is loaded once at import time, on CPU, and the same forward pass
feeds every visualisation on the page.
"""

from __future__ import annotations

import math

import gradio as gr
import numpy as np
import plotly.graph_objects as go
import torch
import torch.nn.functional as F
from plotly.subplots import make_subplots
from transformers import GPT2LMHeadModel, GPT2Tokenizer

MODEL_NAME = "gpt2"

tokenizer = GPT2Tokenizer.from_pretrained(MODEL_NAME)
# Don't bake output_attentions/output_hidden_states into the config — that
# makes transformers warn about `return_dict_in_generate` even when we never
# call .generate(). Pass them per forward call instead (see run_model).
model = GPT2LMHeadModel.from_pretrained(MODEL_NAME)
model.eval()

NUM_LAYERS = model.config.n_layer  # 12
NUM_HEADS = model.config.n_head    # 12
VOCAB_SIZE = model.config.vocab_size  # 50257
MAX_ENTROPY = math.log(VOCAB_SIZE)

PRESETS = [
    "The Eiffel Tower is located in the city of",
    "Aryaman is a machine learning engineer who builds AI agents at",
    "The capital of France is",
    "Once upon a time, in a land far, far",
    "def fibonacci(n):\n    if n < 2:\n        return",
]

DEFAULT_TEXT = PRESETS[0]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def display_token(tok: str) -> str:
    """Make BPE tokens human-readable while preserving their identity.

    GPT-2 uses `Ġ` to mark a leading space and `Ċ` to mark a newline. Show
    those as `·` and `⏎` so the segmentation stays visible.
    """
    return tok.replace("Ġ", "·").replace("Ċ", "⏎")


def run_model(text: str):
    """Run one forward pass and package the results the UI needs."""
    text = text if text.strip() else DEFAULT_TEXT
    enc = tokenizer(text, return_tensors="pt")
    input_ids = enc["input_ids"]
    with torch.no_grad():
        outputs = model(
            **enc,
            output_attentions=True,
            output_hidden_states=True,
        )
    token_strs = [
        display_token(t)
        for t in tokenizer.convert_ids_to_tokens(input_ids[0])
    ]
    # Number each token position to disambiguate repeats on the axes.
    labels = [f"{i}:{t}" for i, t in enumerate(token_strs)]
    return {
        "text": text,
        "tokens": token_strs,
        "labels": labels,
        "attentions": tuple(a.detach() for a in outputs.attentions),
        "hidden_states": tuple(h.detach() for h in outputs.hidden_states),
        "logits": outputs.logits.detach(),
    }


# ---------------------------------------------------------------------------
# 2. Attention
# ---------------------------------------------------------------------------

def single_head_attn(cache, layer: int, head: int):
    if cache is None:
        return go.Figure()
    attn = cache["attentions"][int(layer)][0, int(head)].cpu().numpy()
    labels = cache["labels"]
    fig = go.Figure(
        data=go.Heatmap(
            z=attn,
            x=labels,
            y=labels,
            colorscale="Blues",
            zmin=0.0,
            zmax=1.0,
            colorbar=dict(title="weight"),
            hovertemplate="query: %{y}<br>key: %{x}<br>weight: %{z:.3f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"Layer {int(layer)}, Head {int(head)} — attention weights (query → key)",
        xaxis=dict(title="key (attended to)", tickangle=-45),
        yaxis=dict(title="query (attending from)", autorange="reversed"),
        height=520,
        margin=dict(l=80, r=40, t=60, b=100),
    )
    return fig


def head_grid(cache, layer: int):
    if cache is None:
        return go.Figure()
    layer = int(layer)
    labels = cache["labels"]
    rows, cols = 3, 4
    fig = make_subplots(
        rows=rows,
        cols=cols,
        subplot_titles=[f"Head {h}" for h in range(NUM_HEADS)],
        horizontal_spacing=0.04,
        vertical_spacing=0.08,
    )
    for h in range(NUM_HEADS):
        r = h // cols + 1
        c = h % cols + 1
        attn = cache["attentions"][layer][0, h].cpu().numpy()
        fig.add_trace(
            go.Heatmap(
                z=attn,
                x=labels,
                y=labels,
                colorscale="Blues",
                zmin=0.0,
                zmax=1.0,
                showscale=False,
                hovertemplate=f"head {h}<br>query: %{{y}}<br>key: %{{x}}<br>w: %{{z:.3f}}<extra></extra>",
            ),
            row=r,
            col=c,
        )
        fig.update_yaxes(autorange="reversed", showticklabels=False, row=r, col=c)
        fig.update_xaxes(showticklabels=False, row=r, col=c)
    fig.update_layout(
        title=f"Layer {layer} — all 12 heads",
        height=720,
        margin=dict(l=20, r=20, t=60, b=20),
    )
    return fig


# ---------------------------------------------------------------------------
# 3. Logit lens
# ---------------------------------------------------------------------------

def logit_lens_table(cache, top_k: int):
    """Project every layer's final-position hidden state through ln_f + lm_head."""
    if cache is None:
        return []
    top_k = int(top_k)
    ln_f = model.transformer.ln_f
    lm_head = model.lm_head
    rows = []
    with torch.no_grad():
        for layer_idx, h in enumerate(cache["hidden_states"]):
            last = h[0, -1, :]
            logits = lm_head(ln_f(last))
            probs = F.softmax(logits, dim=-1)
            top = torch.topk(probs, top_k)
            cells = [
                f"{tokenizer.decode([tid.item()])!r}  ({p.item() * 100:.1f}%)"
                for tid, p in zip(top.indices, top.values)
            ]
            layer_label = "embed" if layer_idx == 0 else f"layer {layer_idx}"
            rows.append([layer_label] + cells)
    return rows


def logit_lens_headers(top_k: int) -> list[str]:
    return ["depth"] + [f"#{i + 1}" for i in range(int(top_k))]


# ---------------------------------------------------------------------------
# 4. Next-token distribution
# ---------------------------------------------------------------------------

def next_token_distribution(cache, top_n: int = 20):
    if cache is None:
        return go.Figure(), ""
    logits = cache["logits"][0, -1, :]
    probs = F.softmax(logits, dim=-1)
    top = torch.topk(probs, int(top_n))
    tokens = [tokenizer.decode([tid.item()]) for tid in top.indices]
    values = top.values.cpu().numpy()

    # Bar chart: highest-probability token at the top.
    fig = go.Figure(
        data=go.Bar(
            x=values[::-1],
            y=[repr(t) for t in tokens[::-1]],
            orientation="h",
            marker_color="steelblue",
            hovertemplate="%{y}: %{x:.4f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"Top-{int(top_n)} next-token probabilities (real softmax over {VOCAB_SIZE:,} tokens)",
        xaxis=dict(title="probability", range=[0, float(values.max()) * 1.05]),
        yaxis=dict(title=""),
        height=520,
        margin=dict(l=140, r=40, t=60, b=60),
    )

    # Full-vocab entropy.
    entropy = -(probs * torch.log(probs.clamp_min(1e-12))).sum().item()
    entropy_str = (
        f"**Entropy over the full 50,257-token vocabulary:** "
        f"{entropy:.3f} nats  "
        f"(uniform would be {MAX_ENTROPY:.3f} nats; a one-hot distribution would be 0)."
    )
    return fig, entropy_str


# ---------------------------------------------------------------------------
# 5. Hidden-state trajectory
# ---------------------------------------------------------------------------

def trajectory(cache, token_idx):
    if cache is None or token_idx is None:
        return go.Figure()
    token_idx = int(token_idx)
    hs = cache["hidden_states"]
    vecs = [h[0, token_idx, :] for h in hs]
    final = vecs[-1]
    norms = [float(v.norm().item()) for v in vecs]
    cos = [
        float(F.cosine_similarity(v.unsqueeze(0), final.unsqueeze(0)).item())
        for v in vecs
    ]
    depths = list(range(len(vecs)))
    labels = ["embed"] + [f"L{i}" for i in range(1, len(vecs))]

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=(
            "L2 norm of the residual stream at this position",
            "Cosine similarity to the final-layer representation",
        ),
        horizontal_spacing=0.12,
    )
    fig.add_trace(
        go.Scatter(
            x=depths, y=norms, mode="lines+markers",
            line=dict(color="steelblue"), name="L2 norm",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=depths, y=cos, mode="lines+markers",
            line=dict(color="darkorange"), name="cosine sim",
        ),
        row=1, col=2,
    )
    fig.update_xaxes(tickmode="array", tickvals=depths, ticktext=labels, row=1, col=1)
    fig.update_xaxes(tickmode="array", tickvals=depths, ticktext=labels, row=1, col=2)
    fig.update_yaxes(title_text="‖h‖₂", row=1, col=1)
    fig.update_yaxes(title_text="cos(h_ℓ, h_final)", range=[-0.05, 1.05], row=1, col=2)
    token_display = cache["labels"][token_idx]
    fig.update_layout(
        title=f"Trajectory of token {token_display} through the residual stream",
        showlegend=False,
        height=420,
        margin=dict(l=60, r=40, t=80, b=60),
    )
    return fig


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

INTRO = """
# Transformer Internals

**GPT-2 small (124M), loaded locally, one forward pass per input.** Every
chart on this page comes from the same run of the same model — what would
otherwise be invisible behind an API.
"""

HONESTY = """
## What this is, and isn't

- **The model.** This is GPT-2 small — 124M parameters, released in 2019.
  It is **not** the model behind Karrou's agent, which is a ~550B-parameter
  model served over an API whose internals no one outside the provider can
  see. That is exactly why this project uses a model small enough to load
  and inspect end-to-end.
- **Attention weights are not explanations.** There is a real literature
  arguing attention is not faithful attribution — see Jain & Wallace 2019,
  *Attention Is Not Explanation*, and the follow-up debate. Interesting
  patterns here are hypotheses, not proofs.
- **The logit lens is an approximation.** Intermediate layers were never
  trained to be decodable through the final unembedding matrix, so early
  readouts should be read as suggestive, not literal. See nostalgebraist,
  *interpreting GPT: the logit lens* (2020).
"""


def analyze(text, layer_a, head_a, layer_b, top_k, top_n):
    cache = run_model(text)
    default_token = len(cache["tokens"]) - 1
    fig_single = single_head_attn(cache, layer_a, head_a)
    fig_grid = head_grid(cache, layer_b)
    lens_rows = logit_lens_table(cache, top_k)
    lens_headers = logit_lens_headers(top_k)
    fig_dist, entropy_md = next_token_distribution(cache, top_n)
    fig_traj = trajectory(cache, default_token)
    token_choices = [(t, i) for i, t in enumerate(cache["labels"])]
    return (
        cache,
        fig_single,
        fig_grid,
        gr.update(value=lens_rows, headers=lens_headers),
        fig_dist,
        entropy_md,
        gr.update(choices=token_choices, value=default_token),
        fig_traj,
    )


with gr.Blocks(title="Transformer Internals", theme=gr.themes.Soft()) as app:
    gr.Markdown(INTRO)

    cache_state = gr.State(None)

    with gr.Row():
        text_in = gr.Textbox(
            label="Input text",
            value=DEFAULT_TEXT,
            lines=3,
        )
    gr.Examples(examples=[[p] for p in PRESETS], inputs=[text_in], label="Presets")
    analyze_btn = gr.Button("Analyze", variant="primary")

    # -- Section 2: Attention -------------------------------------------------
    gr.Markdown("## 2. Attention")
    gr.Markdown(
        "GPT-2 small has **12 layers × 12 heads = 144 attention heads**. Each "
        "head produces a matrix showing, for every query token, how much weight "
        "it puts on every earlier token when mixing the residual stream."
    )
    with gr.Tabs():
        with gr.Tab("Single head"):
            with gr.Row():
                layer_a = gr.Slider(0, NUM_LAYERS - 1, value=5, step=1, label="Layer")
                head_a = gr.Slider(0, NUM_HEADS - 1, value=0, step=1, label="Head")
            single_plot = gr.Plot()
        with gr.Tab("All 12 heads for a layer"):
            layer_b = gr.Slider(0, NUM_LAYERS - 1, value=0, step=1, label="Layer")
            gr.Markdown(
                "Look across the twelve heads and specific patterns pop out: "
                "diagonal-below-diagonal (previous-token heads), first-column "
                "stripes (delimiter/BOS heads), broad diagonals (positional "
                "heads). This is the moment the concept usually lands."
            )
            grid_plot = gr.Plot()

    # -- Section 3: Logit lens ------------------------------------------------
    gr.Markdown("## 3. Logit lens — the model changing its mind by depth")
    gr.Markdown(
        "At each layer we take the residual-stream vector at the **final** "
        "position, apply the model's final layer norm, and project it through "
        "the unembedding matrix. That gives an approximate next-token guess "
        "from that layer's point of view. Early layers usually predict generic "
        "high-frequency tokens; deeper layers converge on the actual answer."
    )
    top_k_slider = gr.Slider(3, 10, value=5, step=1, label="Top-k per layer")
    lens_df = gr.Dataframe(
        headers=logit_lens_headers(5),
        interactive=False,
        wrap=True,
    )

    # -- Section 4: Next-token distribution ----------------------------------
    gr.Markdown("## 4. Next-token distribution (the whole thing)")
    gr.Markdown(
        "The real softmax over all 50,257 tokens for the final position. "
        "OpenAI's API returns at most five logprobs; most providers return "
        "none. Here you get the full distribution and its entropy."
    )
    top_n_slider = gr.Slider(5, 40, value=20, step=1, label="How many top tokens to plot")
    dist_plot = gr.Plot()
    entropy_md = gr.Markdown()

    # -- Section 5: Hidden-state trajectory ----------------------------------
    gr.Markdown("## 5. Hidden-state trajectory")
    gr.Markdown(
        "Pick a token and follow its residual-stream vector through the 12 "
        "layers. **L2 norm** shows how much signal has accumulated; **cosine "
        "similarity to the final-layer representation** shows where in depth "
        "the token's meaning actually settles."
    )
    token_dd = gr.Dropdown(label="Token to trace", choices=[], interactive=True)
    traj_plot = gr.Plot()

    # -- Section 6: Honesty --------------------------------------------------
    gr.Markdown(HONESTY)

    # -- Wiring --------------------------------------------------------------
    analyze_btn.click(
        analyze,
        inputs=[text_in, layer_a, head_a, layer_b, top_k_slider, top_n_slider],
        outputs=[cache_state, single_plot, grid_plot, lens_df, dist_plot, entropy_md, token_dd, traj_plot],
    )

    # Re-plot from the cached forward pass when controls move — no re-run.
    for ctrl in (layer_a, head_a):
        ctrl.change(
            single_head_attn,
            inputs=[cache_state, layer_a, head_a],
            outputs=single_plot,
        )
    layer_b.change(head_grid, inputs=[cache_state, layer_b], outputs=grid_plot)
    top_k_slider.change(
        lambda c, k: gr.update(value=logit_lens_table(c, k), headers=logit_lens_headers(k)),
        inputs=[cache_state, top_k_slider],
        outputs=lens_df,
    )
    top_n_slider.change(
        next_token_distribution,
        inputs=[cache_state, top_n_slider],
        outputs=[dist_plot, entropy_md],
    )
    token_dd.change(trajectory, inputs=[cache_state, token_dd], outputs=traj_plot)

    # Prime the UI with the default input so the page isn't empty on load.
    app.load(
        analyze,
        inputs=[text_in, layer_a, head_a, layer_b, top_k_slider, top_n_slider],
        outputs=[cache_state, single_plot, grid_plot, lens_df, dist_plot, entropy_md, token_dd, traj_plot],
    )


if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860)
