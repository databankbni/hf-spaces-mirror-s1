---
title: Toxic Comment Moderator API
emoji: 🛡️
colorFrom: red
colorTo: red
sdk: docker
pinned: false
---

# Toxic Comment Moderator API

A production REST API that classifies toxic content across six categories in real time. Fine tuned on 145k Wikipedia comments from the Jigsaw Toxic Comment Classification dataset. Send text, get back structured JSON telling you what kind of toxicity was detected and how confident the model is.

Built with DistilBERT, FastAPI, and Docker.

---

## Quick Start

**Classify a comment:**

```bash
curl -X POST "https://lakresi-toxic-comment-moderator.hf.space/classify/" \
  -H "Content-Type: application/json" \
  -d '{"text": "You are absolutely worthless and should be ashamed of yourself"}'
```

**Response:**

```json
{
  "is_toxic": true,
  "confidence": 0.9733,
  "categories": {
    "toxic": 0.9733,
    "severe_toxic": 0.0028,
    "obscene": 0.3587,
    "threat": 0.0004,
    "insult": 0.9184,
    "identity_hate": 0.001
  },
  "flagged_categories": ["toxic", "insult"],
  "processing_time_ms": 334.203
}
```

---

## Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | /classify/ | Classify text across six toxicity categories |
| GET | /health | API status and uptime |
| GET | / | Model metadata and endpoint summary |
| GET | /docs | Interactive API documentation |

---

## Categories

The model detects six toxicity labels simultaneously. A comment can be flagged for multiple categories at once.

| Label | Description |
|---|---|
| toxic | General toxic content |
| severe_toxic | Severely toxic, extreme hostility |
| obscene | Obscene or vulgar language |
| threat | Direct threats toward a person |
| insult | Personal insults directed at an individual |
| identity_hate | Hate speech targeting identity groups |

Each label has an individually tuned decision threshold optimized on the validation set rather than a single 0.5 cutoff across all labels.

---

## Performance

| Metric | Value |
|---|---|
| F1 Macro | 0.687 |
| ROC AUC | 0.987 |
| Avg inference latency | ~334ms on CPU |

---

## Known Limitation

Sentences that state an LGBTQ+ identity using an is/are construction (e.g. "My colleague is Gay") are prone to false positive toxic flags regardless of surrounding sentiment. This is a documented artifact of the Jigsaw training data. See the full bias analysis in the GitHub repository.

---

## Links

[GitHub Repository](https://github.com/lloydakresi/toxic_comment_moderator_api) — full technical breakdown, training details, and bias analysis

[Model on HuggingFace](https://huggingface.co/lakresi/toxic-comment-moderator) — model weights, tokenizer, and usage examples
