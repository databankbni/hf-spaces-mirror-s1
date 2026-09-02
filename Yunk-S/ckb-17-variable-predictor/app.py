"""Hugging Face Space entry point for the CKB prediction package.

The public Space serves two stable programmatic endpoints (``/predict`` and
``/warmup``) as well as a browser-first Gradio experience. Model artifacts are
loaded lazily and never retain a visitor's submitted data.
"""

from __future__ import annotations

import html
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import gradio as gr
import pandas as pd

from predictions.predict_single import CKBSingleSamplePredictor


MODEL_DIR = Path(__file__).resolve().parent / "predictions"
SHAP_CACHE_DIR = Path(tempfile.gettempdir()) / "ckb_space_shap"
SUPPLEMENTARY_IMAGE_DIR = Path(__file__).resolve().parent / "assets" / "supplementary"
SHAP_CACHE_TTL_SECONDS = 60 * 60
SHAP_LIGHT_CANVAS_MARKER = "ckb-force-plot-light-canvas"
SHAP_LIGHT_CANVAS_HEAD = f"""
<meta name="color-scheme" content="light">
<style id="{SHAP_LIGHT_CANVAS_MARKER}">
  html {{ background: #ffffff !important; color-scheme: only light !important; }}
  body {{ min-height: 100%; margin: 0; background: #ffffff !important; color: #111827 !important; color-scheme: only light !important; }}
</style>
"""

FEATURES = [
    "sex",
    "age",
    "edu_level",
    "marital_status",
    "work",
    "retire",
    "hh_size",
    "smoking",
    "alcohol",
    "height_cm",
    "weight_kg",
    "waist_cm",
    "sbp_mmhg",
    "dbp_mmhg",
    "bp_drugs",
    "self_health",
    "chronic_pain",
]

FEATURE_LABELS = {
    "sex": "性别编码",
    "age": "年龄（岁）",
    "edu_level": "教育程度编码",
    "marital_status": "婚姻状态编码",
    "work": "工作状态编码",
    "retire": "退休状态编码",
    "hh_size": "家庭人口数",
    "smoking": "吸烟编码",
    "alcohol": "饮酒编码",
    "height_cm": "身高（cm）",
    "weight_kg": "体重（kg）",
    "waist_cm": "腰围（cm）",
    "sbp_mmhg": "收缩压（mmHg）",
    "dbp_mmhg": "舒张压（mmHg）",
    "bp_drugs": "降压药使用编码",
    "self_health": "自评健康编码",
    "chronic_pain": "慢性疼痛编码",
}

FEATURE_HELP = {
    "sex": "请使用训练数据中的原始分类编码。",
    "age": "以完整岁数填写。",
    "edu_level": "请使用训练数据中的原始分类编码。",
    "marital_status": "请使用训练数据中的原始分类编码。",
    "work": "请使用训练数据中的原始分类编码。",
    "retire": "请使用训练数据中的原始分类编码。",
    "hh_size": "同住家庭成员人数。",
    "smoking": "请使用训练数据中的原始分类编码。",
    "alcohol": "请使用训练数据中的原始分类编码。",
    "height_cm": "连续数值，单位为厘米。",
    "weight_kg": "连续数值，单位为千克。",
    "waist_cm": "连续数值，单位为厘米。",
    "sbp_mmhg": "连续数值，单位为 mmHg。",
    "dbp_mmhg": "连续数值，单位为 mmHg。",
    "bp_drugs": "请使用训练数据中的原始分类编码。",
    "self_health": "请使用训练数据中的原始分类编码。",
    "chronic_pain": "请使用训练数据中的原始分类编码。",
}

FEATURE_GROUPS = [
    (
        "01",
        "基本资料",
        "人口与社会特征",
        ["sex", "age", "edu_level", "marital_status", "work", "retire", "hh_size"],
    ),
    (
        "02",
        "生活与感受",
        "行为及健康自评",
        ["smoking", "alcohol", "self_health", "chronic_pain"],
    ),
    (
        "03",
        "体征与用药",
        "身体测量与血压信息",
        ["height_cm", "weight_kg", "waist_cm", "sbp_mmhg", "dbp_mmhg", "bp_drugs"],
    ),
]

INTEGER_FEATURES = {
    "sex",
    "age",
    "edu_level",
    "marital_status",
    "work",
    "retire",
    "hh_size",
    "smoking",
    "alcohol",
    "sbp_mmhg",
    "dbp_mmhg",
    "bp_drugs",
    "self_health",
    "chronic_pain",
}

# Display text is deliberately human-readable; the paired values remain the
# frozen numeric encodings expected by the trained model.
CATEGORICAL_CHOICES = {
    "sex": [("Male", 0), ("Female", 1)],
    "edu_level": [("Low", 1), ("Intermediate", 2), ("High", 3)],
    "marital_status": [
        ("Other observed status", 0),
        ("Married or partnered", 1),
    ],
    "work": [("No", 0), ("Yes", 1)],
    "retire": [("No", 0), ("Yes", 1)],
    "smoking": [("No", 0), ("Yes", 1)],
    "alcohol": [("No", 0), ("Yes", 1)],
    "bp_drugs": [("No", 0), ("Yes", 1)],
    "self_health": [
        ("Very good or excellent", 1),
        ("Good", 2),
        ("Fair or regular", 3),
        ("Poor or very poor", 4),
    ],
    "chronic_pain": [("No", 0), ("Yes", 1)],
}

EXAMPLE_VALUES = {
    "sex": 0,
    "age": 59,
    "edu_level": 1,
    "marital_status": 1,
    "work": 1,
    "retire": 0,
    "hh_size": 5,
    "smoking": 1,
    "alcohol": 1,
    "height_cm": 163.8,
    "weight_kg": 59.6,
    "waist_cm": 81.1,
    "sbp_mmhg": 125,
    "dbp_mmhg": 67,
    "bp_drugs": 0,
    "self_health": 2,
    "chronic_pain": 0,
}

TABLE_COLUMNS = ["代码", "预测结局", "概率", "冻结阈值", "风险判定"]


DEFAULT_EN_FEATURE_LABELS = {
    "sex": "Sex",
    "age": "Age (years)",
    "edu_level": "Education level",
    "marital_status": "Married or partnered",
    "work": "Currently working",
    "retire": "Retired",
    "hh_size": "Household size",
    "smoking": "Smoking",
    "alcohol": "Alcohol use",
    "height_cm": "Height (cm)",
    "weight_kg": "Weight (kg)",
    "waist_cm": "Waist (cm)",
    "sbp_mmhg": "Systolic BP (mmHg)",
    "dbp_mmhg": "Diastolic BP (mmHg)",
    "bp_drugs": "Blood-pressure medication",
    "self_health": "Self-rated health",
    "chronic_pain": "Chronic pain",
}

DEFAULT_EN_FEATURE_HELP = {feature: "" for feature in FEATURES}

TABLE_COLUMNS_EN = ["Code", "Outcome", "Probability", "Frozen threshold", "Risk decision"]


# Presentation-only labels and cumulative-incidence reference values supplied
# for the public demo. They do not participate in model inference or risk
# classification, which always uses the frozen per-outcome Youden threshold.
OUTCOME_PRESENTATION = {
    "A00_B99": {
        "en": "Infectious and parasitic diseases",
        "zh": "感染性疾病",
        "model_en": "MLP",
        "model_zh": "MLP",
        "low_5": 0.7,
        "low_10": 1.9,
        "high_5": 1.5,
        "high_10": 4.6,
    },
    "C00_D48": {
        "en": "Neoplasms",
        "zh": "肿瘤",
        "model_en": "MLP",
        "model_zh": "MLP",
        "low_5": 1.9,
        "low_10": 4.8,
        "high_5": 4.3,
        "high_10": 9.5,
    },
    "E00_E90": {
        "en": "Endocrine and metabolic diseases",
        "zh": "内分泌代谢疾病",
        "model_en": "MLP",
        "model_zh": "MLP",
        "low_5": 1.2,
        "low_10": 3.6,
        "high_5": 5.2,
        "high_10": 12.4,
    },
    "F00_F99": {
        "en": "Mental and behavioural disorders",
        "zh": "精神和行为障碍",
        "model_en": "Random Forest",
        "model_zh": "随机森林",
        "low_5": 0.2,
        "low_10": 0.5,
        "high_5": 0.6,
        "high_10": 1.3,
    },
    "G00_G99": {
        "en": "Diseases of the nervous system",
        "zh": "神经系统疾病",
        "model_en": "MLP",
        "model_zh": "MLP",
        "low_5": 0.6,
        "low_10": 2.7,
        "high_5": 2.5,
        "high_10": 7.7,
    },
    "H00_H95": {
        "en": "Diseases of the eye and ear",
        "zh": "眼耳疾病",
        "model_en": "Random Forest",
        "model_zh": "随机森林",
        "low_5": 0.6,
        "low_10": 2.4,
        "high_5": 2.6,
        "high_10": 8.9,
    },
    "I00_I99": {
        "en": "Diseases of the circulatory system",
        "zh": "循环系统疾病",
        "model_en": "MLP",
        "model_zh": "MLP",
        "low_5": 2.6,
        "low_10": 9.9,
        "high_5": 16.1,
        "high_10": 38.1,
    },
    "J00_J99": {
        "en": "Diseases of the respiratory system",
        "zh": "呼吸系统疾病",
        "model_en": "MLP",
        "model_zh": "MLP",
        "low_5": 2.0,
        "low_10": 6.4,
        "high_5": 5.9,
        "high_10": 18.6,
    },
    "K00_K93": {
        "en": "Diseases of the digestive system",
        "zh": "消化系统疾病",
        "model_en": "MLP",
        "model_zh": "MLP",
        "low_5": 3.1,
        "low_10": 9.2,
        "high_5": 5.6,
        "high_10": 16.0,
    },
    "L00_L99": {
        "en": "Diseases of the skin",
        "zh": "皮肤病",
        "model_en": "Random Forest",
        "model_zh": "随机森林",
        "low_5": 0.1,
        "low_10": 0.5,
        "high_5": 0.3,
        "high_10": 1.2,
    },
    "M00_M99": {
        "en": "Musculoskeletal diseases",
        "zh": "肌肉骨骼疾病",
        "model_en": "MLP",
        "model_zh": "MLP",
        "low_5": 1.2,
        "low_10": 5.5,
        "high_5": 2.5,
        "high_10": 11.0,
    },
    "N00_N99": {
        "en": "Diseases of the genitourinary system",
        "zh": "泌尿生殖系统疾病",
        "model_en": "MLP",
        "model_zh": "MLP",
        "low_5": 1.6,
        "low_10": 4.6,
        "high_5": 3.2,
        "high_10": 9.2,
    },
    "death": {
        "en": "All-cause death",
        "zh": "全因死亡",
        "model_en": "MLP",
        "model_zh": "MLP",
        "low_5": 0.9,
        "low_10": 2.4,
        "high_5": 8.0,
        "high_10": 20.2,
    },
}

# Keep Chinese presentation copy in unicode escapes so it remains intact when
# the Space is edited from Windows shells with different console code pages.
_OUTCOME_ZH = {
    "A00_B99": "\u611f\u67d3\u6027\u75be\u75c5",
    "C00_D48": "\u80bf\u7624",
    "E00_E90": "\u5185\u5206\u6ccc\u4ee3\u8c22\u75be\u75c5",
    "F00_F99": "\u7cbe\u795e\u548c\u884c\u4e3a\u969c\u788d",
    "G00_G99": "\u795e\u7ecf\u7cfb\u7edf\u75be\u75c5",
    "H00_H95": "\u773c\u8033\u75be\u75c5",
    "I00_I99": "\u5faa\u73af\u7cfb\u7edf\u75be\u75c5",
    "J00_J99": "\u547c\u5438\u7cfb\u7edf\u75be\u75c5",
    "K00_K93": "\u6d88\u5316\u7cfb\u7edf\u75be\u75c5",
    "L00_L99": "\u76ae\u80a4\u75c5",
    "M00_M99": "\u808c\u8089\u9aa8\u9abc\u75be\u75c5",
    "N00_N99": "\u6ccc\u5c3f\u751f\u6b96\u7cfb\u7edf\u75be\u75c5",
    "death": "\u5168\u56e0\u6b7b\u4ea1",
}
for _outcome_code, _outcome_name_zh in _OUTCOME_ZH.items():
    OUTCOME_PRESENTATION[_outcome_code]["zh"] = _outcome_name_zh
OUTCOME_PRESENTATION["F00_F99"]["model_zh"] = "\u968f\u673a\u68ee\u6797"
OUTCOME_PRESENTATION["H00_H95"]["model_zh"] = "\u968f\u673a\u68ee\u6797"
OUTCOME_PRESENTATION["L00_L99"]["model_zh"] = "\u968f\u673a\u68ee\u6797"


