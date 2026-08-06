"""
Real-Time Explainable AI Platform for Employee Sentiment Analysis and
Attrition Prediction Using Transformer Models and CNN-BiGRU-Attention
=====================================================================

Two trained models served with Gradio:

  1. FT-Transformer (PyTorch)  -> employee attrition risk from 30 HR features
  2. BiLSTM (TensorFlow/Keras) -> sentiment of an employee review

Preprocessing is reconstructed to EXACTLY match training:
  * Attrition: same 30-feature order, same alphabetical LabelEncoder mapping,
    same StandardScaler.
  * Sentiment: same cleaner (lowercase -> strip urls/emoji/punctuation -> drop
    NLTK stopwords -> WordNet lemmatize), same tokenizer word_index, maxlen=80.

IMPORTANT NOTE ON THE ATTRITION CHECKPOINT
------------------------------------------
The saved checkpoint reports best_epoch = 2. Early stopping monitored validation
ACCURACY on a target where ~84% of employees stay, so the epoch that maximised
accuracy is one where the network leans heavily towards the majority class. As a
result its predicted probability of leaving sits in a narrow band and rarely
exceeds 0.50 on its own.

The model still RANKS employees sensibly (working overtime raises risk, higher
income lowers it), so this app exposes an explicit decision threshold and also
reports risk RELATIVE to an average employee. Neither device changes the model.
Both are disclosed in the interface. The correct long-term fix is to retrain with
early stopping on validation F1 or ROC-AUC rather than accuracy.
"""

import os
import re
import pickle

import numpy as np
import pandas as pd
import gradio as gr

HERE         = os.path.dirname(os.path.abspath(__file__))
FT_PTH       = os.path.join(HERE, "ft_transformer_attrition.pth")
FT_SCALER    = os.path.join(HERE, "ft_transformer_scaler.pkl")
BILSTM_KERAS = os.path.join(HERE, "bilstm_sentiment_model.keras")
BILSTM_H5    = os.path.join(HERE, "bilstm_sentiment_model.h5")
BILSTM_TOK   = os.path.join(HERE, "bilstm_tokenizer.pkl")
BILSTM_LMAP  = os.path.join(HERE, "bilstm_label_map.pkl")

MAX_LEN = 80

APP_TITLE = ("Real-Time Explainable AI Platform for Employee Sentiment Analysis "
             "and Attrition Prediction Using Transformer Models and CNN-BiGRU-Attention")


# ============================================================================ #
#  PART 1 - FT-TRANSFORMER (PyTorch) FOR ATTRITION
# ============================================================================ #
import torch
import torch.nn as nn


class FeatureTokenizer(nn.Module):
    def __init__(self, num_features, d_token):
        super().__init__()
        self.weight = nn.Parameter(torch.empty(num_features, d_token))
        self.bias   = nn.Parameter(torch.empty(num_features, d_token))
        nn.init.xavier_uniform_(self.weight)
        nn.init.zeros_(self.bias)

    def forward(self, x):
        return x.unsqueeze(-1) * self.weight + self.bias


class TransformerBlock(nn.Module):
    def __init__(self, d_token, n_heads, dropout=0.2, ff_factor=4):
        super().__init__()
        self.attention = nn.MultiheadAttention(
            embed_dim=d_token, num_heads=n_heads, dropout=dropout, batch_first=True)
        self.norm1 = nn.LayerNorm(d_token)
        self.norm2 = nn.LayerNorm(d_token)
        self.ffn = nn.Sequential(
            nn.Linear(d_token, d_token * ff_factor), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(d_token * ff_factor, d_token), nn.Dropout(dropout))
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        attn_out, attn_weights = self.attention(
            x, x, x, need_weights=True, average_attn_weights=True)
        x = self.norm1(x + self.dropout(attn_out))
        x = self.norm2(x + self.ffn(x))
        return x, attn_weights


class AttentionPooling(nn.Module):
    def __init__(self, d_token):
        super().__init__()
        self.attention_vector = nn.Linear(d_token, 1)

    def forward(self, x):
        weights = torch.softmax(self.attention_vector(x), dim=1)
        return torch.sum(weights * x, dim=1), weights


