---
title: Employee Attrition & Sentiment AI
emoji: 🔬
colorFrom: indigo
colorTo: blue
sdk: gradio
app_file: app.py
python_version: "3.11"
pinned: false
license: mit
---

# Real-Time Explainable AI Platform for Employee Sentiment Analysis and Attrition Prediction

Two trained deep-learning models served with Gradio.

| Tab | Model | Input | Output |
|-----|-------|-------|--------|
| Attrition prediction | FT-Transformer (PyTorch) | 27 HR fields, 3 columns of 9 | Stay / Leave, confidence, risk vs average, per-feature drivers |
| Review sentiment | BiLSTM (TensorFlow/Keras) | Free-text review | Positive / Negative, confidence, per-word drivers |

## Files in this Space
```
app.py                         # the Gradio application
requirements.txt               # pinned dependencies
ft_transformer_attrition.pth   # PyTorch checkpoint (weights + config + feature names)
ft_transformer_scaler.pkl      # StandardScaler used at training time
bilstm_sentiment_model.keras   # Keras model (native format)
bilstm_sentiment_model.h5      # Keras model (legacy fallback)
bilstm_tokenizer.pkl           # Keras tokenizer
bilstm_label_map.pkl           # {0: 'Negative', 1: 'Positive'}
```

## Known issue: the attrition checkpoint is majority-biased

The checkpoint records `best_epoch = 2`. Early stopping monitored validation **accuracy**
on a target where roughly 84% of employees stay, so the epoch that maximised accuracy is
one where the network leans towards always predicting the majority class.

Measured behaviour of the saved weights:

- An average employee (every feature at its training mean) scores **41.1%** probability of leaving.
- Moving any single feature across its full range shifts the probability by at most about 5 points.
- Across 200 random profiles, only **4%** cross the naive 0.50 threshold.

The model still **ranks** employees correctly. Overtime raises risk, higher income and longer
tenure lower it. The app therefore handles the bias in two honest ways.

1. **Risk relative to an average employee**, in percentage points. This is the most useful number.
2. **An exposed decision threshold** (default 0.47), so an HR user can trade precision for recall.

Neither device alters the model. The real fix is to retrain with early stopping on validation
**F1 or ROC-AUC** instead of accuracy, or to apply class weighting. This is exactly the
"threshold optimisation and cost-sensitive learning" listed as future work in the dissertation.

## Hidden inputs
Stock Option Level, Daily Rate and Number of Companies Worked are removed from the interface.
The trained network has a **fixed 30-input layer**, so they cannot be dropped from the tensor
without retraining. They are held at their training-set mean, which becomes exactly `0.0` after
scaling, so they are neutral and are excluded from the explanation.

## How the explanations work
- **Attrition**: signed occlusion. Each feature is reset to its training average, the model is
  re-run, and the movement in the output logit is recorded. Up means the value pushes towards
  leaving, down means it pushes towards staying. 31 forward passes, sub-second on CPU.
- **Sentiment**: leave-one-word-out. Each word is removed in turn and the change in predicted
  positivity is recorded.

Both give **direction**, not just magnitude, which raw attention weights cannot.

## How predictions stay faithful to training
- Attrition: features are placed in the exact saved order, categorical fields are label-encoded
  with the same alphabetical mapping `LabelEncoder` produced, and the original `StandardScaler`
  is applied. The architecture is rebuilt from the checkpoint's own `model_config` and loaded
  with a strict `load_state_dict`.
- Sentiment: the training text cleaner (lowercase, strip URLs and emoji and punctuation, drop
  NLTK stopwords, WordNet lemmatize) is reproduced exactly, and text is encoded directly from the
  tokenizer's `word_index` with `maxlen=80`, `padding='post'`, `truncating='post'`.

## Deploy
1. Create a new Space, choosing the Gradio SDK.
2. Upload every file listed above, keeping the model artefacts at the repo root next to `app.py`.
3. The Space builds automatically and launches `app.py`.

## Troubleshooting
- **BiLSTM fails to load** with a Keras version error: the `.keras` file was saved with a specific
  TensorFlow version. Match `tensorflow-cpu` in `requirements.txt` to the training version. The app
  already falls back from `.keras` to `.h5` automatically.
- **Scaler version warning**: `scikit-learn` is pinned to `1.6.1`, the version that produced the scaler.
