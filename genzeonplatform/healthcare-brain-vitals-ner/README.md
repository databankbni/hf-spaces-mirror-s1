---
title: Healthcare Brain Vitals NER
emoji: 🩺
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 6.20.0
app_file: app.py
short_description: Extract vital sign entities from text
python_version: "3.12"
startup_duration_timeout: 30m
---

# Healthcare Brain Vitals NER

Extract vital sign and measurement entities from unstructured clinical text using
[genzeonplatform/healthcare-brain-vitals-ner](https://huggingface.co/genzeonplatform/healthcare-brain-vitals-ner),
a Bio_ClinicalBERT fine-tuned for 15 vital sign entity types: blood pressure,
heart rate, respiratory rate, temperature, SpO2, weight, height, BMI, pain score,
GCS, blood glucose, vital date, vital time, measurement unit, and measurement value.

Paste a nursing note, triage assessment, or vital sign flowsheet and the model
highlights vital sign spans in-text, with a summary table of each extracted
entity and its confidence score.