CUSTOM_CSS = """
:root {
  --ckb-blue-950: #082f49;
  --ckb-blue-900: #0c4a6e;
  --ckb-blue-700: #0369a1;
  --ckb-blue-600: #0284c7;
  --ckb-blue-100: #e0f2fe;
  --ckb-blue-50: #f0f9ff;
  --ckb-cyan-100: #cffafe;
  --ckb-green-700: #15803d;
  --ckb-green-600: #16a34a;
  --ckb-green-100: #dcfce7;
  --ckb-amber-700: #b45309;
  --ckb-amber-100: #fef3c7;
  --ckb-slate-950: #0f172a;
  --ckb-slate-700: #334155;
  --ckb-slate-600: #475569;
  --ckb-slate-400: #94a3b8;
  --ckb-slate-200: #e2e8f0;
  --ckb-slate-100: #f1f5f9;
  --ckb-white: #ffffff;
  --ckb-shadow-sm: 0 1px 2px rgb(15 23 42 / 0.05);
  --ckb-shadow-md: 0 16px 40px rgb(12 74 110 / 0.10);
  --ckb-radius-lg: 20px;
  --ckb-radius-md: 14px;
  --ckb-radius-sm: 10px;
  --ckb-motion-fast: 180ms;
  --ckb-motion-base: 280ms;
  --ckb-layer-field: 10;
  --ckb-layer-dropdown: 40;
}

.gradio-container {
  background:
    radial-gradient(circle at 10% 0%, rgb(207 250 254 / 0.75), transparent 24rem),
    radial-gradient(circle at 90% 9%, rgb(224 242 254 / 0.95), transparent 25rem),
    var(--ckb-blue-50);
  color: var(--ckb-slate-950);
  color-scheme: light !important;
  font-family: Aptos, "Segoe UI", "Microsoft YaHei UI", "Noto Sans SC", sans-serif;
}

#ckb-shell {
  width: min(1180px, 100%);
  margin: 0 auto;
  padding: 24px 18px 52px;
  color: var(--ckb-slate-950);
}

#ckb-shell * { box-sizing: border-box; }

.ckb-skip {
  position: absolute;
  left: -10000px;
  top: auto;
  overflow: hidden;
  width: 1px;
  height: 1px;
}

.ckb-skip:focus {
  left: 18px;
  top: 18px;
  z-index: 1000;
  width: auto;
  height: auto;
  padding: 10px 14px;
  border-radius: var(--ckb-radius-sm);
  background: var(--ckb-blue-950);
  color: var(--ckb-white);
  font-weight: 700;
}

.ckb-hero {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  min-height: 286px;
  padding: clamp(30px, 6vw, 68px);
  border: 1px solid rgb(255 255 255 / 0.28);
  border-radius: 28px;
  background:
    linear-gradient(123deg, var(--ckb-blue-950) 0%, var(--ckb-blue-900) 56%, var(--ckb-blue-700) 100%);
  box-shadow: var(--ckb-shadow-md);
  color: var(--ckb-white) !important;
}

.ckb-hero::before,
.ckb-hero::after {
  position: absolute;
  z-index: -1;
  display: block;
  border-radius: 999px;
  content: "";
  filter: blur(2px);
}

.ckb-hero::before {
  top: -138px;
  right: -58px;
  width: 322px;
  height: 322px;
  border: 1px solid rgb(207 250 254 / 0.30);
  background: radial-gradient(circle, rgb(34 211 238 / 0.30), transparent 67%);
}

.ckb-hero::after {
  right: 18%;
  bottom: -185px;
  width: 360px;
  height: 360px;
  background: radial-gradient(circle, rgb(22 163 74 / 0.24), transparent 67%);
}

.ckb-hero__content { position: relative; max-width: 720px; }

.ckb-eyebrow,
.ckb-chip,
.ckb-section-kicker,
.ckb-result-kicker {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 0.78rem;
  font-weight: 750;
  letter-spacing: 0.08em;
  line-height: 1;
  text-transform: uppercase;
}

.ckb-hero .ckb-eyebrow {
  color: var(--ckb-cyan-100) !important;
  -webkit-text-fill-color: var(--ckb-cyan-100);
}

.ckb-mark {
  display: inline-grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 1px solid rgb(207 250 254 / 0.36);
  border-radius: 9px;
  background: rgb(255 255 255 / 0.10);
}

.ckb-mark svg { width: 17px; height: 17px; stroke: currentColor; }

.ckb-hero h1 {
  max-width: 13ch;
  margin: 16px 0 14px;
  color: var(--ckb-white) !important;
  -webkit-text-fill-color: var(--ckb-white);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: clamp(2.15rem, 5.1vw, 4.25rem);
  font-weight: 650;
  letter-spacing: -0.045em;
  line-height: 1.04;
}

.ckb-hero p {
  max-width: 62ch;
  margin: 0;
  color: #f0f9ff !important;
  -webkit-text-fill-color: #f0f9ff;
  font-size: clamp(1rem, 1.4vw, 1.12rem);
  line-height: 1.7;
}

.ckb-hero__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 26px;
}

.ckb-chip {
  min-height: 34px;
  padding: 8px 11px;
  border: 1px solid rgb(255 255 255 / 0.16);
  border-radius: 999px;
  background: rgb(255 255 255 / 0.10);
  color: var(--ckb-white) !important;
  -webkit-text-fill-color: var(--ckb-white);
  letter-spacing: 0.02em;
  text-transform: none;
}

.ckb-chip svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 2; }

.ckb-trust-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0 24px;
}

.ckb-trust-card {
  min-width: 0;
  padding: 16px 18px;
  border: 1px solid var(--ckb-blue-100);
  border-radius: var(--ckb-radius-md);
  background: rgb(255 255 255 / 0.78);
  box-shadow: var(--ckb-shadow-sm);
}

.ckb-trust-card strong {
  display: block;
  color: var(--ckb-blue-900);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 1.42rem;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}

.ckb-trust-card span {
  display: block;
  margin-top: 5px;
  color: var(--ckb-slate-600);
  font-size: 0.86rem;
  line-height: 1.35;
}

.ckb-language-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
  margin: -4px 0 14px;
}

.ckb-language-switch,
.ckb-theme-switch {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--ckb-blue-100);
  border-radius: 999px;
  background: rgb(255 255 255 / 0.88);
  box-shadow: var(--ckb-shadow-sm);
}

.ckb-language-switch button,
.ckb-theme-switch button {
  min-width: 74px;
  min-height: 36px;
  padding: 7px 12px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--ckb-slate-600);
  cursor: pointer;
  font: inherit;
  font-size: 0.82rem;
  font-weight: 750;
  transition: background var(--ckb-motion-fast) ease, color var(--ckb-motion-fast) ease, transform var(--ckb-motion-fast) ease;
}

.ckb-theme-switch button { min-width: 58px; }
.ckb-language-switch button:hover,
.ckb-theme-switch button:hover { background: var(--ckb-blue-50); color: var(--ckb-blue-900); }
.ckb-language-switch button:active,
.ckb-theme-switch button:active { transform: scale(0.98); }
.ckb-language-switch button[aria-pressed="true"],
.ckb-theme-switch button[aria-pressed="true"] { background: var(--ckb-blue-900); color: var(--ckb-white); }
.ckb-language-switch button:focus-visible,
.ckb-theme-switch button:focus-visible { outline: 3px solid rgb(2 132 199 / 0.32); outline-offset: 2px; }

.ckb-status {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-height: 52px;
  margin: 0 0 20px;
  padding: 14px 16px;
  border: 1px solid var(--ckb-blue-100);
  border-radius: var(--ckb-radius-md);
  background: rgb(255 255 255 / 0.82);
  color: var(--ckb-slate-700);
  box-shadow: var(--ckb-shadow-sm);
  line-height: 1.5;
}

.ckb-status__dot {
  flex: 0 0 auto;
  width: 10px;
  height: 10px;
  margin-top: 7px;
  border-radius: 50%;
  background: var(--ckb-blue-600);
  box-shadow: 0 0 0 4px var(--ckb-blue-100);
}

.ckb-status--ready { border-color: var(--ckb-green-100); background: #f6fff8; }
.ckb-status--ready .ckb-status__dot { background: var(--ckb-green-600); box-shadow: 0 0 0 4px var(--ckb-green-100); }
.ckb-status--warning { border-color: var(--ckb-amber-100); background: #fffbeb; }
.ckb-status--warning .ckb-status__dot { background: var(--ckb-amber-700); box-shadow: 0 0 0 4px var(--ckb-amber-100); }

.ckb-panel {
  padding: clamp(22px, 3vw, 34px);
  border: 1px solid var(--ckb-blue-100);
  border-radius: var(--ckb-radius-lg);
  background: rgb(255 255 255 / 0.88);
  box-shadow: var(--ckb-shadow-md);
}

.ckb-section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}

.ckb-section-kicker { color: var(--ckb-blue-700); }

.ckb-section-heading h2 {
  margin: 7px 0 6px;
  color: var(--ckb-slate-950);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: clamp(1.55rem, 3vw, 2.1rem);
  letter-spacing: -0.025em;
  line-height: 1.16;
}

.ckb-section-heading p {
  max-width: 58ch;
  margin: 0;
  color: var(--ckb-slate-600);
  font-size: 0.95rem;
  line-height: 1.6;
}

.ckb-coding-note {
  flex: 0 0 auto;
  max-width: 265px;
  padding: 10px 12px;
  border-radius: var(--ckb-radius-sm);
  background: var(--ckb-blue-50);
  color: var(--ckb-blue-900);
  font-size: 0.82rem;
  font-weight: 650;
  line-height: 1.45;
}

.ckb-input-grid { gap: 14px; }

.ckb-form-card {
  height: 100%;
  padding: 17px;
  border: 1px solid var(--ckb-slate-200);
  border-radius: var(--ckb-radius-md);
  background: var(--ckb-white);
  box-shadow: var(--ckb-shadow-sm);
}

.ckb-form-card .form-card__top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 14px;
}

.ckb-form-card .form-card__index {
  display: inline-grid;
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 9px;
  background: var(--ckb-blue-100);
  color: var(--ckb-blue-900);
  font-size: 0.78rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.ckb-form-card h3 { margin: 1px 0 3px; color: var(--ckb-slate-950); font-size: 1rem; }
.ckb-form-card p { margin: 0; color: var(--ckb-slate-600); font-size: 0.8rem; line-height: 1.4; }

#ckb-shell .ckb-form-card .block { min-width: 0; margin-bottom: 10px; }
#ckb-shell .ckb-form-card label { color: var(--ckb-slate-700); font-size: 0.86rem; font-weight: 700; }
#ckb-shell .ckb-form-card input {
  min-height: 48px;
  border: 1px solid var(--ckb-slate-200);
  border-radius: var(--ckb-radius-sm);
  background: var(--ckb-white);
  color: var(--ckb-slate-950);
  font-size: 1rem;
  font-variant-numeric: tabular-nums;
  transition: border-color var(--ckb-motion-fast) ease, box-shadow var(--ckb-motion-fast) ease;
}

#ckb-shell .ckb-form-card input:hover { border-color: var(--ckb-blue-600); }
#ckb-shell .ckb-form-card input:focus {
  border-color: var(--ckb-blue-600);
  box-shadow: 0 0 0 3px rgb(2 132 199 / 0.20);
  outline: none;
}

.ckb-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 24px;
}

#predict-button,
#reset-button {
  min-height: 48px;
  border-radius: var(--ckb-radius-sm);
  font-weight: 750;
  transition: transform var(--ckb-motion-fast) ease, box-shadow var(--ckb-motion-fast) ease, background var(--ckb-motion-fast) ease;
}

#predict-button {
  min-width: 172px;
  border: 0;
  background: var(--ckb-green-600);
  box-shadow: 0 10px 22px rgb(22 163 74 / 0.22);
  color: var(--ckb-white);
}

#predict-button:hover { background: var(--ckb-green-700); box-shadow: 0 13px 26px rgb(22 163 74 / 0.29); transform: translateY(-1px); }
#predict-button:active { transform: translateY(0) scale(0.985); }
#predict-button:focus-visible,
#reset-button:focus-visible { outline: 3px solid rgb(2 132 199 / 0.35); outline-offset: 3px; }

#reset-button {
  border: 1px solid var(--ckb-slate-200);
  background: var(--ckb-white);
  color: var(--ckb-slate-700);
}

#reset-button:hover { border-color: var(--ckb-blue-600); color: var(--ckb-blue-900); transform: translateY(-1px); }

.ckb-privacy-copy {
  display: flex;
  flex: 1 1 250px;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--ckb-slate-600);
  font-size: 0.82rem;
  line-height: 1.45;
}

.ckb-privacy-copy svg { flex: 0 0 auto; width: 17px; height: 17px; stroke: var(--ckb-blue-700); stroke-width: 2; }

.ckb-results {
  margin-top: 26px;
  padding: clamp(22px, 3vw, 34px);
  border: 1px solid var(--ckb-blue-100);
  border-radius: var(--ckb-radius-lg);
  background: rgb(255 255 255 / 0.90);
  box-shadow: var(--ckb-shadow-md);
}

.ckb-results-header { margin-bottom: 17px; }
.ckb-results-header h2 { margin: 7px 0 0; color: var(--ckb-slate-950); font-family: Georgia, "Noto Serif SC", serif; font-size: clamp(1.5rem, 3vw, 2rem); }

.ckb-result-card,
.ckb-result-placeholder {
  min-height: 122px;
  padding: 20px;
  border: 1px solid var(--ckb-blue-100);
  border-radius: var(--ckb-radius-md);
  background: linear-gradient(112deg, var(--ckb-blue-50), var(--ckb-white));
}

.ckb-result-placeholder { display: grid; place-items: center; color: var(--ckb-slate-600); text-align: center; }

.ckb-result-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.ckb-result-kicker { color: var(--ckb-blue-700); }
.ckb-result-card h3 { margin: 6px 0 0; color: var(--ckb-blue-950); font-family: Georgia, "Noto Serif SC", serif; font-size: 1.7rem; }
.ckb-result-badge { flex: 0 0 auto; padding: 8px 10px; border-radius: 999px; background: var(--ckb-green-100); color: var(--ckb-green-700); font-size: 0.8rem; font-weight: 800; }
.ckb-result-badge--review { background: var(--ckb-amber-100); color: var(--ckb-amber-700); }

.ckb-result-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 18px 0 0;
}

.ckb-result-metrics div { padding: 11px; border-radius: var(--ckb-radius-sm); background: rgb(255 255 255 / 0.76); }
.ckb-result-metrics dt { color: var(--ckb-slate-600); font-size: 0.76rem; }
.ckb-result-metrics dd { margin: 4px 0 0; color: var(--ckb-slate-950); font-size: 1rem; font-weight: 800; font-variant-numeric: tabular-nums; }

.ckb-risk-visual { margin-top: 18px; padding: 20px; border: 1px solid var(--ckb-slate-200); border-radius: var(--ckb-radius-md); background: var(--ckb-white); }
.ckb-risk-visual__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 16px; }
.ckb-risk-visual h3 { margin: 0; color: var(--ckb-slate-950); font-size: 1.05rem; }
.ckb-risk-visual p { margin: 5px 0 0; color: var(--ckb-slate-600); font-size: 0.82rem; line-height: 1.45; }
.ckb-legend { display: flex; flex-wrap: wrap; gap: 10px; color: var(--ckb-slate-600); font-size: 0.76rem; }
.ckb-legend span { display: inline-flex; align-items: center; gap: 5px; }
.ckb-legend i { width: 9px; height: 9px; border-radius: 50%; background: var(--ckb-green-600); }
.ckb-legend .ckb-legend--high { background: var(--ckb-amber-700); }

.ckb-risk-row { display: grid; grid-template-columns: minmax(88px, 0.8fr) minmax(130px, 2fr) 54px; gap: 10px; align-items: center; margin: 10px 0; }
.ckb-risk-label { overflow: hidden; color: var(--ckb-slate-700); font-size: 0.78rem; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.ckb-risk-track { position: relative; height: 11px; overflow: hidden; border-radius: 999px; background: var(--ckb-slate-100); }
.ckb-risk-fill { display: block; width: var(--risk-width); height: 100%; border-radius: inherit; background: var(--ckb-green-600); }
.ckb-risk-row--high .ckb-risk-fill { background: var(--ckb-amber-700); }
.ckb-risk-threshold { position: absolute; top: 0; bottom: 0; left: var(--threshold); width: 2px; background: var(--ckb-slate-950); opacity: 0.58; }
.ckb-risk-value { color: var(--ckb-slate-950); font-size: 0.8rem; font-weight: 800; font-variant-numeric: tabular-nums; text-align: right; }

#outcome-table { margin-top: 18px; overflow-x: auto; }
#outcome-table table { min-width: 680px; border-collapse: separate; border-spacing: 0; }
#outcome-table thead { background: var(--ckb-blue-50); }
#outcome-table th { color: var(--ckb-blue-900); font-size: 0.78rem; font-weight: 800; }
#outcome-table td { color: var(--ckb-slate-700); font-size: 0.84rem; }
#outcome-table th, #outcome-table td { border-color: var(--ckb-slate-200); }

#shap-result { overflow: hidden !important; margin-top: 18px; border: 1px solid var(--ckb-blue-700); border-radius: var(--ckb-radius-md); background: var(--ckb-white); box-shadow: var(--ckb-shadow-sm); }
#shap-result > button {
  position: relative;
  display: flex !important;
  align-items: center;
  width: 100%;
  min-height: 64px;
  padding: 14px 68px 14px 22px !important;
  border: 0 !important;
  border-radius: var(--ckb-radius-md);
  background: linear-gradient(112deg, var(--ckb-blue-950), var(--ckb-blue-700));
  color: var(--ckb-white) !important;
  cursor: pointer;
  font-size: 0.98rem;
  font-weight: 800;
  letter-spacing: 0.01em;
  line-height: 1.35;
  text-align: left;
  touch-action: manipulation;
  transition: background 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}
#shap-result > button::after {
  position: absolute;
  right: 26px;
  width: 11px;
  height: 11px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  content: "";
  transform: rotate(45deg) translateY(-3px);
  transform-origin: center;
  transition: transform 180ms ease;
}
#shap-result > button:hover { background: linear-gradient(112deg, var(--ckb-blue-900), var(--ckb-blue-600)); box-shadow: inset 0 0 0 999px rgb(255 255 255 / 0.05); }
#shap-result > button:active { transform: scale(0.995); }
#shap-result > button:focus-visible { outline: 3px solid rgb(2 132 199 / 0.42); outline-offset: -5px; }
#shap-result > button.open { border-bottom: 1px solid var(--ckb-blue-100) !important; border-radius: var(--ckb-radius-md) var(--ckb-radius-md) 0 0; background: var(--ckb-blue-50); color: var(--ckb-blue-950) !important; }
#shap-result > button.open::after { transform: rotate(225deg) translateY(-3px); }
.ckb-shap-placeholder { display: grid; min-height: 108px; place-items: center; color: var(--ckb-slate-600); text-align: center; }
.ckb-shap-gallery { padding: 4px 2px 2px; }
.ckb-shap-gallery__header { margin: 0 0 16px; }
.ckb-shap-gallery__header .ckb-section-kicker { color: var(--ckb-blue-700); }
.ckb-shap-gallery__header h3 { margin: 6px 0 0; color: var(--ckb-slate-950); font-size: 1.2rem; }
.ckb-shap-gallery__header p { margin: 6px 0 0; color: var(--ckb-slate-600); font-size: 0.84rem; line-height: 1.5; }
.ckb-shap-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.ckb-shap-card { min-width: 0; overflow: hidden; border: 1px solid var(--ckb-slate-200); border-radius: var(--ckb-radius-sm); background: var(--ckb-white); box-shadow: var(--ckb-shadow-sm); }
.ckb-shap-card--cluster { grid-column: 1 / -1; }
.ckb-shap-card__header { padding: 13px 14px 10px; border-bottom: 1px solid var(--ckb-slate-100); background: linear-gradient(112deg, var(--ckb-blue-50), var(--ckb-white)); }
.ckb-shap-card__kind { margin: 0; color: var(--ckb-blue-700); font-size: 0.72rem; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; }
.ckb-shap-card h4 { margin: 4px 0 0; color: var(--ckb-slate-950); font-size: 0.94rem; line-height: 1.35; }
.ckb-shap-frame { display: block; width: 100%; height: 330px; border: 0; background: var(--ckb-white); }

#raw-result { margin-top: 16px; border: 1px solid var(--ckb-slate-200); border-radius: var(--ckb-radius-sm); background: var(--ckb-white); }
#raw-result button { min-height: 44px; color: var(--ckb-slate-700); font-weight: 750; }

.ckb-footer-note { margin: 20px 0 0; color: var(--ckb-slate-600); font-size: 0.82rem; line-height: 1.6; }
.ckb-footer-note code { padding: 2px 5px; border-radius: 5px; background: var(--ckb-slate-100); color: var(--ckb-blue-900); }

.ckb-hero, .ckb-trust-card, .ckb-panel, .ckb-results { will-change: auto; }

/* The hero now carries one concise model statement; the old labels and count
   tiles remain in the DOM only so legacy locale initialisation stays stable. */
.ckb-eyebrow, .ckb-hero__meta, .ckb-trust-row { display: none !important; }
.ckb-hero { min-height: 230px; display: grid; align-items: center; }
.ckb-hero p { max-width: 66ch; }
.ckb-section-heading > div > p, .ckb-coding-note { display: none !important; }

/* Gradio renders dropdown lists in a popover. Keeping animated ancestors
   transform-free and elevating the portal fixes the offset seen in the form. */
#ckb-shell .ckb-form-card .block,
#ckb-shell .ckb-form-card .wrap { position: relative; overflow: visible !important; }
#ckb-shell .ckb-form-card .block { z-index: 0; }
#ckb-shell .ckb-form-card .block:focus-within { z-index: var(--ckb-layer-field); }
body .secondary-wrap,
body [role="listbox"] { z-index: var(--ckb-layer-dropdown) !important; }
#ckb-shell .ckb-form-card button,
#ckb-shell .ckb-form-card [role="combobox"] { min-height: 48px; border-radius: var(--ckb-radius-sm); }
#ckb-shell,
#outcome-table,
#outcome-table .html-container,
#shap-result,
#shap-result .wrap,
#shap-result .form,
#shap-result .html-container,
#shap-gallery,
#shap-gallery .wrap,
#shap-gallery .html-container,
.ckb-image-gallery,
.ckb-image-card,
.ckb-image-card__force { color-scheme: light !important; }
.ckb-image-frame,
.ckb-reference-figure,
.ckb-cluster-profile-figure { color-scheme: only light !important; }
#shap-result .wrap,
#shap-result .form,
#shap-result .html-container,
#shap-gallery,
#shap-gallery .wrap,
#shap-gallery .html-container { background: var(--ckb-white) !important; color: var(--ckb-slate-950) !important; }
#ckb-shell .ckb-panel .ckb-section-heading,
#ckb-shell .ckb-panel .ckb-section-heading h2,
#ckb-shell .ckb-panel .ckb-section-heading p,
#ckb-shell .ckb-status,
#ckb-shell .ckb-status strong,
#ckb-shell .ckb-results-header,
#ckb-shell .ckb-results-header h2,
#ckb-shell .ckb-result-placeholder,
#ckb-shell .ckb-footer-note { color: var(--ckb-slate-950) !important; }
#ckb-shell .ckb-panel .ckb-section-heading .ckb-section-kicker,
#ckb-shell .ckb-results-header .ckb-section-kicker { color: var(--ckb-blue-700) !important; }
#ckb-shell .ckb-status { color: var(--ckb-slate-700) !important; }
#ckb-shell .ckb-status span,
#ckb-shell .ckb-status strong { color: inherit !important; }
#ckb-shell .ckb-result-placeholder,
#ckb-shell .ckb-footer-note { color: var(--ckb-slate-600) !important; }
#ckb-shell .ckb-footer-note code { color: var(--ckb-blue-900) !important; }
#ckb-shell .ckb-form-card,
#ckb-shell .ckb-form-card > .styler,
#ckb-shell .ckb-form-card .form,
#ckb-shell .ckb-form-card .container { background: var(--ckb-white) !important; color: var(--ckb-slate-950) !important; }
#ckb-shell .ckb-form-card .block { background: transparent !important; border-color: transparent !important; }
#ckb-shell .ckb-form-card .wrap,
#ckb-shell .ckb-form-card .wrap-inner,
#ckb-shell .ckb-form-card .secondary-wrap { background: var(--ckb-white) !important; border-color: var(--ckb-slate-200) !important; color: var(--ckb-slate-950) !important; }
#ckb-shell .ckb-form-card .form-card__index { color: var(--ckb-blue-900) !important; }
#ckb-shell .ckb-form-card h3 { color: var(--ckb-slate-950) !important; }
#ckb-shell .ckb-form-card p { color: var(--ckb-slate-600) !important; }
#ckb-shell .ckb-form-card [data-testid="block-info"],
#ckb-shell .ckb-form-card label { color: var(--ckb-slate-700) !important; }
body .options[role="listbox"] { border: 1px solid var(--ckb-slate-200) !important; border-radius: var(--ckb-radius-sm) !important; background: var(--ckb-white) !important; box-shadow: var(--ckb-shadow-md) !important; }
body .options[role="listbox"] [role="option"] { background: var(--ckb-white) !important; color: var(--ckb-slate-950) !important; }
body .options[role="listbox"] [role="option"]:hover,
body .options[role="listbox"] [role="option"][aria-selected="true"] { background: var(--ckb-blue-50) !important; color: var(--ckb-blue-950) !important; }

.ckb-outcome-table { margin-top: 18px; overflow: hidden; border: 1px solid var(--ckb-slate-200); border-radius: var(--ckb-radius-md); background: var(--ckb-white); box-shadow: var(--ckb-shadow-sm); }
.ckb-outcome-table__header { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; padding: 18px 20px 15px; border-bottom: 1px solid var(--ckb-slate-100); background: linear-gradient(112deg, var(--ckb-blue-50), var(--ckb-white)); }
.ckb-outcome-table__header h3 { margin: 5px 0 0; color: var(--ckb-slate-950); font-size: 1.08rem; }
.ckb-outcome-table__header > p { max-width: 50ch; margin: 0; color: var(--ckb-slate-600); font-size: 0.8rem; line-height: 1.45; text-align: right; }
.ckb-outcome-table__scroll { overflow-x: auto; }
.ckb-outcome-table table { width: 100%; min-width: 720px; border-collapse: collapse; }
.ckb-outcome-table th, .ckb-outcome-table td { padding: 12px 14px; border-bottom: 1px solid var(--ckb-slate-100); text-align: left; }
.ckb-outcome-table th { color: var(--ckb-blue-900); background: rgb(240 249 255 / 0.72); font-size: 0.76rem; font-weight: 850; letter-spacing: 0.025em; }
.ckb-outcome-table td { color: var(--ckb-slate-700); font-size: 0.84rem; vertical-align: middle; }
.ckb-outcome-table tbody tr:last-child td { border-bottom: 0; }
.ckb-outcome-table tbody tr:hover { background: var(--ckb-blue-50); }
.ckb-outcome-table__code { color: var(--ckb-slate-950) !important; font-weight: 800; font-variant-numeric: tabular-nums; white-space: nowrap; }
.ckb-outcome-table__decision { display: inline-flex; padding: 5px 8px; border-radius: 999px; background: var(--ckb-green-100); color: var(--ckb-green-700); font-size: 0.75rem; font-weight: 800; white-space: nowrap; }
.ckb-outcome-table__decision--high { background: var(--ckb-amber-100); color: var(--ckb-amber-700); }

.ckb-image-placeholder { display: grid; min-height: 108px; place-items: center; padding: 20px; color: var(--ckb-slate-600); text-align: center; }
.ckb-image-gallery { padding: 2px; }
.ckb-image-gallery__header { margin: 0 0 20px; }
.ckb-image-gallery__header h3 { margin: 6px 0 0; color: var(--ckb-slate-950); font-size: 1.2rem; }
.ckb-image-gallery__header p { max-width: 74ch; margin: 6px 0 0; color: var(--ckb-slate-600); font-size: 0.84rem; line-height: 1.5; }
.ckb-image-section + .ckb-image-section { margin-top: 22px; }
.ckb-image-section__header { margin: 0 0 10px; }
.ckb-image-section__header h4 { margin: 0; color: var(--ckb-blue-900); font-size: 0.9rem; font-weight: 850; }
.ckb-image-grid { display: grid; gap: 14px; }
.ckb-image-grid--clusters { grid-template-columns: 1fr; }
.ckb-image-grid--outcomes { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.ckb-image-card { min-width: 0; overflow: hidden; border: 1px solid var(--ckb-slate-200); border-radius: var(--ckb-radius-sm); background: var(--ckb-white); box-shadow: var(--ckb-shadow-sm); }
.ckb-image-card--selected { border-color: var(--ckb-blue-600); box-shadow: 0 0 0 2px rgb(2 132 199 / 0.14), var(--ckb-shadow-sm); }
.ckb-image-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 12px 13px 10px; border-bottom: 1px solid var(--ckb-slate-100); background: linear-gradient(112deg, var(--ckb-blue-50), var(--ckb-white)); }
.ckb-image-card__kind { margin: 0; color: var(--ckb-blue-700); font-size: 0.7rem; font-weight: 850; letter-spacing: 0.06em; text-transform: uppercase; }
.ckb-image-card h4 { margin: 4px 0 0; color: var(--ckb-slate-950); font-size: 0.9rem; line-height: 1.35; }
.ckb-image-card__badge { flex: 0 0 auto; max-width: 50%; padding: 5px 8px; border-radius: 999px; background: var(--ckb-blue-100); color: var(--ckb-blue-900); font-size: 0.7rem; font-weight: 800; line-height: 1.2; text-align: center; }
.ckb-image-card__badge--high { background: var(--ckb-amber-100); color: var(--ckb-amber-700); }
.ckb-image-frame { display: block; width: 100%; height: 218px; border: 0; background: var(--ckb-white); }
.ckb-image-card__context { display: grid; grid-template-columns: minmax(205px, 0.9fr) minmax(0, 1.1fr); gap: 12px; align-items: stretch; padding: 12px; background: #fbfdff; }
.ckb-image-card__curve { min-width: 0; padding: 3px; border: 1px solid var(--ckb-slate-100); border-radius: 8px; background: var(--ckb-white); }
.ckb-reference-figure { display: block; width: 100%; height: 100%; min-height: 184px; object-fit: contain; border-radius: 6px; background: var(--ckb-white); }
.ckb-cluster-profile-figure { display: block; width: 100%; max-height: 230px; object-fit: contain; padding: 10px 12px; background: var(--ckb-white); }
.ckb-image-card__force { border-top: 1px solid var(--ckb-slate-100); background: var(--ckb-white); }
.ckb-risk-curve { display: block; width: 100%; height: auto; }
.ckb-risk-curve__grid path { fill: none; stroke: #dbeafe; stroke-width: 1; }
.ckb-risk-curve__low, .ckb-risk-curve__high { fill: none; stroke-linecap: round; stroke-linejoin: round; stroke-width: 3; }
.ckb-risk-curve__low { stroke: #0d9488; }
.ckb-risk-curve__high { stroke: #d97706; }
.ckb-risk-curve__legend text, .ckb-risk-curve__axis { fill: var(--ckb-slate-600); font-size: 10px; font-family: ui-sans-serif, system-ui, sans-serif; }
.ckb-risk-curve__point--low circle { fill: #0d9488; }.ckb-risk-curve__point--low text { fill: #0f766e; }.ckb-risk-curve__point--high circle { fill: #d97706; }.ckb-risk-curve__point--high text { fill: #b45309; }
.ckb-risk-curve__point text { font-size: 10px; font-weight: 800; font-family: ui-sans-serif, system-ui, sans-serif; }
.ckb-image-card__explanation { display: flex; flex-direction: column; justify-content: center; min-width: 0; }
.ckb-image-card__explanation p { margin: 0; color: var(--ckb-slate-600); font-size: 0.78rem; line-height: 1.55; }
.ckb-image-card__explanation .ckb-image-card__risk { margin-bottom: 7px; color: var(--ckb-blue-900); font-size: 0.76rem; font-weight: 850; }

/* Theme selection is explicit: the page never follows the browser/system theme. */
html[data-ckb-theme="light"] .gradio-container { color-scheme: light !important; }
#ckb-shell[data-theme="dark"] {
  --ckb-blue-950: #082f49;
  --ckb-blue-900: #0c4a6e;
  --ckb-blue-700: #7dd3fc;
  --ckb-blue-600: #38bdf8;
  --ckb-blue-100: #153b58;
  --ckb-blue-50: #0f1d31;
  --ckb-cyan-100: #164e63;
  --ckb-green-700: #bbf7d0;
  --ckb-green-600: #4ade80;
  --ckb-green-100: #14532d;
  --ckb-amber-700: #fcd34d;
  --ckb-amber-100: #78350f;
  --ckb-slate-950: #f8fafc;
  --ckb-slate-700: #e2e8f0;
  --ckb-slate-600: #cbd5e1;
  --ckb-slate-400: #94a3b8;
  --ckb-slate-200: #334155;
  --ckb-slate-100: #1e293b;
  --ckb-white: #111827;
  --ckb-shadow-sm: 0 1px 2px rgb(0 0 0 / 0.32);
  --ckb-shadow-md: 0 16px 40px rgb(0 0 0 / 0.34);
  color-scheme: dark !important;
}
html[data-ckb-theme="dark"] .gradio-container {
  background:
    radial-gradient(circle at 10% 0%, rgb(8 47 73 / 0.76), transparent 24rem),
    radial-gradient(circle at 90% 9%, rgb(15 35 57 / 0.9), transparent 25rem),
    #020617;
  color: #f8fafc;
  color-scheme: dark !important;
}
html[data-ckb-theme="dark"] #ckb-shell,
html[data-ckb-theme="dark"] #outcome-table,
html[data-ckb-theme="dark"] #shap-result,
html[data-ckb-theme="dark"] #shap-gallery,
html[data-ckb-theme="dark"] .ckb-image-gallery,
html[data-ckb-theme="dark"] .ckb-image-card,
html[data-ckb-theme="dark"] .ckb-image-card__force { color-scheme: dark !important; }
html[data-ckb-theme="dark"] #ckb-shell .ckb-panel,
html[data-ckb-theme="dark"] #ckb-shell .ckb-results { background: rgb(15 23 42 / 0.94); border-color: var(--ckb-slate-200); }
html[data-ckb-theme="dark"] #ckb-shell .ckb-status--ready { background: #102a1c; border-color: #166534; }
html[data-ckb-theme="dark"] #ckb-shell .ckb-status--warning { background: #422006; border-color: #92400e; }
html[data-ckb-theme="dark"] #ckb-shell .ckb-result-metrics div { background: #172033; }
html[data-ckb-theme="dark"] #ckb-shell .ckb-image-card__context { background: #111c2d; }
html[data-ckb-theme="dark"] #ckb-shell .ckb-language-switch,
html[data-ckb-theme="dark"] #ckb-shell .ckb-theme-switch { background: #111827; border-color: var(--ckb-slate-200); }
html[data-ckb-theme="dark"] #ckb-shell .ckb-language-switch button[aria-pressed="true"],
html[data-ckb-theme="dark"] #ckb-shell .ckb-theme-switch button[aria-pressed="true"],
html[data-ckb-theme="dark"] #ckb-shell #predict-button,
html[data-ckb-theme="dark"] #ckb-shell #shap-result > button { color: #ffffff !important; }
html[data-ckb-theme="dark"] #ckb-shell .ckb-hero,
html[data-ckb-theme="dark"] #ckb-shell .ckb-hero h1,
html[data-ckb-theme="dark"] #ckb-shell .ckb-hero p {
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
}
html[data-ckb-theme="dark"] #ckb-shell #shap-result > button.open { color: #e0f2fe !important; }
html[data-ckb-theme="dark"] #ckb-shell .ckb-image-frame,
html[data-ckb-theme="dark"] #ckb-shell .ckb-reference-figure,
html[data-ckb-theme="dark"] #ckb-shell .ckb-cluster-profile-figure { background: #ffffff !important; color-scheme: only light !important; }
html[data-ckb-theme="dark"] body .options[role="listbox"] { border-color: #334155 !important; background: #111827 !important; }
html[data-ckb-theme="dark"] body .options[role="listbox"] [role="option"] { background: #111827 !important; color: #f8fafc !important; }
html[data-ckb-theme="dark"] body .options[role="listbox"] [role="option"]:hover,
html[data-ckb-theme="dark"] body .options[role="listbox"] [role="option"][aria-selected="true"] { background: #0f2f4a !important; color: #f8fafc !important; }

@media (max-width: 820px) {
  #ckb-shell { padding: 14px 12px 36px; }
  .ckb-hero { min-height: 0; border-radius: var(--ckb-radius-lg); }
  .ckb-trust-row { grid-template-columns: 1fr; }
  .ckb-section-heading { display: block; }
  .ckb-coding-note { max-width: none; margin-top: 14px; }
  .ckb-risk-row { grid-template-columns: 104px minmax(90px, 1fr) 48px; gap: 8px; }
  .ckb-shap-grid { grid-template-columns: 1fr; }
  .ckb-shap-card--cluster { grid-column: auto; }
  .ckb-image-grid--clusters { grid-template-columns: 1fr; }
  .ckb-image-grid--outcomes { grid-template-columns: 1fr; }
}

@media (max-width: 520px) {
  #ckb-shell { padding-inline: 8px; }
  .ckb-hero, .ckb-panel, .ckb-results { border-radius: 16px; }
  .ckb-hero { padding: 28px 22px; }
  .ckb-hero h1 { max-width: 11ch; }
  .ckb-panel, .ckb-results { padding: 18px; }
  .ckb-result-card__header, .ckb-risk-visual__header { display: block; }
  .ckb-result-badge, .ckb-legend { margin-top: 10px; }
  .ckb-shap-frame { height: 360px; }
  .ckb-outcome-table__header { display: block; }
  .ckb-outcome-table__header > p { margin-top: 7px; text-align: left; }
  .ckb-image-grid--clusters { grid-template-columns: 1fr; }
  .ckb-image-frame { height: 210px; }
  .ckb-image-card__context { grid-template-columns: 1fr; }
  .ckb-actions { align-items: stretch; }
  #predict-button, #reset-button { width: 100%; }
  .ckb-privacy-copy { flex-basis: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; }
}
"""