class AdvancedFTTransformer(nn.Module):
    def __init__(self, num_features, d_token=64, n_heads=8, n_layers=4, dropout=0.3):
        super().__init__()
        self.tokenizer = FeatureTokenizer(num_features, d_token)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, d_token))
        self.transformer_blocks = nn.ModuleList(
            [TransformerBlock(d_token, n_heads, dropout) for _ in range(n_layers)])
        self.pooling    = AttentionPooling(d_token)
        self.classifier = nn.Sequential(
            nn.Linear(d_token, 256), nn.BatchNorm1d(256), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(256, 128),     nn.BatchNorm1d(128), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(128, 64),      nn.BatchNorm1d(64),  nn.GELU(), nn.Dropout(dropout),
            nn.Linear(64, 1))
        self.attention_maps    = []
        self.pooling_attention = None

    def forward(self, x):
        tokens = self.tokenizer(x)
        cls    = self.cls_token.expand(x.shape[0], -1, -1)
        h      = torch.cat([cls, tokens], dim=1)
        self.attention_maps = []
        for block in self.transformer_blocks:
            h, attn = block(h)
            self.attention_maps.append(attn.detach())
        pooled, pool_w = self.pooling(h)
        self.pooling_attention = pool_w.detach().squeeze(-1)
        return self.classifier(pooled)


with open(FT_SCALER, "rb") as f:
    scaler = pickle.load(f)

ckpt          = torch.load(FT_PTH, map_location="cpu", weights_only=False)
FT_CONFIG     = ckpt["model_config"]
FEATURE_NAMES = list(ckpt.get("feature_names", scaler.feature_names_in_))

ft_model = AdvancedFTTransformer(**FT_CONFIG)
ft_model.load_state_dict(ckpt["model_state_dict"])
ft_model.eval()

TRAIN_MEAN = {n: float(m) for n, m in zip(scaler.feature_names_in_, scaler.mean_)}


CAT_MAPS = {
    "BusinessTravel": {"Non-Travel": 0, "Travel_Frequently": 1, "Travel_Rarely": 2},
    "Department":     {"Human Resources": 0, "Research & Development": 1, "Sales": 2},
    "EducationField": {"Human Resources": 0, "Life Sciences": 1, "Marketing": 2,
                       "Medical": 3, "Other": 4, "Technical Degree": 5},
    "Gender":         {"Female": 0, "Male": 1},
    "JobRole":        {"Healthcare Representative": 0, "Human Resources": 1,
                       "Laboratory Technician": 2, "Manager": 3,
                       "Manufacturing Director": 4, "Research Director": 5,
                       "Research Scientist": 6, "Sales Executive": 7,
                       "Sales Representative": 8},
    "MaritalStatus":  {"Divorced": 0, "Married": 1, "Single": 2},
    "OverTime":       {"No": 0, "Yes": 1},
}

HIDDEN_FEATURES = ["StockOptionLevel", "DailyRate", "NumCompaniesWorked"]

NUMERIC_UI = {
    "Age":                      ("Age (years)", 18, 60, 37, "18 to 60"),
    "DistanceFromHome":         ("Distance From Home (miles)", 1, 29, 9, "1 to 29"),
    "Education":                ("Education Level", 1, 5, 3, "1 Below College to 5 Doctor"),
    "EnvironmentSatisfaction":  ("Environment Satisfaction", 1, 4, 3, "1 Low to 4 Very High"),
    "HourlyRate":               ("Hourly Rate", 30, 100, 66, "30 to 100"),
    "JobInvolvement":           ("Job Involvement", 1, 4, 3, "1 Low to 4 Very High"),
    "JobLevel":                 ("Job Level", 1, 5, 2, "1 to 5"),
    "JobSatisfaction":          ("Job Satisfaction", 1, 4, 3, "1 Low to 4 Very High"),
    "MonthlyIncome":            ("Monthly Income", 1000, 20000, 6500, "1000 to 20000"),
    "MonthlyRate":              ("Monthly Rate", 2000, 27000, 14400, "2000 to 27000"),
    "PercentSalaryHike":        ("Percent Salary Hike (%)", 11, 25, 15, "11 to 25"),
    "PerformanceRating":        ("Performance Rating", 1, 5, 3,
                                 "1 to 5 (training data held only 3 and 4)"),
    "RelationshipSatisfaction": ("Relationship with Current Manager", 1, 4, 3, "1 Low to 4 Very High"),
    "TotalWorkingYears":        ("Total Working Years", 0, 40, 11, "0 to 40"),
    "TrainingTimesLastYear":    ("Training Times Last Year", 0, 6, 3, "0 to 6"),
    "WorkLifeBalance":          ("Work Life Balance", 1, 4, 3, "1 Bad to 4 Best"),
    "YearsAtCompany":           ("Years at Company", 0, 40, 7, "0 to 40"),
    "YearsInCurrentRole":       ("Years in Current Role", 0, 18, 4, "0 to 18"),
    "YearsSinceLastPromotion":  ("Years Since Last Promotion", 0, 15, 2, "0 to 15"),
    "YearsWithCurrManager":     ("Years with Current Manager", 0, 17, 4, "0 to 17"),
}

