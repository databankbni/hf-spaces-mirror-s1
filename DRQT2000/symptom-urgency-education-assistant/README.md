---
title: Chief Complaint Triage Education Assistant
sdk: gradio
sdk_version: 6.20.0
app_file: app.py
pinned: false
short_description: A classroom zero-shot text-classification demonstration.
preload_from_hub:
  - facebook/bart-large-mnli
---

# Chief Complaint Triage Education Assistant

This application is a classroom demonstration of text classification with a
pretrained Transformer. It places a fictional or de-identified symptom
description into one broad educational urgency category.

**This is not medical advice, a diagnosis, a clinical triage tool, or a medical
device. Do not use it to make decisions about a real person's care.**

## Task and model

- *Task:* Zero-shot text classification
- *Model:* [`facebook/bart-large-mnli`](https://huggingface.co/facebook/bart-large-mnli)
- *Interface:* Gradio

The model compares three candidate labels for prompt evaluation, routine
follow-up, and lower-urgency self-care/monitoring. A short phrase list can
produce an emergency-warning category before model inference, while invalid or
low-confidence results return an uncertain category.

## How to use the application

1. Enter at least six words describing a fictional or de-identified symptom
   scenario.
2. Do not include names, dates of birth, addresses, medical-record numbers, or
   other identifying information.
3. Select **Classify example** and review the educational category, explanation,
   model score, and disclaimer.

The model score only compares the three candidate labels. It is not the
probability of an emergency or the probability that the result is medically
correct.

## Output categories

- **U1:** Emergency warning signs
- **U2:** Prompt medical evaluation
- **U3:** Routine medical follow-up
- **U4:** General self-care and monitoring
- **U5:** Uncertain; professional guidance recommended

U1 and U2 display fixed contact information for local emergency services,
**911**, the **988 Suicide & Crisis Lifeline**, and **Poison Help at
1-800-222-1222**. Outside the United States, users should use the appropriate
local emergency, crisis, or poison service.

## Limitations

- BART is a general-language model, not a clinical triage model.
- The warning-phrase and negation rules are intentionally short and incomplete.
- Misspellings, unusual wording, missing context, or model errors can change the
  output.
- A missing warning phrase never proves that a situation is safe.
- The application has not been clinically validated.

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

## Files

- `app.py` — Gradio interface and model call
- `safety_rules.py` — category rules, warning phrases, and fixed contact numbers
- `requirements.txt` — Python dependencies
- `README.md` — project and Space documentation

## Safety references

- [MedlinePlus: Recognizing medical emergencies](https://medlineplus.gov/ency/article/001927.htm)
- [988 Suicide & Crisis Lifeline](https://988lifeline.org/)
- [Poison Help](https://www.poisonhelp.org/)