HEAD = """
<script>
(() => {
  const startMotion = () => {
    const root = document.querySelector('#ckb-shell');
    if (!root || root.dataset.motionReady === 'true') return Boolean(root);
    root.dataset.motionReady = 'true';

    const run = () => {
      if (!window.gsap) return;
      const media = window.gsap.matchMedia();
      media.add({ reduceMotion: '(prefers-reduced-motion: reduce)' }, (context) => {
        const hero = root.querySelector('.ckb-hero');
        const cards = root.querySelectorAll('.ckb-trust-card');
        const panel = root.querySelector('.ckb-panel');
        const results = root.querySelector('.ckb-results');
        if (context.conditions.reduceMotion) {
          window.gsap.set([hero, cards, panel, results], { autoAlpha: 1, clearProps: 'transform' });
          return;
        }
        const timeline = window.gsap.timeline({ defaults: { duration: 0.42, ease: 'power3.out' } });
        timeline
          .from(hero, { y: 18, autoAlpha: 0 })
          .from(cards, { y: 14, scale: 0.98, autoAlpha: 0, stagger: 0.07, ease: 'back.out(1.35)' }, '-=0.18')
          .from(panel, { y: 16, autoAlpha: 0 }, '-=0.20')
          .from(results, { y: 12, autoAlpha: 0 }, '-=0.24')
          // A transformed ancestor makes Gradio's fixed dropdown portal drift.
          .set([hero, cards, panel, results], { clearProps: 'transform,opacity,visibility' });
        return () => timeline.kill();
      });
    };

    if (window.gsap) {
      run();
      return true;
    }
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js';
    script.async = true;
    script.onload = run;
    script.onerror = () => { /* Animation is progressive enhancement only. */ };
    document.head.appendChild(script);
    return true;
  };

  if (!startMotion()) {
    const observer = new MutationObserver(() => {
      if (startMotion()) observer.disconnect();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
    window.setTimeout(() => observer.disconnect(), 7000);
  }
})();
</script>
<script>
(() => {
  const copy = {
    en: {
      eyebrow: 'CKB RESEARCH INTERFACE',
      title: '17-variable risk prediction',
      hero: 'One complete input returns a frozen K=3 cluster assignment and probabilities for 13 outcomes. The form and API use the same model inference path.',
      chips: ['17 input variables', '13 probability outputs', 'No persistent storage'],
      metrics: ['Complete input variables', 'Frozen nearest-centroid clustering', 'Outcome risk probabilities'],
      ready: '<strong>Model ready.</strong> Predictions can start immediately; submitted data is not persistently stored by this Space.',
      loading: '<strong>Warming the model in the background.</strong> You can complete the form while loading finishes.',
      inputKicker: 'INPUT WORKSPACE',
      inputTitle: 'Enter prediction variables',
      inputBody: 'All 17 variables are required. Categorical values must use the same codes as the training data; this service does not recode, impute, or retain input.',
      coding: 'Research-use note: verify category codes and units before interpreting results.',
      groups: [['Participant profile', 'Demographic and social context'], ['Lifestyle & self-report', 'Behaviour and self-rated health'], ['Measurements & medication', 'Body measures and blood-pressure information']],
      run: 'Run risk prediction',
      reset: 'Restore demo values',
      privacy: 'Temporary files are removed after inference. Do not use this tool for diagnosis or treatment decisions.',
      outputKicker: 'PREDICTION OUTPUT',
      outputTitle: 'Results and probability distribution',
      clusterPlaceholder: 'Submit a complete set of variables to show cluster assignment and distance information here.',
      visualPlaceholder: 'The probability distribution will appear after prediction completes.',
      clusterKicker: 'CLUSTER ASSIGNMENT',
      cluster: 'Risk cluster',
      assigned: 'Assigned',
      review: 'Review suggested',
      nearest: 'Nearest centroid distance',
      margin: 'Separation from next-nearest centroid',
      visualTitle: 'Probability across 13 outcomes',
      visualBody: 'The marker indicates the frozen Youden threshold for each outcome. This is for research interpretation, not clinical diagnosis.',
      low: 'Below threshold',
      high: 'At or above threshold',
      tableLabel: 'Outcome prediction details',
      tableHeaders: ['Code', 'Outcome', 'Probability', 'Frozen threshold', 'Risk decision'],
      json: 'View complete JSON response',
      footer: 'For programmatic use: the stable JSON endpoint is <code>/predict</code>; model warm-up is <code>/warmup</code>. Use the “Use via API” panel for examples.'
    },
    zh: {
      eyebrow: 'CKB 研究界面',
      title: '\u0031\u0037 \u53d8\u91cf\u98ce\u9669\u9884\u6d4b',
      hero: '\u4e00\u6b21\u5b8c\u6574\u8f93\u5165\uff0c\u8fd4\u56de\u51bb\u7ed3 K=3 \u805a\u7c7b\u5206\u914d\u4e0e \u0031\u0033 \u9879\u7ed3\u5c40\u98ce\u9669\u6982\u7387\u3002\u8868\u5355\u4e0e API \u5171\u7528\u540c\u4e00\u5957\u6a21\u578b\u63a8\u7406\u903b\u8f91\u3002',
      chips: ['\u0031\u0037 \u4e2a\u8f93\u5165\u53d8\u91cf', '\u0031\u0033 \u9879\u6982\u7387\u7ed3\u679c', '\u65e0\u6301\u4e45\u5316\u4fdd\u5b58'],
      metrics: ['\u5b8c\u6574\u8f93\u5165\u53d8\u91cf', '\u51bb\u7ed3\u6700\u8fd1\u4e2d\u5fc3\u805a\u7c7b', '\u7ed3\u5c40\u98ce\u9669\u6982\u7387'],
      ready: '<strong>\u6a21\u578b\u5df2\u5c31\u7eea\u3002</strong>\u53ef\u4ee5\u7acb\u5373\u63d0\u4ea4\u9884\u6d4b\uff1b\u8fd9\u4e2a Space \u4e0d\u4f1a\u6301\u4e45\u4fdd\u5b58\u63d0\u4ea4\u6570\u636e\u3002',
      loading: '<strong>\u6b63\u5728\u540e\u53f0\u9884\u70ed\u6a21\u578b\u3002</strong>\u4f60\u53ef\u4ee5\u5148\u586b\u5199\u8868\u5355\uff1b\u52a0\u8f7d\u5b8c\u6210\u540e\u5373\u53ef\u63d0\u4ea4\u3002',
      inputKicker: '\u8f93\u5165\u5de5\u4f5c\u533a',
      inputTitle: '\u586b\u5199\u9884\u6d4b\u53d8\u91cf',
      inputBody: '\u6240\u6709 \u0031\u0037 \u9879\u5747\u4e3a\u5fc5\u586b\u3002\u5206\u7c7b\u53d8\u91cf\u5fc5\u987b\u4e0e\u8bad\u7ec3\u6570\u636e\u4f7f\u7528\u76f8\u540c\u7f16\u7801\uff1b\u672c\u670d\u52a1\u4e0d\u4f1a\u91cd\u65b0\u7f16\u7801\u3001\u63d2\u8865\u6216\u4fdd\u5b58\u8f93\u5165\u3002',
      coding: '\u7814\u7a76\u7528\u9014\u63d0\u793a\uff1a\u8bf7\u5728\u89e3\u91ca\u7ed3\u679c\u524d\u6838\u5bf9\u5206\u7c7b\u7f16\u7801\u4e0e\u91cf\u7eb2\u3002',
      groups: [['\u57fa\u672c\u8d44\u6599', '\u4eba\u53e3\u4e0e\u793e\u4f1a\u7279\u5f81'], ['\u751f\u6d3b\u4e0e\u611f\u53d7', '\u884c\u4e3a\u53ca\u5065\u5eb7\u81ea\u8bc4'], ['\u4f53\u5f81\u4e0e\u7528\u836f', '\u8eab\u4f53\u6d4b\u91cf\u4e0e\u8840\u538b\u4fe1\u606f']],
      run: '\u8fd0\u884c\u98ce\u9669\u9884\u6d4b',
      reset: '\u6062\u590d\u6f14\u793a\u6570\u636e',
      privacy: '\u63a8\u7406\u7ed3\u675f\u540e\u4f1a\u6e05\u9664\u4e34\u65f6\u6587\u4ef6\uff1b\u8bf7\u52ff\u5c06\u672c\u5de5\u5177\u7528\u4e8e\u8bca\u65ad\u6216\u6cbb\u7597\u51b3\u7b56\u3002',
      outputKicker: '\u9884\u6d4b\u8f93\u51fa',
      outputTitle: '\u7ed3\u679c\u4e0e\u6982\u7387\u5206\u5e03',
      clusterPlaceholder: '\u63d0\u4ea4\u4e00\u7ec4\u5b8c\u6574\u53d8\u91cf\u540e\uff0c\u6b64\u5904\u5c06\u663e\u793a\u805a\u7c7b\u5206\u914d\u4e0e\u8ddd\u79bb\u4fe1\u606f\u3002',
      visualPlaceholder: '\u6982\u7387\u5206\u5e03\u56fe\u5c06\u5728\u9884\u6d4b\u5b8c\u6210\u540e\u51fa\u73b0\u3002',
      clusterKicker: '\u805a\u7c7b\u5206\u914d',
      cluster: '\u98ce\u9669\u805a\u7c7b',
      assigned: '\u5df2\u5b8c\u6210\u5206\u914d',
      review: '\u5efa\u8bae\u590d\u6838',
      nearest: '\u6700\u8fd1\u4e2d\u5fc3\u8ddd\u79bb',
      margin: '\u4e0e\u6b21\u8fd1\u4e2d\u5fc3\u7684\u95f4\u9694',
      visualTitle: '\u0031\u0033 \u9879\u7ed3\u5c40\u7684\u9884\u6d4b\u6982\u7387',
      visualBody: '\u6a2a\u7ebf\u6807\u8bb0\u5404\u7ed3\u5c40\u51bb\u7ed3\u7684 Youden \u9608\u503c\uff1b\u6b64\u56fe\u7528\u4e8e\u7814\u7a76\u7ed3\u679c\u9605\u8bfb\uff0c\u5e76\u975e\u4e34\u5e8a\u8bca\u65ad\u3002',
      low: '\u4f4e\u4e8e\u9608\u503c',
      high: '\u8fbe\u5230\u6216\u9ad8\u4e8e\u9608\u503c',
      tableLabel: '\u7ed3\u5c40\u9884\u6d4b\u660e\u7ec6',
      tableHeaders: ['\u4ee3\u7801', '\u9884\u6d4b\u7ed3\u5c40', '\u6982\u7387', '\u51bb\u7ed3\u9608\u503c', '\u98ce\u9669\u5224\u5b9a'],
      json: '\u67e5\u770b\u5b8c\u6574 JSON \u54cd\u5e94',
      footer: '\u7528\u4e8e\u7a0b\u5e8f\u5316\u8c03\u7528\uff1a\u7a33\u5b9a JSON \u63a5\u53e3\u4e3a <code>/predict</code>\uff1b\u6a21\u578b\u9884\u70ed\u63a5\u53e3\u4e3a <code>/warmup</code>\u3002\u53ef\u4ece Space \u7684 “Use via API” \u9762\u677f\u83b7\u53d6\u8c03\u7528\u793a\u4f8b\u3002'
    }
  };

  const fields = {
    en: {
      labels: { sex: 'Sex (training code)', age: 'Age (years)', edu_level: 'Education (training code)', marital_status: 'Marital status (training code)', work: 'Employment (training code)', retire: 'Retirement (training code)', hh_size: 'Household size', smoking: 'Smoking (training code)', alcohol: 'Alcohol use (training code)', height_cm: 'Height (cm)', weight_kg: 'Weight (kg)', waist_cm: 'Waist (cm)', sbp_mmhg: 'Systolic BP (mmHg)', dbp_mmhg: 'Diastolic BP (mmHg)', bp_drugs: 'BP medication (training code)', self_health: 'Self-rated health (training code)', chronic_pain: 'Chronic pain (training code)' },
      help: { sex: 'Use the original categorical code from the training data.', age: 'Enter completed years.', edu_level: 'Use the original categorical code from the training data.', marital_status: 'Use the original categorical code from the training data.', work: 'Use the original categorical code from the training data.', retire: 'Use the original categorical code from the training data.', hh_size: 'Number of people in the household.', smoking: 'Use the original categorical code from the training data.', alcohol: 'Use the original categorical code from the training data.', height_cm: 'Continuous value in centimetres.', weight_kg: 'Continuous value in kilograms.', waist_cm: 'Continuous value in centimetres.', sbp_mmhg: 'Continuous value in mmHg.', dbp_mmhg: 'Continuous value in mmHg.', bp_drugs: 'Use the original categorical code from the training data.', self_health: 'Use the original categorical code from the training data.', chronic_pain: 'Use the original categorical code from the training data.' }
    },
    zh: {
      labels: { sex: '\u6027\u522b\u7f16\u7801', age: '\u5e74\u9f84\uff08\u5c81\uff09', edu_level: '\u6559\u80b2\u7a0b\u5ea6\u7f16\u7801', marital_status: '\u5a5a\u59fb\u72b6\u6001\u7f16\u7801', work: '\u5de5\u4f5c\u72b6\u6001\u7f16\u7801', retire: '\u9000\u4f11\u72b6\u6001\u7f16\u7801', hh_size: '\u5bb6\u5ead\u4eba\u53e3\u6570', smoking: '\u5438\u70df\u7f16\u7801', alcohol: '\u996e\u9152\u7f16\u7801', height_cm: '\u8eab\u9ad8\uff08cm\uff09', weight_kg: '\u4f53\u91cd\uff08kg\uff09', waist_cm: '\u8170\u56f4\uff08cm\uff09', sbp_mmhg: '\u6536\u7f29\u538b\uff08mmHg\uff09', dbp_mmhg: '\u8212\u5f20\u538b\uff08mmHg\uff09', bp_drugs: '\u964d\u538b\u836f\u4f7f\u7528\u7f16\u7801', self_health: '\u81ea\u8bc4\u5065\u5eb7\u7f16\u7801', chronic_pain: '\u6162\u6027\u75bc\u75db\u7f16\u7801' },
      help: { sex: '\u8bf7\u4f7f\u7528\u8bad\u7ec3\u6570\u636e\u4e2d\u7684\u539f\u59cb\u5206\u7c7b\u7f16\u7801\u3002', age: '\u4ee5\u5b8c\u6574\u5c81\u6570\u586b\u5199\u3002', edu_level: '\u8bf7\u4f7f\u7528\u8bad\u7ec3\u6570\u636e\u4e2d\u7684\u539f\u59cb\u5206\u7c7b\u7f16\u7801\u3002', marital_status: '\u8bf7\u4f7f\u7528\u8bad\u7ec3\u6570\u636e\u4e2d\u7684\u539f\u59cb\u5206\u7c7b\u7f16\u7801\u3002', work: '\u8bf7\u4f7f\u7528\u8bad\u7ec3\u6570\u636e\u4e2d\u7684\u539f\u59cb\u5206\u7c7b\u7f16\u7801\u3002', retire: '\u8bf7\u4f7f\u7528\u8bad\u7ec3\u6570\u636e\u4e2d\u7684\u539f\u59cb\u5206\u7c7b\u7f16\u7801\u3002', hh_size: '\u540c\u4f4f\u5bb6\u5ead\u6210\u5458\u4eba\u6570\u3002', smoking: '\u8bf7\u4f7f\u7528\u8bad\u7ec3\u6570\u636e\u4e2d\u7684\u539f\u59cb\u5206\u7c7b\u7f16\u7801\u3002', alcohol: '\u8bf7\u4f7f\u7528\u8bad\u7ec3\u6570\u636e\u4e2d\u7684\u539f\u59cb\u5206\u7c7b\u7f16\u7801\u3002', height_cm: '\u8fde\u7eed\u6570\u503c\uff0c\u5355\u4f4d\u4e3a\u5398\u7c73\u3002', weight_kg: '\u8fde\u7eed\u6570\u503c\uff0c\u5355\u4f4d\u4e3a\u5343\u514b\u3002', waist_cm: '\u8fde\u7eed\u6570\u503c\uff0c\u5355\u4f4d\u4e3a\u5398\u7c73\u3002', sbp_mmhg: '\u8fde\u7eed\u6570\u503c\uff0c\u5355\u4f4d\u4e3a mmHg\u3002', dbp_mmhg: '\u8fde\u7eed\u6570\u503c\uff0c\u5355\u4f4d\u4e3a mmHg\u3002', bp_drugs: '\u8bf7\u4f7f\u7528\u8bad\u7ec3\u6570\u636e\u4e2d\u7684\u539f\u59cb\u5206\u7c7b\u7f16\u7801\u3002', self_health: '\u8bf7\u4f7f\u7528\u8bad\u7ec3\u6570\u636e\u4e2d\u7684\u539f\u59cb\u5206\u7c7b\u7f16\u7801\u3002', chronic_pain: '\u8bf7\u4f7f\u7528\u8bad\u7ec3\u6570\u636e\u4e2d\u7684\u539f\u59cb\u5206\u7c7b\u7f16\u7801\u3002' }
    }
  };

  Object.assign(copy.en, {
    inputBody: 'All 17 variables are required. Choose categorical values by their descriptions; the frozen model encoding is preserved internally and no input is retained.',
    coding: 'Research-use note: verify the selected description and units before interpreting results.',
    privacy: 'Temporary SHAP explanation files expire automatically. Do not use this tool for diagnosis or treatment decisions.',
    shapExpand: 'Show 14 SHAP force plots',
    shapCollapse: 'Hide SHAP force plots',
    shapKicker: 'SHAP EXPLANATIONS',
    shapTitle: '14 force plots',
    shapDescription: 'One force plot explains the assigned cluster; the remaining 13 explain each outcome probability surrogate.',
    shapCluster: 'Cluster assignment',
    shapOutcome: 'Outcome explanation',
    shapPlaceholder: 'Run a prediction to generate 14 SHAP force plots.'
  });
  Object.assign(copy.zh, {
    inputBody: '\u6240\u6709 17 \u9879\u5747\u4e3a\u5fc5\u586b\u3002\u5206\u7c7b\u53d8\u91cf\u901a\u8fc7\u6587\u5b57\u9009\u9879\u9009\u62e9\uff1b\u7cfb\u7edf\u5728\u540e\u53f0\u4fdd\u6301\u4e0e\u8bad\u7ec3\u6570\u636e\u4e00\u81f4\u7684\u51bb\u7ed3\u7f16\u7801\uff0c\u4e0d\u4f1a\u4fdd\u5b58\u8f93\u5165\u3002',
    coding: '\u7814\u7a76\u7528\u9014\u63d0\u793a\uff1a\u8bf7\u5728\u89e3\u91ca\u7ed3\u679c\u524d\u6838\u5bf9\u6240\u9009\u6587\u5b57\u63cf\u8ff0\u4e0e\u91cf\u7eb2\u3002',
    privacy: '\u4e34\u65f6 SHAP \u89e3\u91ca\u6587\u4ef6\u4f1a\u81ea\u52a8\u8fc7\u671f\u6e05\u7406\uff1b\u8bf7\u52ff\u5c06\u672c\u5de5\u5177\u7528\u4e8e\u8bca\u65ad\u6216\u6cbb\u7597\u51b3\u7b56\u3002',
    shapExpand: '\u5c55\u5f00\u67e5\u770b 14 \u5f20 SHAP \u529b\u56fe',
    shapCollapse: '\u6536\u8d77 SHAP \u529b\u56fe',
    shapKicker: 'SHAP \u89e3\u91ca',
    shapTitle: '14 \u5f20\u529b\u56fe',
    shapDescription: '1 \u5f20\u529b\u56fe\u89e3\u91ca\u5df2\u5206\u914d\u7684\u805a\u7c7b\uff1b\u53e6\u5916 13 \u5f20\u5206\u522b\u89e3\u91ca\u5404\u7ed3\u5c40\u6982\u7387\u4ee3\u7406\u6a21\u578b\u3002',
    shapCluster: '\u805a\u7c7b\u5206\u914d',
    shapOutcome: '\u7ed3\u5c40\u89e3\u91ca',
    shapPlaceholder: '\u8fd0\u884c\u9884\u6d4b\u540e\u751f\u6210 14 \u5f20 SHAP \u529b\u56fe\u3002'
  });
  Object.assign(fields.en.labels, {
    sex: 'Sex', edu_level: 'Education level', marital_status: 'Married or partnered',
    work: 'Currently working', retire: 'Retired', smoking: 'Smoking', alcohol: 'Alcohol use',
    bp_drugs: 'Blood-pressure medication', self_health: 'Self-rated health', chronic_pain: 'Chronic pain'
  });
  Object.assign(fields.en.help, {
    sex: 'Choose the description that matches the study definition.', edu_level: 'Choose the description that matches the study definition.',
    marital_status: 'Choose the description that matches the study definition.', work: 'Choose the description that matches the study definition.',
    retire: 'Choose the description that matches the study definition.', smoking: 'Choose the description that matches the study definition.',
    alcohol: 'Choose the description that matches the study definition.', bp_drugs: 'Choose the description that matches the study definition.',
    self_health: 'Choose the description that matches the study definition.', chronic_pain: 'Choose the description that matches the study definition.'
  });
  Object.assign(fields.zh.labels, {
    sex: '\u6027\u522b', edu_level: '\u6559\u80b2\u7a0b\u5ea6', marital_status: '\u5a5a\u59fb\u6216\u4f34\u4fa3\u72b6\u6001',
    work: '\u5f53\u524d\u5de5\u4f5c', retire: '\u5df2\u9000\u4f11', smoking: '\u5438\u70df', alcohol: '\u996e\u9152',
    bp_drugs: '\u964d\u538b\u836f\u4f7f\u7528', self_health: '\u81ea\u8bc4\u5065\u5eb7', chronic_pain: '\u6162\u6027\u75bc\u75db'
  });
  Object.assign(fields.zh.help, {
    sex: '\u8bf7\u9009\u62e9\u4e0e\u7814\u7a76\u5b9a\u4e49\u76f8\u7b26\u7684\u6587\u5b57\u9009\u9879\u3002', edu_level: '\u8bf7\u9009\u62e9\u4e0e\u7814\u7a76\u5b9a\u4e49\u76f8\u7b26\u7684\u6587\u5b57\u9009\u9879\u3002',
    marital_status: '\u8bf7\u9009\u62e9\u4e0e\u7814\u7a76\u5b9a\u4e49\u76f8\u7b26\u7684\u6587\u5b57\u9009\u9879\u3002', work: '\u8bf7\u9009\u62e9\u4e0e\u7814\u7a76\u5b9a\u4e49\u76f8\u7b26\u7684\u6587\u5b57\u9009\u9879\u3002',
    retire: '\u8bf7\u9009\u62e9\u4e0e\u7814\u7a76\u5b9a\u4e49\u76f8\u7b26\u7684\u6587\u5b57\u9009\u9879\u3002', smoking: '\u8bf7\u9009\u62e9\u4e0e\u7814\u7a76\u5b9a\u4e49\u76f8\u7b26\u7684\u6587\u5b57\u9009\u9879\u3002',
    alcohol: '\u8bf7\u9009\u62e9\u4e0e\u7814\u7a76\u5b9a\u4e49\u76f8\u7b26\u7684\u6587\u5b57\u9009\u9879\u3002', bp_drugs: '\u8bf7\u9009\u62e9\u4e0e\u7814\u7a76\u5b9a\u4e49\u76f8\u7b26\u7684\u6587\u5b57\u9009\u9879\u3002',
    self_health: '\u8bf7\u9009\u62e9\u4e0e\u7814\u7a76\u5b9a\u4e49\u76f8\u7b26\u7684\u6587\u5b57\u9009\u9879\u3002', chronic_pain: '\u8bf7\u9009\u62e9\u4e0e\u7814\u7a76\u5b9a\u4e49\u76f8\u7b26\u7684\u6587\u5b57\u9009\u9879\u3002'
  });

  // Keep the visible UI concise. The frozen numeric representation stays in
  // the component value and is never exposed as 0/1/2/3/4 to visitors.
  Object.assign(copy.en, {
    hero: 'One complete input returns a frozen K=3 cluster assignment and probabilities for 13 outcomes. The model was developed using the China Kadoorie Biobank.',
    inputBody: '',
    coding: '',
    outputTitle: 'Prediction results',
    themeLabel: 'Colour theme',
    themeLight: 'Light',
    themeDark: 'Dark',
    shapExpand: 'Show image results',
    shapCollapse: 'Hide image results',
    shapKicker: 'IMAGE RESULTS',
    shapTitle: 'Assigned cluster explanation and 13 outcome panels',
    shapDescription: 'Each outcome panel places its cumulative-risk reference and brief interpretation above the related SHAP force plot.',
    shapCluster: 'Assigned cluster explanation',
    shapOutcome: 'Outcome risk explanations',
    shapPlaceholder: 'Run a prediction to generate image results.'
  });
  Object.assign(copy.zh, {
    hero: '\u4e00\u6b21\u5b8c\u6574\u8f93\u5165\uff0c\u8fd4\u56de\u51bb\u7ed3 K=3 \u805a\u7c7b\u5206\u914d\u4e0e 13 \u9879\u7ed3\u5c40\u98ce\u9669\u6982\u7387\u3002\u6a21\u578b\u57fa\u4e8e China Kadoorie Biobank \u5f00\u53d1\u3002',
    inputBody: '',
    coding: '',
    outputTitle: '\u9884\u6d4b\u7ed3\u679c',
    themeLabel: '\u9875\u9762\u4e3b\u9898',
    themeLight: '\u6d45\u8272',
    themeDark: '\u6df1\u8272',
    shapExpand: '\u5c55\u5f00\u67e5\u770b\u56fe\u7247\u7ed3\u679c',
    shapCollapse: '\u6536\u8d77\u56fe\u7247\u7ed3\u679c',
    shapKicker: '\u56fe\u7247\u7ed3\u679c',
    shapTitle: '\u5df2\u5206\u914d\u805a\u7c7b\u89e3\u91ca\u4e0e 13 \u9879\u7ed3\u5c40\u98ce\u9669\u9762\u677f',
    shapDescription: '\u6bcf\u4e2a\u7ed3\u5c40\u9762\u677f\u5747\u5c06\u7d2f\u79ef\u98ce\u9669\u53c2\u8003\u548c\u7b80\u77ed\u89e3\u8bfb\u7f6e\u4e8e\u76f8\u5173 SHAP \u529b\u56fe\u4e0a\u65b9\u3002',
    shapCluster: '\u5df2\u5206\u914d\u805a\u7c7b\u89e3\u91ca',
    shapOutcome: '\u7ed3\u5c40\u98ce\u9669\u89e3\u91ca',
    shapPlaceholder: '\u8fd0\u884c\u9884\u6d4b\u540e\u751f\u6210\u56fe\u7247\u7ed3\u679c\u3002'
  });

  const dropdownCopy = {
    'Male': { en: 'Male', zh: '\u7537' }, 'Female': { en: 'Female', zh: '\u5973' },
    'Low': { en: 'Low', zh: '\u4f4e' }, 'Intermediate': { en: 'Intermediate', zh: '\u4e2d' }, 'High': { en: 'High', zh: '\u9ad8' },
    'Other observed status': { en: 'Other observed status', zh: '\u5176\u4ed6\u89c2\u5bdf\u72b6\u6001' },
    'Married or partnered': { en: 'Married or partnered', zh: '\u5df2\u5a5a\u6216\u6709\u4f34\u4fa3' },
    'No': { en: 'No', zh: '\u5426' }, 'Yes': { en: 'Yes', zh: '\u662f' },
    'Very good or excellent': { en: 'Very good or excellent', zh: '\u975e\u5e38\u597d\u6216\u6781\u597d' },
    'Good': { en: 'Good', zh: '\u597d' }, 'Fair or regular': { en: 'Fair or regular', zh: '\u4e00\u822c' },
    'Poor or very poor': { en: 'Poor or very poor', zh: '\u5dee\u6216\u5f88\u5dee' }
  };

  const setText = (node, value) => {
    if (node && node.textContent !== value) node.textContent = value;
  };
  const setHtml = (node, value) => {
    if (node && node.innerHTML !== value) node.innerHTML = value;
  };
  const translateDynamicContent = (root, language) => {
    const textKey = language === 'zh' ? 'localeZh' : 'localeEn';
    const ariaKey = language === 'zh' ? 'ariaZh' : 'ariaEn';
    root.querySelectorAll('[data-locale-en]').forEach((node) => setText(node, node.dataset[textKey] || ''));
    root.querySelectorAll('[data-aria-en]').forEach((node) => {
      const value = node.dataset[ariaKey];
      if (value) node.setAttribute('aria-label', value);
    });
  };
  const dropdownEntry = (value) => {
    const normalized = String(value || '').replace(/^[✓✔]\\s*/, '').trim();
    return Object.values(dropdownCopy).find((entry) => entry.en === normalized || entry.zh === normalized);
  };
  const translateDropdownText = (root, language) => {
    root.querySelectorAll('.ckb-form-card input').forEach((input) => {
      const entry = dropdownEntry(input.value);
      if (entry) input.value = entry[language];
    });
    document.querySelectorAll('[role="option"]').forEach((option) => {
      const entry = dropdownEntry(option.textContent);
      if (entry) option.textContent = entry[language];
    });
  };

  const initLocale = () => {
    const root = document.querySelector('#ckb-shell');
    if (!root || root.dataset.localeReady === 'true') return Boolean(root);
    const trustRow = root.querySelector('.ckb-trust-row');
    if (!trustRow) return false;
    root.dataset.localeReady = 'true';
    const syncShapDisclosure = () => {
      const button = root.querySelector('#shap-result > button');
      if (!button) return;
      const text = copy[root.dataset.language || 'en'];
      const expanded = button.classList.contains('open');
      const label = expanded ? text.shapCollapse : text.shapExpand;
      setText(button, label);
      button.setAttribute('aria-label', label);
    };
    const setupShapDisclosure = () => {
      const button = root.querySelector('#shap-result > button');
      if (!button || button.dataset.ckbDisclosureReady === 'true') return;
      button.dataset.ckbDisclosureReady = 'true';
      new MutationObserver(syncShapDisclosure).observe(button, {
        attributes: true,
        attributeFilter: ['class'],
      });
    };
    let language = 'en';
    try { language = localStorage.getItem('ckb-language') === 'zh' ? 'zh' : 'en'; } catch (_) { /* Default to English. */ }
    let theme = 'light';
    try { theme = localStorage.getItem('ckb-theme') === 'dark' ? 'dark' : 'light'; } catch (_) { /* Theme is page-controlled and defaults to light. */ }

    const bar = document.createElement('div');
    bar.className = 'ckb-language-bar';
    bar.innerHTML = '<div class="ckb-language-switch" role="group" aria-label="Language selector"><button type="button" data-language="en">English</button><button type="button" data-language="zh">\u4e2d\u6587</button></div><div class="ckb-theme-switch" role="group" data-theme-switch="true" aria-label="Colour theme"><button type="button" data-theme="light">Light</button><button type="button" data-theme="dark">Dark</button></div>';
    trustRow.insertAdjacentElement('afterend', bar);

    const applyTheme = () => {
      root.dataset.theme = theme;
      document.documentElement.dataset.ckbTheme = theme;
      root.querySelectorAll('[data-theme]').forEach((button) => {
        button.setAttribute('aria-pressed', String(button.dataset.theme === theme));
      });
    };

    const applyLanguage = () => {
      const text = copy[language];
      root.dataset.language = language;
      root.querySelectorAll('[data-language]').forEach((button) => {
        button.setAttribute('aria-pressed', String(button.dataset.language === language));
      });
      const themeSwitch = root.querySelector('[data-theme-switch]');
      if (themeSwitch) themeSwitch.setAttribute('aria-label', text.themeLabel);
      setText(root.querySelector('[data-theme="light"]'), text.themeLight);
      setText(root.querySelector('[data-theme="dark"]'), text.themeDark);
      setText(root.querySelector('.ckb-skip'), language === 'en' ? 'Skip to prediction inputs' : '\u8df3\u8f6c\u5230\u9884\u6d4b\u8f93\u5165');
      const eyebrow = root.querySelector('.ckb-eyebrow');
      if (eyebrow) setText(eyebrow.lastChild, text.eyebrow);
      setText(root.querySelector('.ckb-hero h1'), text.title);
      setText(root.querySelector('.ckb-hero p'), text.hero);
      root.querySelectorAll('.ckb-chip').forEach((chip, index) => setText(chip.lastChild, ` ${text.chips[index] || ''}`));
      root.querySelectorAll('.ckb-trust-card span').forEach((node, index) => setText(node, text.metrics[index] || ''));

      const status = root.querySelector('.ckb-status span:last-child');
      if (status) setHtml(status, root.querySelector('.ckb-status--ready') ? text.ready : text.loading);
      setText(root.querySelector('.ckb-section-heading .ckb-section-kicker'), text.inputKicker);
      setText(root.querySelector('.ckb-section-heading h2'), text.inputTitle);
      setText(root.querySelector('.ckb-section-heading p'), text.inputBody);
      setText(root.querySelector('.ckb-coding-note'), text.coding);
      Array.from(root.querySelectorAll('.ckb-form-card'))
        .filter((card) => !card.parentElement.closest('.ckb-form-card'))
        .forEach((card, index) => {
        setText(card.querySelector('h3'), text.groups[index]?.[0] || '');
        setText(card.querySelector('p'), text.groups[index]?.[1] || '');
        });
      Object.keys(fields[language].labels).forEach((field) => {
        const component = root.querySelector(`#field-${field}`);
        if (!component) return;
        setText(component.querySelector('[data-testid="block-info"]'), fields[language].labels[field]);
        component.querySelector('input')?.setAttribute('aria-label', fields[language].labels[field]);
      });
      translateDropdownText(root, language);
      setText(root.querySelector('#predict-button'), text.run);
      setText(root.querySelector('#reset-button'), text.reset);
      const privacy = root.querySelector('.ckb-privacy-copy');
      if (privacy) {
        const icon = privacy.querySelector('svg')?.outerHTML || '';
        setHtml(privacy, `${icon}${text.privacy}`);
      }
      setText(root.querySelector('.ckb-results-header .ckb-section-kicker'), text.outputKicker);
      setText(root.querySelector('.ckb-results-header h2'), text.outputTitle);
      setText(root.querySelector('.ckb-result-placeholder'), root.querySelector('#cluster-result .ckb-result-placeholder') ? text.clusterPlaceholder : text.visualPlaceholder);
      const placeholders = root.querySelectorAll('.ckb-result-placeholder');
      setText(placeholders[0], text.clusterPlaceholder);
      setText(placeholders[1], text.visualPlaceholder);

      const clusterTitle = root.querySelector('.ckb-result-card h3');
      if (clusterTitle) {
        const label = clusterTitle.textContent.split(/[:：]/).pop().trim();
        setText(clusterTitle, `${text.cluster}: ${label}`);
      }
      setText(root.querySelector('.ckb-result-card .ckb-result-kicker'), text.clusterKicker);
      const badge = root.querySelector('.ckb-result-badge');
      if (badge) setText(badge, badge.classList.contains('ckb-result-badge--review') ? text.review : text.assigned);
      const metrics = root.querySelectorAll('.ckb-result-metrics dt');
      setText(metrics[0], text.nearest);
      setText(metrics[1], text.margin);
      setText(root.querySelector('.ckb-risk-visual h3'), text.visualTitle);
      setText(root.querySelector('.ckb-risk-visual p'), text.visualBody);
      root.querySelectorAll('.ckb-legend span').forEach((legend, index) => {
        const marker = legend.querySelector('i')?.outerHTML || '';
        setHtml(legend, `${marker}${index === 0 ? text.low : text.high}`);
      });
      setText(root.querySelector('#outcome-table .label p'), text.tableLabel);
      root.querySelectorAll('#outcome-table th [role="button"]').forEach((node, index) => setText(node, text.tableHeaders[index] || ''));
      root.querySelectorAll('#outcome-table th').forEach((node, index) => node.setAttribute('title', text.tableHeaders[index] || ''));
      root.querySelectorAll('#outcome-table [role="button"]').forEach((node) => {
        const value = node.textContent.trim();
        if (value === '\u8fbe\u5230\u6216\u9ad8\u4e8e\u9608\u503c' || value === 'At or above threshold') setText(node, text.high);
        if (value === '\u4f4e\u4e8e\u9608\u503c' || value === 'Below threshold') setText(node, text.low);
      });
      setupShapDisclosure();
      syncShapDisclosure();
      setText(root.querySelector('[data-shap-kicker]'), text.shapKicker);
      setText(root.querySelector('[data-shap-title]'), text.shapTitle);
      setText(root.querySelector('[data-shap-description]'), text.shapDescription);
      root.querySelectorAll('[data-shap-kind]').forEach((node) => {
        setText(node, node.dataset.shapKind === 'cluster' ? text.shapCluster : text.shapOutcome);
      });
      root.querySelectorAll('.ckb-shap-placeholder').forEach((node) => setText(node, text.shapPlaceholder));
      setText(root.querySelector('[data-image-kicker]'), text.shapKicker);
      setText(root.querySelector('[data-image-title]'), text.shapTitle);
      setText(root.querySelector('[data-image-description]'), text.shapDescription);
      setText(root.querySelector('[data-image-cluster-title]'), text.shapCluster);
      setText(root.querySelector('[data-image-outcome-title]'), text.shapOutcome);
      root.querySelectorAll('.ckb-image-placeholder').forEach((node) => setText(node, text.shapPlaceholder));
      translateDynamicContent(root, language);
      const jsonButton = root.querySelector('#raw-result > button');
      if (jsonButton) setText(jsonButton, text.json);
      setHtml(root.querySelector('.ckb-footer-note'), text.footer);
    };

    bar.addEventListener('click', (event) => {
      const themeButton = event.target.closest('button[data-theme]');
      if (themeButton) {
        theme = themeButton.dataset.theme === 'dark' ? 'dark' : 'light';
        try { localStorage.setItem('ckb-theme', theme); } catch (_) { /* Preference remains for this page. */ }
        applyTheme();
        return;
      }
      const button = event.target.closest('button[data-language]');
      if (!button) return;
      language = button.dataset.language === 'zh' ? 'zh' : 'en';
      try { localStorage.setItem('ckb-language', language); } catch (_) { /* Preference remains for this page. */ }
      applyLanguage();
    });
    document.addEventListener('click', () => {
      requestAnimationFrame(() => translateDropdownText(root, language));
    }, true);
    applyTheme();
    applyLanguage();
    let scheduled = false;
    const observer = new MutationObserver(() => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => { scheduled = false; applyLanguage(); });
    });
    observer.observe(root, { childList: true, subtree: true });
  };

  if (!initLocale()) {
    const observer = new MutationObserver(() => {
      if (initLocale()) observer.disconnect();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
    window.setTimeout(() => observer.disconnect(), 7000);
  }
})();
</script>
"""