CAT_UI = {
    "BusinessTravel": ("Business Travel", "Travel_Rarely"),
    "Department":     ("Department", "Research & Development"),
    "EducationField": ("Education Field", "Life Sciences"),
    "Gender":         ("Gender", "Male"),
    "JobRole":        ("Job Role", "Sales Executive"),
    "MaritalStatus":  ("Marital Status", "Married"),
    "OverTime":       ("Works Overtime", "No"),
}

PRETTY = {**{k: v[0] for k, v in NUMERIC_UI.items()},
          **{k: v[0] for k, v in CAT_UI.items()}}

# --- Three balanced columns: exactly 9 fields each (27 visible features) ------ #
COL_1 = ["Age", "Gender", "MaritalStatus", "DistanceFromHome", "Education",
         "EducationField", "Department", "JobRole", "BusinessTravel"]
COL_2 = ["JobLevel", "MonthlyIncome", "MonthlyRate", "HourlyRate", "PercentSalaryHike",
         "OverTime", "TotalWorkingYears", "TrainingTimesLastYear", "PerformanceRating"]
COL_3 = ["YearsAtCompany", "YearsInCurrentRole", "YearsSinceLastPromotion",
         "YearsWithCurrManager", "JobSatisfaction", "EnvironmentSatisfaction",
         "JobInvolvement", "RelationshipSatisfaction", "WorkLifeBalance"]

VISIBLE_FEATURES = COL_1 + COL_2 + COL_3
assert len(COL_1) == len(COL_2) == len(COL_3) == 9
assert sorted(VISIBLE_FEATURES) == sorted(f for f in FEATURE_NAMES if f not in HIDDEN_FEATURES)


def _forward_logits(scaled_batch: np.ndarray) -> np.ndarray:
    x = torch.tensor(scaled_batch, dtype=torch.float32)
    with torch.no_grad():
        return ft_model(x).squeeze(-1).cpu().numpy()


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


# Probability the model assigns to a perfectly average employee (all features at
# the training mean). Used as the reference point for relative risk.
BASELINE_PROB = float(_sigmoid(_forward_logits(np.zeros((1, len(FEATURE_NAMES)), dtype=np.float32))[0]))


def predict_attrition(threshold, *values):
    raw = dict(zip(VISIBLE_FEATURES, values))
    notes = []

    for feat in VISIBLE_FEATURES:
        if feat in NUMERIC_UI:
            _, lo, hi, default, _ = NUMERIC_UI[feat]
            v = raw[feat]
            if v is None or (isinstance(v, str) and not str(v).strip()):
                raw[feat] = default
                notes.append(f"{PRETTY[feat]} was empty, so {default} was used.")
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                raw[feat] = default
                notes.append(f"{PRETTY[feat]} was not a number, so {default} was used.")
                continue
            if v < lo or v > hi:
                v = min(max(v, lo), hi)
                notes.append(f"{PRETTY[feat]} was outside {lo} to {hi} and was clamped to {v:g}.")
            raw[feat] = v

    encoded = {}
    for feat in FEATURE_NAMES:
        if feat in HIDDEN_FEATURES:
            encoded[feat] = TRAIN_MEAN[feat]
        elif feat in CAT_MAPS:
            encoded[feat] = CAT_MAPS[feat][raw[feat]]
        else:
            encoded[feat] = float(raw[feat])

    row    = pd.DataFrame([encoded])[FEATURE_NAMES]
    scaled = scaler.transform(row)

    # batch: row 0 = actual, rows 1..30 = actual with feature j reset to its mean
    batch = np.repeat(scaled, len(FEATURE_NAMES) + 1, axis=0)
    for j in range(len(FEATURE_NAMES)):
        batch[j + 1, j] = 0.0

    logits       = _forward_logits(batch)
    logit_actual = float(logits[0])
    prob         = float(_sigmoid(logit_actual))

    contribs = {f: logit_actual - float(logits[j + 1])
                for j, f in enumerate(FEATURE_NAMES) if f not in HIDDEN_FEATURES}

    toward_leave = sorted([(f, c) for f, c in contribs.items() if c > 1e-6], key=lambda t: -t[1])[:5]
    toward_stay  = sorted([(f, c) for f, c in contribs.items() if c < -1e-6], key=lambda t: t[1])[:5]

    thr = float(threshold)
    if prob >= thr:
        verdict, badge = "LIKELY TO LEAVE THE COMPANY", "#b3261e"
        sub = "The model places this employee above the current decision threshold."
        confidence = prob
    else:
        verdict, badge = "LIKELY TO STAY WITH THE COMPANY", "#1b6b3a"
        sub = "The model places this employee below the current decision threshold."
        confidence = 1.0 - prob

    rel = (prob - BASELINE_PROB) * 100.0
    if   rel >= 6:  band, bcol = "High risk", "#b3261e"
    elif rel >= 2:  band, bcol = "Elevated risk", "#c77700"
    elif rel >= -2: band, bcol = "Around average", "#475467"
    else:           band, bcol = "Low risk", "#1b6b3a"
    rel_txt = f"{rel:+.1f} pts"

    verdict_html = f"""
    <div class="verdict-card" style="border-left:6px solid {badge};">
      <div class="verdict-title" style="color:{badge};">{verdict}</div>
      <div class="verdict-sub">{sub}</div>
      <div class="verdict-metrics">
        <div class="metric"><span class="metric-value">{confidence*100:.1f}%</span>
             <span class="metric-label">Confidence</span></div>
        <div class="metric"><span class="metric-value">{prob*100:.1f}%</span>
             <span class="metric-label">Probability of leaving</span></div>
        <div class="metric"><span class="metric-value" style="color:{bcol};">{rel_txt}</span>
             <span class="metric-label">vs average employee</span></div>
        <div class="metric"><span class="metric-value" style="color:{bcol};">{band}</span>
             <span class="metric-label">Risk band</span></div>
      </div>
      <div class="thr-note">Decision threshold {thr:.2f}. An average employee in the training
      data scores {BASELINE_PROB*100:.1f}%.</div>
    </div>"""

    def rows(items, colour, arrow):
        if not items:
            return "<tr><td colspan='3' class='empty'>No feature pushed the prediction in this direction.</td></tr>"
        biggest = max(abs(c) for _, c in items) or 1.0
        out = []
        for f, c in items:
            width = max(6, int(abs(c) / biggest * 100))
            shown = raw[f]
            shown = f"{shown:g}" if isinstance(shown, float) else shown
            out.append(f"<tr><td class='fname'>{PRETTY.get(f, f)}</td>"
                       f"<td class='fval'>{shown}</td>"
                       f"<td class='fbar'><div class='bar' style='width:{width}%;background:{colour};'></div>"
                       f"<span class='bar-num'>{arrow} {abs(c):.3f}</span></td></tr>")
        return "".join(out)

    factors_html = f"""
    <div class="factor-grid">
      <div class="factor-card">
        <div class="factor-head leave">Pushing towards LEAVING</div>
        <table class="factor-table">
          <thead><tr><th>Feature</th><th>Value</th><th>Influence</th></tr></thead>
          <tbody>{rows(toward_leave, '#e07a74', '&#9650;')}</tbody>
        </table>
      </div>
      <div class="factor-card">
        <div class="factor-head stay">Pushing towards STAYING</div>
        <table class="factor-table">
          <thead><tr><th>Feature</th><th>Value</th><th>Influence</th></tr></thead>
          <tbody>{rows(toward_stay, '#6aa47f', '&#9660;')}</tbody>
        </table>
      </div>
    </div>
    <p class="explain-note">Influence is measured by resetting one feature at a time to its
    training-set average and recording how far the model's output moves. A larger bar means the
    feature moved the decision further. Values are relative to this employee only.</p>"""

    if notes:
        factors_html += ("<div class='notes'><strong>Input notes</strong><ul>"
                         + "".join(f"<li>{n}</li>" for n in notes) + "</ul></div>")

    label = {"Likely to leave": round(prob, 4), "Likely to stay": round(1 - prob, 4)}
    return label, verdict_html, factors_html


