---
title: Full Finetuned NLLB Bidirectional Odia German Translator
emoji: 🦜
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 5.50.0
app_file: app.py
pinned: false
license: apache-2.0
short_description: A Gradio-based web interface for full fine-tuned NLLB model
---

# Odia ↔ German Translator

A Gradio-based web interface for a full fine-tuned NLLB model, enabling bidirectional translation between Odia and German.

## Usage
- Enter text in Odia or German and select the source language (or use auto-detection).
- Examples:
  - Odia: "କମ୍ପ୍ୟୁଟର ଆଧାରିତ ଏହି ପରୀକ୍ଷାର ଫଳାଫଳ ୧୫ ଜୁଲାଇରେ ଘୋଷଣା ହେବାର ଆଶା କରାଯାଉଛି।" → German: "Es wird erwartet, dass die Ergebnisse des computergestützten Tests am 15. Juli bekannt gegeben werden."
  - German: "Die derzeitige Wachstumsrate von 6,5 Prozent ist sehr lobenswert." → Odia: "ବର୍ତ୍ତମାନର ୬.୫ ପ୍ରତିଶତ ଅଭିବୃଦ୍ଧି ହାର ଅତ୍ୟନ୍ତ ପ୍ରଶଂସନୀୟ।"

## Model
- Hosted at: [abhinandansamal/nllb-200-distilled-600M-full-finetuned-odia-german-bidirectional](https://huggingface.co/abhinandansamal/nllb-200-distilled-600M-full-finetuned-odia-german-bidirectional)
- Fully Fine-tuned on NLLB for Odia-German translation.

## Requirements
See `requirements.txt` for library versions.

## Notes
- Auto-detection may occasionally misidentify languages. Use the dropdown to manually select "or" (Odia) or "de" (German) for best results.
- Built with Gradio and hosted on Hugging Face Spaces.


Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference