---
title: Transformer Internals
sdk: gradio
sdk_version: 5.9.1
app_file: app.py
python_version: "3.10"
pinned: false
license: mit
colorFrom: blue
colorTo: purple
---

# transformer-internals

What an API can't show you: attention heads, the logit lens, and the full
next-token distribution from a locally-loaded transformer.

**Live Space:** _link goes here once deployed_
**Screenshot:** _`docs/screenshot.png` goes here_

The whole app runs one forward pass of **GPT-2 small (124M)** per input on
CPU and feeds every chart on the page from the same run.

## What each visualisation shows

1. **Input.** A textarea with a few presets. GPT-2 tokenizes with BPE, so
   leading spaces are shown as `·` and newlines as `⏎` — the actual tokens
   the model sees.

2. **Attention.** Two views over the 12 layers × 12 heads:
   - a single-head heatmap with tokens on both axes;
   - a small-multiples grid of all 12 heads for a chosen layer. Distinct
     patterns — previous-token heads, positional heads, delimiter heads —
     become visible immediately.

3. **Logit lens.** At every layer we take the residual-stream vector at the
   final position, apply the final layer norm, and project it through the
   unembedding matrix. Reads as the model changing its mind with depth.

4. **Next-token distribution.** The real softmax over the full
   50,257-token vocabulary, top-20 as a bar chart, with full-vocabulary
   entropy. Most APIs return five logprobs at best.

5. **Hidden-state trajectory.** For a selected token, the L2 norm of the
   residual stream across depth, and cosine similarity to the token's own
   final-layer representation. Shows where the token's meaning settles.

## What this is, and isn't

- **The model.** GPT-2 small — 124M parameters, released 2019. It is **not**
  the model behind Karrou's agent, which is a ~550B-parameter model served
  over an API whose internals no one outside the provider can see. That is
  exactly why this project uses a model small enough to load and inspect.
- **Attention weights are not explanations.** See Jain & Wallace 2019,
  *Attention Is Not Explanation*, and the follow-up debate. Interesting
  patterns here are hypotheses, not proofs.
- **The logit lens is an approximation.** Intermediate layers were never
  trained to be decodable through the final unembedding. See nostalgebraist,
  *interpreting GPT: the logit lens* (2020).

## Running it locally

```bash
pip install -r requirements.txt
python app.py
```

The first run downloads GPT-2 small (~500MB) from the Hugging Face hub.

## Deploying to a Space

This repo is the source of truth. To deploy to a Hugging Face Space, push
this repo to a Space with `sdk: gradio` (the frontmatter at the top of this
README is what the Space reads for its config).