def reset_defaults():
    return [CAT_UI[f][1] if f in CAT_UI else NUMERIC_UI[f][3] for f in VISIBLE_FEATURES]


# ============================================================================ #
#  PART 2 - BiLSTM (Keras) FOR SENTIMENT   (unchanged logic from the original app)
# ============================================================================ #
import nltk
for pkg in ["stopwords", "wordnet", "omw-1.4"]:
    try:
        nltk.download(pkg, quiet=True)
    except Exception:
        pass
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

try:
    _SW = set(stopwords.words("english"))
except Exception:
    _SW = set()
_LEM   = WordNetLemmatizer()
_URL   = re.compile(r"http\S+|www\.\S+")
_EMOJI = re.compile("[\U0001F000-\U0001FFFF\U00002600-\U000027BF]", flags=re.UNICODE)


def clean_text(t):
    """Exact replica of the training-time cleaner."""
    t = str(t).lower()
    t = _URL.sub(" ", t)
    t = _EMOJI.sub(" ", t)
    t = re.sub(r"[^a-z\s]", " ", t)
    return " ".join(_LEM.lemmatize(w) for w in t.split() if w not in _SW and len(w) > 1)


class _Stub:
    def __setstate__(self, state): self.__dict__.update(state)
    def __init__(self, *a, **k): pass


class _TokUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if "keras" in module or "tensorflow" in module:
            return type(name, (_Stub,), {})
        return super().find_class(module, name)


with open(BILSTM_TOK, "rb") as f:
    _tok = _TokUnpickler(f).load()
WORD_INDEX = _tok.__dict__.get("word_index", {})
NUM_WORDS  = _tok.__dict__.get("num_words")
OOV_TOKEN  = _tok.__dict__.get("oov_token")
OOV_INDEX  = WORD_INDEX.get(OOV_TOKEN) if OOV_TOKEN else None

with open(BILSTM_LMAP, "rb") as f:
    LABEL_MAP = pickle.load(f)


def text_to_padded(text):
    """Manual texts_to_sequences + pad - matches Keras behaviour exactly."""
    seq = []
    for w in clean_text(text).split():
        i = WORD_INDEX.get(w)
        if i is None:
            if OOV_INDEX is not None:
                seq.append(OOV_INDEX)
            continue
        if NUM_WORDS and i >= NUM_WORDS:
            if OOV_INDEX is not None:
                seq.append(OOV_INDEX)
            continue
        seq.append(i)
    seq = seq[:MAX_LEN]
    seq = seq + [0] * (MAX_LEN - len(seq))
    return np.array([seq], dtype="int32")


import tensorflow as tf


def _load_bilstm():
    last_err = None
    for path in [BILSTM_KERAS, BILSTM_H5]:
        if os.path.isfile(path):
            try:
                return tf.keras.models.load_model(path, compile=False)
            except Exception as e:
                last_err = e
    raise RuntimeError(f"Could not load BiLSTM model: {last_err}")


bilstm_model = _load_bilstm()