_predictor: CKBSingleSamplePredictor | None = None
_load_lock = threading.Lock()
_inference_lock = threading.Lock()


def get_predictor() -> CKBSingleSamplePredictor:
    """Load the large model bundle once, on the first prediction request."""
    global _predictor
    if _predictor is None:
        with _load_lock:
            if _predictor is None:
                _predictor = CKBSingleSamplePredictor(MODEL_DIR)
    return _predictor


def _clean_expired_shap_reports() -> None:
    """Remove old, per-request SHAP files from the ephemeral Space filesystem."""
    if not SHAP_CACHE_DIR.exists():
        return
    deadline = time.time() - SHAP_CACHE_TTL_SECONDS
    for report_dir in SHAP_CACHE_DIR.iterdir():
        try:
            if report_dir.is_dir() and report_dir.stat().st_mtime < deadline:
                shutil.rmtree(report_dir, ignore_errors=True)
        except OSError:
            continue


def _ensure_light_shap_canvas(plot_path: str) -> None:
    """Keep generated SHAP HTML legible when the host browser uses dark mode."""
    path = Path(plot_path)
    try:
        document = path.read_text(encoding="utf-8")
        if SHAP_LIGHT_CANVAS_MARKER in document:
            return
        if "</head>" not in document:
            return
        path.write_text(
            document.replace("</head>", SHAP_LIGHT_CANVAS_HEAD + "</head>", 1),
            encoding="utf-8",
        )
    except (OSError, UnicodeError):
        return


