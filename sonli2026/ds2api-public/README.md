---
title: Dolor Document Translator
emoji: "📚"
colorFrom: gray
colorTo: green
sdk: gradio
sdk_version: "5.44.1"
app_file: app.py
python_version: "3.12"
app_port: 7860
---

# Dolor

Local document translation on Hugging Face Spaces CPU Basic. Dolor uses TranslateGemma 4B Q4_K_M through llama.cpp and processes one PDF at a time with a live queue.

The GGUF model is downloaded at first use from `mradermacher/translategemma-4b-it-GGUF`. You can override `MODEL_REPO` and `MODEL_FILE` in Space variables.