def _word_influence(text, p_pos_full, top_k=6):
    """Leave-one-word-out: how much does removing each word move P(positive)?"""
    words = clean_text(text).split()[:MAX_LEN]
    if not words:
        return [], []
    seen, uniq = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    uniq = uniq[:25]

    batch = []
    for w in uniq:
        kept = " ".join(x for x in words if x != w)
        batch.append(text_to_padded(kept)[0])
    if not batch:
        return [], []
    probs = bilstm_model.predict(np.array(batch, dtype="int32"), verbose=0)[:, 1]

    # removing a word DROPS positivity  -> that word was pushing POSITIVE
    deltas = [(w, float(p_pos_full - p)) for w, p in zip(uniq, probs)]
    pos = sorted([d for d in deltas if d[1] > 1e-4], key=lambda t: -t[1])[:top_k]
    neg = sorted([d for d in deltas if d[1] < -1e-4], key=lambda t: t[1])[:top_k]
    return pos, neg


def predict_sentiment(text):
    if not text or not text.strip():
        return ({"Positive": 0.0, "Negative": 0.0},
                "<div class='verdict-card'><div class='verdict-sub'>Please enter some review text.</div></div>",
                "")

    padded = text_to_padded(text)
    probs  = bilstm_model.predict(padded, verbose=0)[0]
    p_neg, p_pos = float(probs[0]), float(probs[1])
    conf = max(p_neg, p_pos)

    if conf < 0.65:
        pred, signal, badge = "NEUTRAL OR MIXED", "Uncertain signal, review manually", "#c77700"
    elif p_pos >= 0.5:
        pred, signal, badge = "POSITIVE", "Consistent with an employee likely to stay", "#1b6b3a"
    else:
        pred, signal, badge = "NEGATIVE", "Consistent with an employee at risk of leaving", "#b3261e"

    verdict_html = f"""
    <div class="verdict-card" style="border-left:6px solid {badge};">
      <div class="verdict-title" style="color:{badge};">{pred}</div>
      <div class="verdict-sub">{signal}</div>
      <div class="verdict-metrics">
        <div class="metric"><span class="metric-value">{conf*100:.1f}%</span>
             <span class="metric-label">Confidence</span></div>
        <div class="metric"><span class="metric-value">{p_pos*100:.1f}%</span>
             <span class="metric-label">P(Positive)</span></div>
        <div class="metric"><span class="metric-value">{p_neg*100:.1f}%</span>
             <span class="metric-label">P(Negative)</span></div>
      </div>
    </div>"""

    pos, neg = _word_influence(text, p_pos)

    def wrows(items, colour, arrow):
        if not items:
            return "<tr><td colspan='2' class='empty'>No word pushed the prediction in this direction.</td></tr>"
        biggest = max(abs(d) for _, d in items) or 1.0
        out = []
        for w, d in items:
            width = max(6, int(abs(d) / biggest * 100))
            out.append(f"<tr><td class='fname'>{w}</td>"
                       f"<td class='fbar'><div class='bar' style='width:{width}%;background:{colour};'></div>"
                       f"<span class='bar-num'>{arrow} {abs(d):.3f}</span></td></tr>")
        return "".join(out)

    words_html = f"""
    <div class="factor-grid">
      <div class="factor-card">
        <div class="factor-head stay">Words driving POSITIVE sentiment</div>
        <table class="factor-table">
          <thead><tr><th>Word</th><th>Influence</th></tr></thead>
          <tbody>{wrows(pos, '#6aa47f', '&#9650;')}</tbody>
        </table>
      </div>
      <div class="factor-card">
        <div class="factor-head leave">Words driving NEGATIVE sentiment</div>
        <table class="factor-table">
          <thead><tr><th>Word</th><th>Influence</th></tr></thead>
          <tbody>{wrows(neg, '#e07a74', '&#9660;')}</tbody>
        </table>
      </div>
    </div>
    <p class="explain-note">Each word is removed in turn and the model is run again. The larger the
    change in the predicted sentiment, the more that word mattered. Words outside the model's
    20,000-word vocabulary, and common stop words, are ignored before analysis.</p>"""

    label = {"Positive": round(p_pos, 4), "Negative": round(p_neg, 4)}
    return label, verdict_html, words_html