def _shap_force_plot_card(kind: str, title: str, plot_path: str, *, cluster: bool = False) -> str:
    """Embed one trusted, locally-generated SHAP HTML force plot by temporary URL."""
    card_class = " ckb-shap-card--cluster" if cluster else ""
    _ensure_light_shap_canvas(plot_path)
    plot_url = "/gradio_api/file=" + quote(Path(plot_path).resolve().as_posix(), safe="/")
    return f"""
    <article class="ckb-shap-card{card_class}">
      <header class="ckb-shap-card__header">
        <p class="ckb-shap-card__kind" data-shap-kind="{kind}">{kind.title()}</p>
        <h4>{html.escape(title)}</h4>
      </header>
      <iframe
        class="ckb-shap-frame"
        title="{html.escape(title)} SHAP force plot"
        loading="lazy"
        sandbox="allow-scripts"
        src="{plot_url}"
      ></iframe>
    </article>
    """


def _shap_force_gallery(result: dict[str, Any]) -> str:
    """Create the one-cluster plus 13-outcome SHAP explanation gallery."""
    try:
        force_plots = result["force_plots"]
        cluster = result["cluster"]
        cluster_label = str(cluster.get("cluster_label") or cluster["provisional_cluster_label"])
        cards = [
            _shap_force_plot_card(
                "cluster",
                f"Frozen cluster explanation · {cluster_label}",
                force_plots["cluster"][cluster_label],
                cluster=True,
            )
        ]
        for outcome_code, outcome in result["outcomes"].items():
            cards.append(
                _shap_force_plot_card(
                    "outcome",
                    f"{outcome_code} · {outcome['outcome']}",
                    force_plots[outcome_code],
                )
            )
    except (KeyError, OSError, TypeError):
        return (
            '<div class="ckb-shap-placeholder">'
            "SHAP force plots could not be rendered for this request."
            "</div>"
        )

    return """
    <section class="ckb-shap-gallery" aria-live="polite">
      <header class="ckb-shap-gallery__header">
        <div class="ckb-section-kicker" data-shap-kicker="true">SHAP EXPLANATIONS</div>
        <h3 data-shap-title="true">14 force plots</h3>
        <p data-shap-description="true">One force plot explains the assigned cluster; the remaining 13 explain each outcome probability surrogate.</p>
      </header>
      <div class="ckb-shap-grid">
    """ + "".join(cards) + "</div></section>"


