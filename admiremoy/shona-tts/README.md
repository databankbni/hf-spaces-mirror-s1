---
title: Mazwi AI
emoji: 🕊️
colorFrom: green
colorTo: yellow
sdk: gradio
app_file: app.py
pinned: false
license: cc-by-nc-4.0
hf_oauth: true
---

# Mazwi AI — chiShona Text-to-Speech

*Mazwi* means "voices / words" in Shona. Type Shona text and hear it spoken in a
community-built Shona voice.

This Space runs a VITS/MMS model fine-tuned on a small, hand-recorded Shona
dataset. It is an early version — the voice improves as more Shona speech is
recorded and the model is retrained.

- Source & recorder: https://github.com/admiremoyo/ShonaTTS
- Base model: `facebook/mms-tts-sna` (CC BY-NC 4.0)

`app.py`'s `MODEL_ID` points at the trained voice model on the Hub.