# ============================================================================ #
#  INTERFACE
# ============================================================================ #
CSS = """
.gradio-container {max-width: 1200px !important; margin: auto;}
#hero {text-align:center; padding: 26px 18px 18px; border-radius:14px;
       background:linear-gradient(135deg,#1e2a44 0%,#2f4570 100%); color:#fff; margin-bottom:6px;}
#hero h1 {font-size:1.42rem; line-height:1.45; margin:0 0 8px; font-weight:700; color:#fff;}
#hero p  {margin:0; opacity:.86; font-size:.9rem;}
.section-title {font-weight:600; font-size:1.0rem; margin:6px 0 2px; color:#1e2a44;}
.verdict-card {background:#fff; border-radius:12px; padding:18px 20px; margin-top:6px;
               box-shadow:0 1px 3px rgba(16,24,40,.10);}
.verdict-title {font-size:1.24rem; font-weight:700; letter-spacing:.2px;}
.verdict-sub {color:#475467; margin:4px 0 14px; font-size:.92rem;}
.verdict-metrics {display:flex; gap:26px; flex-wrap:wrap;}
.metric {display:flex; flex-direction:column;}
.metric-value {font-size:1.24rem; font-weight:700; color:#101828;}
.metric-label {font-size:.74rem; color:#667085; text-transform:uppercase; letter-spacing:.4px;}
.thr-note {margin-top:12px; font-size:.78rem; color:#667085;}
.factor-grid {display:flex; gap:16px; flex-wrap:wrap; margin-top:14px;}
.factor-card {flex:1 1 320px; background:#fff; border:1px solid #e4e7ec; border-radius:12px; overflow:hidden;}
.factor-head {padding:10px 14px; font-weight:600; font-size:.9rem; color:#fff;}
.factor-head.leave {background:#b3261e;}
.factor-head.stay  {background:#1b6b3a;}
.factor-table {width:100%; border-collapse:collapse; font-size:.86rem;}
.factor-table th {text-align:left; padding:8px 14px; color:#667085; font-weight:600;
                  border-bottom:1px solid #eaecf0; font-size:.74rem; text-transform:uppercase;}
.factor-table td {padding:9px 14px; border-bottom:1px solid #f2f4f7; vertical-align:middle;}
.factor-table tr:last-child td {border-bottom:none;}
.fname {font-weight:500; color:#101828;}
.fval {color:#475467; white-space:nowrap;}
.fbar {min-width:130px;}
.bar {height:8px; border-radius:4px; display:inline-block; vertical-align:middle;}
.bar-num {font-size:.75rem; color:#667085; margin-left:8px;}
.empty {color:#98a2b3; font-style:italic; text-align:center; padding:16px;}
.explain-note {color:#667085; font-size:.8rem; margin-top:12px; line-height:1.5;}
.notes {margin-top:12px; padding:10px 14px; background:#fffaeb; border:1px solid #fedf89;
        border-radius:8px; font-size:.82rem; color:#7a5b00;}
.notes ul {margin:6px 0 0 18px;}
.disclaimer {color:#667085; font-size:.78rem; line-height:1.6; margin-top:18px;
             border-top:1px solid #eaecf0; padding-top:12px;}
@media (max-width:760px){ #hero h1{font-size:1.06rem;} .verdict-metrics{gap:16px;} }
"""


def _build_field(f):
    if f in CAT_UI:
        lbl, dflt = CAT_UI[f]
        return gr.Dropdown(choices=list(CAT_MAPS[f].keys()), value=dflt, label=lbl)
    lbl, lo, hi, dflt, hint = NUMERIC_UI[f]
    return gr.Number(value=dflt, label=lbl, info=hint, precision=0)