def _locale_attrs(en: str, zh: str) -> str:
    """Return safe text attributes used by the language switcher."""
    return (
        f'data-locale-en="{html.escape(en, quote=True)}" '
        f'data-locale-zh="{html.escape(zh, quote=True)}"'
    )


def _outcome_presentation(code: str, outcome: dict[str, Any]) -> dict[str, Any]:
    """Get display-only reference data without influencing inference."""
    fallback_name = str(outcome.get("outcome", code))
    return OUTCOME_PRESENTATION.get(
        code,
        {
            "en": fallback_name,
            "zh": fallback_name,
            "model_en": "Model",
            "model_zh": "模型",
            "low_5": 0.0,
            "low_10": 0.0,
            "high_5": 0.0,
            "high_10": 0.0,
        },
    )


def _force_plot_frame(title_en: str, title_zh: str, plot_path: str) -> str:
    """Embed one trusted locally-generated SHAP force plot."""
    _ensure_light_shap_canvas(plot_path)
    plot_url = "/gradio_api/file=" + quote(Path(plot_path).resolve().as_posix(), safe="/")
    aria_en = title_en + " SHAP force plot"
    aria_zh = title_zh + " SHAP 力图"
    return f"""
      <iframe class="ckb-image-frame" title="{html.escape(aria_en, quote=True)}"
        data-aria-en="{html.escape(aria_en, quote=True)}"
        data-aria-zh="{html.escape(aria_zh, quote=True)}"
        loading="lazy" sandbox="allow-scripts" src="{plot_url}"></iframe>
    """


def _supplementary_image_url(path: Path) -> str:
    """Return a temporary Gradio file URL for a bundled static figure."""
    return "/gradio_api/file=" + quote(path.resolve().as_posix(), safe="/")


def _risk_reference_figure(
    code: str,
    presentation: dict[str, Any],
    *,
    is_high_risk: bool,
) -> str:
    """Show the supplied low/high cumulative-risk figure for this outcome."""
    risk_key = "high" if is_high_risk else "low"
    risk_en, risk_zh = ("High risk", "高风险") if is_high_risk else ("Low risk", "低风险")
    figure_path = SUPPLEMENTARY_IMAGE_DIR / f"{code}_{risk_key}.png"
    if not figure_path.is_file():
        return _cumulative_risk_svg(code, presentation)
    display_code = code.replace("_", "–")
    alt_en = f"{display_code} cumulative risk curve with the {risk_en.lower()} trajectory emphasised"
    alt_zh = f"{display_code} 累积风险曲线，突出显示{risk_zh}轨迹"
    return f"""
    <img class="ckb-reference-figure" src="{_supplementary_image_url(figure_path)}"
      loading="lazy" alt="{html.escape(alt_en, quote=True)}"
      data-aria-en="{html.escape(alt_en, quote=True)}"
      data-aria-zh="{html.escape(alt_zh, quote=True)}" />
    """


def _cluster_profile_figure(label: str) -> str:
    """Show the supplied C1/C2/C3 cluster-profile illustration."""
    figure_path = SUPPLEMENTARY_IMAGE_DIR / f"{label}.png"
    title_en, title_zh = f"Cluster {label} risk profile map", f"聚类 {label} 风险概览图"
    if not figure_path.is_file():
        return '<div class="ckb-image-placeholder">Cluster profile illustration is unavailable.</div>'
    return f"""
    <img class="ckb-cluster-profile-figure" src="{_supplementary_image_url(figure_path)}"
      loading="lazy" alt="{html.escape(title_en, quote=True)}"
      data-aria-en="{html.escape(title_en, quote=True)}"
      data-aria-zh="{html.escape(title_zh, quote=True)}" />
    """


def _cumulative_risk_svg(code: str, presentation: dict[str, Any]) -> str:
    """Create a compact native risk curve from the supplied reference values."""
    low_5, low_10 = float(presentation["low_5"]), float(presentation["low_10"])
    high_5, high_10 = float(presentation["high_5"]), float(presentation["high_10"])
    chart_max = max(low_5, low_10, high_5, high_10, 1.0) * 1.18

    def y(value: float) -> float:
        return 137 - (value / chart_max * 90)

    low_y5, low_y10, high_y5, high_y10 = y(low_5), y(low_10), y(high_5), y(high_10)
    label_en = f"{code.replace('_', '–')} cumulative-risk reference curves"
    label_zh = f"{code.replace('_', '–')} 累积风险参考曲线"
    return f"""
    <svg class="ckb-risk-curve" viewBox="0 0 350 178" role="img"
      aria-label="{html.escape(label_en, quote=True)}"
      data-aria-en="{html.escape(label_en, quote=True)}"
      data-aria-zh="{html.escape(label_zh, quote=True)}">
      <g class="ckb-risk-curve__grid" aria-hidden="true"><path d="M40 40H320M40 89H320M40 137H320M40 22V137H320" /></g>
      <g class="ckb-risk-curve__legend" aria-hidden="true">
        <line x1="43" y1="12" x2="65" y2="12" class="ckb-risk-curve__low" />
        <text x="71" y="16" {_locale_attrs('Low-risk reference', '低风险参考')}>Low-risk reference</text>
        <line x1="191" y1="12" x2="213" y2="12" class="ckb-risk-curve__high" />
        <text x="219" y="16" {_locale_attrs('High-risk reference', '高风险参考')}>High-risk reference</text>
      </g>
      <polyline points="40,137 155,{low_y5:.1f} 280,{low_y10:.1f}" class="ckb-risk-curve__low" />
      <polyline points="40,137 155,{high_y5:.1f} 280,{high_y10:.1f}" class="ckb-risk-curve__high" />
      <g class="ckb-risk-curve__point ckb-risk-curve__point--low"><circle cx="155" cy="{low_y5:.1f}" r="4.5" /><circle cx="280" cy="{low_y10:.1f}" r="4.5" /><text x="155" y="{low_y5 - 10:.1f}" text-anchor="middle">{low_5:.1f}%</text><text x="280" y="{low_y10 - 10:.1f}" text-anchor="middle">{low_10:.1f}%</text></g>
      <g class="ckb-risk-curve__point ckb-risk-curve__point--high"><circle cx="155" cy="{high_y5:.1f}" r="4.5" /><circle cx="280" cy="{high_y10:.1f}" r="4.5" /><text x="155" y="{high_y5 - 10:.1f}" text-anchor="middle">{high_5:.1f}%</text><text x="280" y="{high_y10 - 10:.1f}" text-anchor="middle">{high_10:.1f}%</text></g>
      <text x="40" y="163" class="ckb-risk-curve__axis" {_locale_attrs('0 years', '0年')}>0 years</text><text x="140" y="163" class="ckb-risk-curve__axis" {_locale_attrs('5 years', '5年')}>5 years</text><text x="260" y="163" class="ckb-risk-curve__axis" {_locale_attrs('10 years', '10年')}>10 years</text>
    </svg>
    """


def _outcome_image_card(code: str, outcome: dict[str, Any], plot_path: str) -> str:
    """Render a compact outcome card with context above its SHAP force plot."""
    presentation = _outcome_presentation(code, outcome)
    probability = max(0.0, min(1.0, float(outcome["probability"])))
    threshold = max(0.0, min(1.0, float(outcome["youden_threshold"])))
    is_high_risk = probability >= threshold
    risk_en, risk_zh = ("High risk", "\u9ad8\u98ce\u9669") if is_high_risk else ("Low risk", "\u4f4e\u98ce\u9669")
    decision_en = "at or above" if is_high_risk else "below"
    decision_zh = "\u8fbe\u5230\u6216\u9ad8\u4e8e" if is_high_risk else "\u4f4e\u4e8e"
    explanation_en = (
        f"Predicted probability is {probability * 100:.1f}%, "
        f"{decision_en} the frozen threshold of {threshold * 100:.1f}%. Reference cumulative incidence: "
        f"low-risk {presentation['low_5']:.1f}% at 5 years and {presentation['low_10']:.1f}% at 10 years; "
        f"high-risk {presentation['high_5']:.1f}% and {presentation['high_10']:.1f}%."
    )
    explanation_zh = (
        f"\u9884\u6d4b\u6982\u7387\u4e3a {probability * 100:.1f}%\uff0c{decision_zh}\u51bb\u7ed3\u9608\u503c "
        f"{threshold * 100:.1f}%\u3002\u53c2\u8003\u7d2f\u79ef\u53d1\u751f\u7387\uff1a\u4f4e\u98ce\u9669\u7ec4 5 \u5e74 {presentation['low_5']:.1f}%\u300110 \u5e74 "
        f"{presentation['low_10']:.1f}%\uff1b\u9ad8\u98ce\u9669\u7ec4\u5206\u522b\u4e3a {presentation['high_5']:.1f}% \u548c {presentation['high_10']:.1f}%\u3002"
    )
    display_code = code.replace("_", "\u2013")
    title_en, title_zh = str(presentation["en"]), str(presentation["zh"])
    return f"""
    <article class="ckb-image-card ckb-image-card--outcome">
      <header class="ckb-image-card__header"><div><p class="ckb-image-card__kind" {_locale_attrs('Outcome risk panel', '\u7ed3\u5c40\u98ce\u9669\u9762\u677f')}>Outcome risk panel</p><h4>{html.escape(display_code)} · <span {_locale_attrs(title_en, title_zh)}>{html.escape(title_en)}</span></h4></div><span class="ckb-image-card__badge {'ckb-image-card__badge--high' if is_high_risk else ''}" {_locale_attrs(risk_en, risk_zh)}>{risk_en}</span></header>
      <div class="ckb-image-card__context"><div class="ckb-image-card__curve">{_risk_reference_figure(code, presentation, is_high_risk=is_high_risk)}</div><div class="ckb-image-card__explanation"><p class="ckb-image-card__risk" {_locale_attrs(risk_en, risk_zh)}>{risk_en}</p><p {_locale_attrs(explanation_en, explanation_zh)}>{html.escape(explanation_en)}</p></div></div>
      <div class="ckb-image-card__force">{_force_plot_frame(display_code + ' ' + title_en, display_code + ' ' + title_zh, plot_path)}</div>
    </article>
    """


def _cluster_image_card(label: str, plot_path: str) -> str:
    """Render only the assigned cluster profile and its matching SHAP force plot."""
    title_en, title_zh = f"Cluster {label}", f"\u805a\u7c7b {label}"
    state_en, state_zh = "Assigned cluster", "\u672c\u6b21\u5206\u914d"
    return f"""
    <article class="ckb-image-card ckb-image-card--cluster ckb-image-card--selected">
      <header class="ckb-image-card__header"><div><p class="ckb-image-card__kind" {_locale_attrs('Cluster attribution', '\u805a\u7c7b\u5f52\u56e0')}>Cluster attribution</p><h4 {_locale_attrs(title_en, title_zh)}>{title_en}</h4></div><span class="ckb-image-card__badge" {_locale_attrs(state_en, state_zh)}>{state_en}</span></header>
      {_cluster_profile_figure(label)}
      <div class="ckb-image-card__force">{_force_plot_frame(title_en, title_zh, plot_path)}</div>
    </article>
    """


def _image_results_gallery(result: dict[str, Any]) -> str:
    """Create the assigned-cluster and 13-outcome image-result panels."""
    try:
        force_plots = result["force_plots"]
        cluster = result["cluster"]
        selected_label = str(cluster.get("cluster_label") or cluster["provisional_cluster_label"])
        cluster_cards = [_cluster_image_card(selected_label, force_plots["cluster"][selected_label])]
        outcome_cards = [
            _outcome_image_card(code, outcome, force_plots[code])
            for code, outcome in result["outcomes"].items()
        ]
    except (KeyError, OSError, TypeError):
        return '<div class="ckb-image-placeholder" data-locale-en="Image results could not be rendered for this request." data-locale-zh="本次请求无法生成图片结果。">Image results could not be rendered for this request.</div>'

    return """
    <section class="ckb-image-gallery" aria-live="polite">
      <header class="ckb-image-gallery__header"><div class="ckb-section-kicker" data-image-kicker="true">IMAGE RESULTS</div><h3 data-image-title="true">Assigned cluster explanation and 13 outcome panels</h3><p data-image-description="true">Each outcome panel places its cumulative-risk reference and brief interpretation above the related SHAP force plot.</p></header>
      <section class="ckb-image-section" aria-labelledby="cluster-image-title"><div class="ckb-image-section__header"><h4 id="cluster-image-title" data-image-cluster-title="true">Assigned cluster explanation</h4></div><div class="ckb-image-grid ckb-image-grid--clusters">
    """ + "".join(cluster_cards) + """
      </div></section>
      <section class="ckb-image-section" aria-labelledby="outcome-image-title"><div class="ckb-image-section__header"><h4 id="outcome-image-title" data-image-outcome-title="true">Outcome risk explanations</h4></div><div class="ckb-image-grid ckb-image-grid--outcomes">
    """ + "".join(outcome_cards) + "</div></section></section>"


def run_prediction(
    features: dict[str, float],
    sample_id: str | None = None,
    *,
    include_force_plots: bool = False,
) -> dict[str, Any]:
    """Run one prediction; browser-only SHAP files are temporary and auto-expire."""
    predictor = get_predictor()
    with _inference_lock:
        if include_force_plots:
            SHAP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _clean_expired_shap_reports()
            output_dir = SHAP_CACHE_DIR / uuid.uuid4().hex
            try:
                result = predictor.predict_one(
                    features,
                    output_dir=output_dir,
                    make_force_plots=True,
                    sample_id=sample_id,
                )
                result["_shap_force_gallery_html"] = _image_results_gallery(result)
            except Exception:
                shutil.rmtree(output_dir, ignore_errors=True)
                raise
        else:
            with tempfile.TemporaryDirectory(prefix="ckb_prediction_") as output_dir:
                result = predictor.predict_one(
                    features,
                    output_dir=output_dir,
                    make_force_plots=False,
                    sample_id=sample_id,
                )

    # The predictor writes an audit JSON to its output directory. The API is
    # intentionally stateless, so that temporary file is removed and its now
    # invalid local path is not returned to callers.
    result.pop("result_json", None)
    result.pop("force_plots", None)
    return result


def warm_up_model() -> str:
    """Load prediction-time artifacts after a visitor opens the demo."""
    try:
        predictor = get_predictor()
        with _inference_lock:
            predictor._ensure_cluster_shap()
            for outcome in predictor.outcome_meta:
                predictor._load_outcome_bundle(outcome)
        return (
            '<div class="ckb-status ckb-status--ready" role="status">'
            '<span class="ckb-status__dot" aria-hidden="true"></span>'
            '<span><strong>模型已就绪。</strong>预测可立即开始；提交数据不会被此 Space 持久保存。</span>'
            "</div>"
        )
    except Exception:
        return (
            '<div class="ckb-status ckb-status--warning" role="status">'
            '<span class="ckb-status__dot" aria-hidden="true"></span>'
            '<span><strong>预热尚未完成。</strong>仍可提交预测，系统会在请求时自动重试加载。</span>'
            "</div>"
        )