with gr.Blocks(title="Employee Attrition & Sentiment AI", theme=gr.themes.Soft(), css=CSS) as demo:
    gr.HTML(f"""
    <div id="hero">
      <h1>{APP_TITLE}</h1>
      <p>FT-Transformer for attrition risk &nbsp;&middot;&nbsp; BiLSTM for review sentiment
         &nbsp;&middot;&nbsp; Explainable, per-feature and per-word contributions</p>
    </div>""")

    components = {}

    with gr.Tab("Attrition prediction"):
        gr.Markdown("Enter the employee's details and select **Predict attrition**. The model "
                    "returns whether the employee is likely to stay or leave, its confidence, "
                    "and the features pushing the decision in each direction.")

        with gr.Row():
            with gr.Column():
                gr.HTML("<div class='section-title'>Personal and role</div>")
                for f in COL_1:
                    components[f] = _build_field(f)
            with gr.Column():
                gr.HTML("<div class='section-title'>Compensation and experience</div>")
                for f in COL_2:
                    components[f] = _build_field(f)
            with gr.Column():
                gr.HTML("<div class='section-title'>Tenure and satisfaction</div>")
                for f in COL_3:
                    components[f] = _build_field(f)

        thr = gr.Slider(0.30, 0.70, value=0.47, step=0.01,
                        label="Decision threshold for flagging an employee as a leaver",
                        info=("This is a decision control, not an employee attribute. The trained "
                              "model is majority-biased and rarely exceeds 0.50 on its own. Lower "
                              "the threshold to catch more leavers at the cost of more false alarms."))

        with gr.Row():
            predict_btn = gr.Button("Predict attrition", variant="primary", scale=3)
            reset_btn   = gr.Button("Reset to defaults", scale=1)

        attr_verdict = gr.HTML()
        attr_label   = gr.Label(label="Prediction probabilities", num_top_classes=2)
        attr_factors = gr.HTML()

        ordered = [components[f] for f in VISIBLE_FEATURES]
        predict_btn.click(predict_attrition, inputs=[thr] + ordered,
                          outputs=[attr_label, attr_verdict, attr_factors])
        reset_btn.click(reset_defaults, inputs=None, outputs=ordered)

    with gr.Tab("Review sentiment"):
        gr.Markdown("Paste an employee review or free-text feedback. The BiLSTM classifies its "
                    "sentiment and highlights the words that drove the decision.")
        sent_in = gr.Textbox(lines=5, label="Employee review or feedback",
                             placeholder="e.g. Great pay and supportive managers, but long hours.")
        sent_btn = gr.Button("Analyse sentiment", variant="primary")
        sent_verdict = gr.HTML()
        sent_label   = gr.Label(label="Sentiment probabilities", num_top_classes=2)
        sent_words   = gr.HTML()
        sent_btn.click(predict_sentiment, inputs=sent_in,
                       outputs=[sent_label, sent_verdict, sent_words])
        gr.Examples(
            examples=[
                ["Great pay, supportive managers and amazing work culture."],
                ["Toxic management, low salary, long hours, no growth."],
                ["The job is okay, average pay, nothing special."],
                ["Lack of career progression and a very stressful, bureaucratic environment."],
            ],
            inputs=sent_in, cache_examples=False)

    gr.HTML(f"""
    <div class="disclaimer">
      <strong>Attrition model.</strong> FT-Transformer trained on the IBM HR Analytics dataset
      (test accuracy 87.76%, leaver recall 0.39). The saved checkpoint stopped at epoch 2 because
      early stopping monitored validation <em>accuracy</em> on a target where about 84% of
      employees stay. It therefore leans towards predicting "stay" and its probability of leaving
      concentrates near {BASELINE_PROB*100:.0f}%. It still ranks employees sensibly, which is why
      this app shows risk relative to an average employee and exposes the decision threshold.
      Retraining with early stopping on validation F1 or ROC-AUC would fix the bias properly.<br><br>
      <strong>Sentiment model.</strong> BiLSTM (2,704,578 parameters), trained on Glassdoor employee
      reviews, binary Positive or Negative. Reviews rated three stars were treated as neutral and
      excluded at training time, so genuinely neutral text is reported as uncertain.<br><br>
      <strong>Hidden inputs.</strong> Stock Option Level, Daily Rate and Number of Companies Worked
      are removed from the interface. The network has a fixed 30-input layer, so they are held at
      their training-set mean, which becomes 0.0 after scaling and contributes nothing. Removing
      them from the model itself would require retraining.<br><br>
      <strong>Scope.</strong> Outputs are decision support only and must never be the sole basis for
      any employment decision.
    </div>""")

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