def predict_json_api(request: dict[str, Any]) -> dict[str, Any]:
    """Single-object API used by external Python, JavaScript, or curl clients."""
    if not isinstance(request, dict):
        raise gr.Error("Request must be a JSON object.")

    features = request.get("features", request)
    if not isinstance(features, dict):
        raise gr.Error("The 'features' field must be a JSON object.")

    missing = [feature for feature in FEATURES if feature not in features]
    if missing:
        raise gr.Error(f"Missing required input variables: {missing}")

    sample_id = request.get("sample_id")
    if sample_id is not None:
        sample_id = str(sample_id)
        if len(sample_id) > 200:
            raise gr.Error("sample_id must be no longer than 200 characters.")

    return run_prediction(
        {feature: features[feature] for feature in FEATURES},
        sample_id=sample_id,
    )


def _outcome_table(result: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for code, outcome in result["outcomes"].items():
        is_high_risk = outcome["risk_class"] == "high_risk"
        rows.append(
            {
                "代码": code,
                "预测结局": outcome["outcome"],
                "概率": f"{outcome['probability'] * 100:.1f}%",
                "冻结阈值": f"{outcome['youden_threshold'] * 100:.1f}%",
                "风险判定": "At or above threshold" if is_high_risk else "Below threshold",
            }
        )
    return pd.DataFrame(rows).set_axis(TABLE_COLUMNS_EN, axis="columns")


def _outcome_table_html(result: dict[str, Any]) -> str:
    """Render the outcome table as fully bilingual native HTML."""
    rows: list[str] = []
    for code, outcome in result["outcomes"].items():
        presentation = _outcome_presentation(code, outcome)
        probability = max(0.0, min(1.0, float(outcome["probability"])))
        threshold = max(0.0, min(1.0, float(outcome["youden_threshold"])))
        is_high_risk = probability >= threshold
        risk_en, risk_zh = ("At or above threshold", "达到或高于阈值") if is_high_risk else ("Below threshold", "低于阈值")
        rows.append(
            f"""
            <tr>
              <td class="ckb-outcome-table__code">{html.escape(code.replace('_', '–'))}</td>
              <td><span {_locale_attrs(str(presentation['en']), str(presentation['zh']))}>{html.escape(str(presentation['en']))}</span></td>
              <td>{probability * 100:.1f}%</td>
              <td>{threshold * 100:.1f}%</td>
              <td><span class="ckb-outcome-table__decision{' ckb-outcome-table__decision--high' if is_high_risk else ''}" {_locale_attrs(risk_en, risk_zh)}>{risk_en}</span></td>
            </tr>
            """
        )
    return """
    <section class="ckb-outcome-table" aria-live="polite">
      <div class="ckb-outcome-table__header"><div><p class="ckb-section-kicker" data-outcome-table-kicker="true" data-locale-en="OUTCOME PREDICTIONS" data-locale-zh="结局预测">OUTCOME PREDICTIONS</p><h3 data-outcome-table-title="true" data-locale-en="Outcome prediction details" data-locale-zh="结局预测明细">Outcome prediction details</h3></div><p data-outcome-table-description="true" data-locale-en="Risk class is determined by the frozen threshold for each outcome." data-locale-zh="风险判定根据每项结局的冻结阈值确定。">Risk class is determined by the frozen threshold for each outcome.</p></div>
      <div class="ckb-outcome-table__scroll"><table><thead><tr>
        <th data-locale-en="Code" data-locale-zh="代码">Code</th><th data-locale-en="Outcome" data-locale-zh="结局">Outcome</th><th data-locale-en="Probability" data-locale-zh="概率">Probability</th><th data-locale-en="Frozen threshold" data-locale-zh="冻结阈值">Frozen threshold</th><th data-locale-en="Risk decision" data-locale-zh="风险判定">Risk decision</th>
      </tr></thead><tbody>
    """ + "".join(rows) + "</tbody></table></div></section>"


def _cluster_card(cluster: dict[str, Any]) -> str:
    label = str(cluster.get("cluster_label") or cluster["provisional_cluster_label"])
    assigned = cluster["classification_status"] == "assigned"
    badge_class = "" if assigned else " ckb-result-badge--review"
    badge_text = "已完成分配" if assigned else "建议复核"
    return f"""
    <section class="ckb-result-card" aria-live="polite">
      <div class="ckb-result-card__header">
        <div>
          <div class="ckb-result-kicker">Cluster assignment</div>
          <h3>风险聚类：{html.escape(label)}</h3>
        </div>
        <span class="ckb-result-badge{badge_class}">{badge_text}</span>
      </div>
      <dl class="ckb-result-metrics">
        <div><dt>最近中心距离</dt><dd>{cluster['distance_nearest']:.4f}</dd></div>
        <div><dt>与次近中心的间隔</dt><dd>{cluster['margin']:.4f}</dd></div>
      </dl>
    </section>
    """


def _risk_visual(result: dict[str, Any]) -> str:
    """Render a responsive, accessible probability chart without extra dependencies."""
    rows = sorted(
        result["outcomes"].items(),
        key=lambda item: float(item[1]["probability"]),
        reverse=True,
    )
    bars: list[str] = []
    for code, outcome in rows:
        probability = max(0.0, min(1.0, float(outcome["probability"])))
        threshold = max(0.0, min(1.0, float(outcome["youden_threshold"])))
        is_high_risk = outcome["risk_class"] == "high_risk"
        row_class = " ckb-risk-row--high" if is_high_risk else ""
        accessible_label = (
            f"{code}: {outcome['outcome']}, probability {probability * 100:.1f}%, "
            f"threshold {threshold * 100:.1f}%"
        )
        bars.append(
            f'<div class="ckb-risk-row{row_class}" aria-label="{html.escape(accessible_label)}">'
            f'<span class="ckb-risk-label" title="{html.escape(str(outcome["outcome"]))}">{html.escape(code)}</span>'
            f'<span class="ckb-risk-track" aria-hidden="true">'
            f'<span class="ckb-risk-fill" style="--risk-width: {probability * 100:.2f}%"></span>'
            f'<span class="ckb-risk-threshold" style="--threshold: {threshold * 100:.2f}%"></span>'
            "</span>"
            f'<span class="ckb-risk-value">{probability * 100:.1f}%</span>'
            "</div>"
        )
    return """
    <section class="ckb-risk-visual" aria-labelledby="risk-visual-title">
      <div class="ckb-risk-visual__header">
        <div>
          <h3 id="risk-visual-title">13 项结局的预测概率</h3>
          <p>横线标记各结局冻结的 Youden 阈值；此图用于研究结果阅读，并非临床诊断。</p>
        </div>
        <div class="ckb-legend" aria-label="图例">
          <span><i aria-hidden="true"></i>低于阈值</span>
          <span><i class="ckb-legend--high" aria-hidden="true"></i>达到或高于阈值</span>
        </div>
      </div>
    """ + "".join(bars) + "</section>"


def predict_for_demo(
    *values: float | int | None,
) -> tuple[str, str, str, dict[str, Any], str]:
    missing = [
        FEATURE_LABELS[feature]
        for feature, value in zip(FEATURES, values, strict=True)
        if value is None
    ]
    if missing:
        raise gr.Error(f"请补全以下变量后再预测：{', '.join(missing)}")

    features = {
        feature: float(value)
        for feature, value in zip(FEATURES, values, strict=True)
        if value is not None
    }
    result = run_prediction(
        features,
        sample_id="web_demo",
        include_force_plots=True,
    )
    shap_gallery = result.pop(
        "_shap_force_gallery_html",
        '<div class="ckb-image-placeholder" data-locale-en="Image results are unavailable for this request." data-locale-zh="本次请求暂无图片结果。">Image results are unavailable for this request.</div>',
    )
    return (
        _cluster_card(result["cluster"]),
        _outcome_table_html(result),
        _risk_visual(result),
        result,
        shap_gallery,
    )


def restore_example_values() -> list[float]:
    """Restore the prefilled synthetic demonstration values without model work."""
    return [EXAMPLE_VALUES[feature] for feature in FEATURES]


with gr.Blocks(
    title="CKB 17-variable Risk Predictor",
    fill_width=True,
) as demo:
    with gr.Column(elem_id="ckb-shell"):
        gr.HTML(
            """
            <a class="ckb-skip" href="#risk-inputs">跳转到预测输入</a>
            <section class="ckb-hero" aria-labelledby="ckb-title">
              <div class="ckb-hero__content">
                <div class="ckb-eyebrow">
                  <span class="ckb-mark" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                      <path d="M7 4c5 3 5 13 10 16M17 4C12 7 12 17 7 20M9 6h6M8 12h8M9 18h6"/>
                    </svg>
                  </span>
                  CKB research interface
                </div>
                <h1 id="ckb-title">17 变量风险预测</h1>
                <p>一次完整输入，返回冻结 K=3 聚类分配与 13 项结局风险概率。表单与 API 共用同一套模型推理逻辑。</p>
                <div class="ckb-hero__meta" aria-label="产品特点">
                  <span class="ckb-chip"><svg viewBox="0 0 24 24"><path d="M12 3v18M3 12h18"/></svg>17 个输入变量</span>
                  <span class="ckb-chip"><svg viewBox="0 0 24 24"><path d="M4 19V5m0 14h16M8 15l3-4 3 2 5-7"/></svg>13 项概率结果</span>
                  <span class="ckb-chip"><svg viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>无持久化保存</span>
                </div>
              </div>
            </section>
            """
        )
        gr.HTML(
            """
            <section class="ckb-trust-row" aria-label="模型概览">
              <article class="ckb-trust-card"><strong>17</strong><span>完整输入变量</span></article>
              <article class="ckb-trust-card"><strong>K = 3</strong><span>冻结最近中心聚类</span></article>
              <article class="ckb-trust-card"><strong>13</strong><span>结局风险概率</span></article>
            </section>
            """
        )
        warm_status = gr.HTML(
            '<div class="ckb-status" role="status">'
            '<span class="ckb-status__dot" aria-hidden="true"></span>'
            '<span><strong>正在后台预热模型。</strong>你可以先填写表单；模型完成加载后即可提交。</span>'
            "</div>",
            elem_id="warm-status",
        )

        with gr.Column(elem_id="risk-inputs", elem_classes="ckb-panel"):
            gr.HTML(
                """
                <header class="ckb-section-heading">
                  <div>
                    <div class="ckb-section-kicker">Input workspace</div>
                    <h2>填写预测变量</h2>
                    <p>所有 17 项均为必填。分类变量必须与训练数据使用相同编码；本服务不会重新编码、插补或保存输入。</p>
                  </div>
                  <aside class="ckb-coding-note">研究用途提示：请在解释结果前核对分类编码与量纲。</aside>
                </header>
                """
            )
            input_by_feature: dict[str, Any] = {}
            with gr.Row(elem_classes="ckb-input-grid"):
                for index, title, subtitle, group_features in FEATURE_GROUPS:
                    with gr.Column(min_width=250):
                        with gr.Group(elem_classes="ckb-form-card"):
                            gr.HTML(
                                f"""
                                <div class="form-card__top">
                                  <span class="form-card__index">{index}</span>
                                  <div><h3>{title}</h3><p>{subtitle}</p></div>
                                </div>
                                """
                            )
                            for feature in group_features:
                                component_kwargs = {
                                    "label": DEFAULT_EN_FEATURE_LABELS[feature],
                                    "value": EXAMPLE_VALUES[feature],
                                    "elem_id": f"field-{feature}",
                                }
                                if feature in CATEGORICAL_CHOICES:
                                    input_by_feature[feature] = gr.Dropdown(
                                        choices=CATEGORICAL_CHOICES[feature],
                                        filterable=False,
                                        **component_kwargs,
                                    )
                                else:
                                    input_by_feature[feature] = gr.Number(
                                        precision=0 if feature in INTEGER_FEATURES else None,
                                        **component_kwargs,
                                    )

            # Components are displayed in user-friendly groups, while the
            # predictor always receives its frozen feature order.
            inputs = [input_by_feature[feature] for feature in FEATURES]

            with gr.Row(elem_classes="ckb-actions"):
                submit = gr.Button("运行风险预测", variant="primary", elem_id="predict-button")
                reset = gr.Button("恢复演示数据", variant="secondary", elem_id="reset-button")
                gr.HTML(
                    """
                    <p class="ckb-privacy-copy">
                      <svg viewBox="0 0 24 24" fill="none"><rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>
                      推理结束后会清除临时文件；请勿将本工具用作诊断或治疗决策。
                    </p>
                    """
                )

        with gr.Column(elem_classes="ckb-results"):
            gr.HTML(
                """
                <header class="ckb-results-header">
                  <div class="ckb-section-kicker">Prediction output</div>
                  <h2>结果与概率分布</h2>
                </header>
                """
            )
            cluster_output = gr.HTML(
                '<div class="ckb-result-placeholder">提交一组完整变量后，此处将显示聚类分配与距离信息。</div>',
                elem_id="cluster-result",
            )
            risk_visual = gr.HTML(
                '<div class="ckb-result-placeholder">概率分布图将在预测完成后出现。</div>',
                elem_id="risk-visual",
            )
            outcome_output = gr.HTML(
                '<div class="ckb-image-placeholder" data-locale-en="Run a prediction to generate outcome details." data-locale-zh="运行预测后生成结局明细。">Run a prediction to generate outcome details.</div>',
                elem_id="outcome-table",
            )
            with gr.Accordion("Show image results (16)", open=False, elem_id="shap-result"):
                shap_output = gr.HTML(
                    '<div class="ckb-image-placeholder" data-locale-en="Run a prediction to generate image results." data-locale-zh="运行预测后生成图片结果。">Run a prediction to generate image results.</div>',
                    elem_id="shap-gallery",
                )
            with gr.Accordion("查看完整 JSON 响应", open=False, elem_id="raw-result"):
                raw_output = gr.JSON(label="完整响应")
            gr.HTML(
                '<p class="ckb-footer-note">面向程序化使用：稳定 JSON 接口为 <code>/predict</code>；预热状态接口为 <code>/warmup</code>。可从 Space 的 “Use via API” 获取调用示例。</p>'
            )

        submit.click(
            fn=predict_for_demo,
            inputs=inputs,
            outputs=[cluster_output, outcome_output, risk_visual, raw_output, shap_output],
            api_name="demo_predict",
            show_progress="full",
        )
        reset.click(fn=restore_example_values, outputs=inputs, api_name=False)

        # A compact API-only endpoint. Keeping one JSON input makes it convenient
        # for external Python, JavaScript, and curl clients to call the Space.
        api_request = gr.JSON(label="request", visible=False)
        api_response = gr.JSON(label="response", visible=False)
        api_trigger = gr.Button(visible=False)
        api_trigger.click(
            fn=predict_json_api,
            inputs=api_request,
            outputs=api_response,
            api_name="predict",
        )
        demo.load(
            fn=warm_up_model,
            outputs=warm_status,
            api_name="warmup",
            show_progress="hidden",
        )

demo.queue(default_concurrency_limit=1, max_size=16)

if __name__ == "__main__":
    SHAP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    demo.launch(
        css=CUSTOM_CSS,
        head=HEAD,
        allowed_paths=[str(SHAP_CACHE_DIR), str(SUPPLEMENTARY_IMAGE_DIR)],
    )
