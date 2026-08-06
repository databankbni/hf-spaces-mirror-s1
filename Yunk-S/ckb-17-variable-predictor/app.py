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
SHAP_CACHE_TTL_SECONDS = 60 * 60

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
    "sex": [("Male / \u7537", 0), ("Female / \u5973", 1)],
    "edu_level": [("Low / \u4f4e", 1), ("Intermediate / \u4e2d", 2), ("High / \u9ad8", 3)],
    "marital_status": [
        ("Other observed status / \u5176\u4ed6\u89c2\u5bdf\u72b6\u6001", 0),
        ("Married or partnered / \u5df2\u5a5a\u6216\u6709\u4f34\u4fa3", 1),
    ],
    "work": [("No / \u5426", 0), ("Yes / \u662f", 1)],
    "retire": [("No / \u5426", 0), ("Yes / \u662f", 1)],
    "smoking": [("No / \u5426", 0), ("Yes / \u662f", 1)],
    "alcohol": [("No / \u5426", 0), ("Yes / \u662f", 1)],
    "bp_drugs": [("No / \u5426", 0), ("Yes / \u662f", 1)],
    "self_health": [
        ("Very good or excellent / \u5f88\u597d\u6216\u4f18\u79c0", 1),
        ("Good / \u597d", 2),
        ("Fair or regular / \u4e00\u822c", 3),
        ("Poor or very poor / \u5dee\u6216\u5f88\u5dee", 4),
    ],
    "chronic_pain": [("No / \u5426", 0), ("Yes / \u662f", 1)],
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

DEFAULT_EN_FEATURE_HELP = {
    "sex": "Choose the description that matches the study definition.",
    "age": "Enter completed years.",
    "edu_level": "Choose the description that matches the study definition.",
    "marital_status": "Choose the description that matches the study definition.",
    "work": "Choose the description that matches the study definition.",
    "retire": "Choose the description that matches the study definition.",
    "hh_size": "Number of people in the household.",
    "smoking": "Choose the description that matches the study definition.",
    "alcohol": "Choose the description that matches the study definition.",
    "height_cm": "Continuous value in centimetres.",
    "weight_kg": "Continuous value in kilograms.",
    "waist_cm": "Continuous value in centimetres.",
    "sbp_mmhg": "Continuous value in mmHg.",
    "dbp_mmhg": "Continuous value in mmHg.",
    "bp_drugs": "Choose the description that matches the study definition.",
    "self_health": "Choose the description that matches the study definition.",
    "chronic_pain": "Choose the description that matches the study definition.",
}

TABLE_COLUMNS_EN = ["Code", "Outcome", "Probability", "Frozen threshold", "Risk decision"]


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
}

.gradio-container {
  background:
    radial-gradient(circle at 10% 0%, rgb(207 250 254 / 0.75), transparent 24rem),
    radial-gradient(circle at 90% 9%, rgb(224 242 254 / 0.95), transparent 25rem),
    var(--ckb-blue-50);
  color: var(--ckb-slate-950);
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
  justify-content: flex-end;
  margin: -4px 0 14px;
}

.ckb-language-switch {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--ckb-blue-100);
  border-radius: 999px;
  background: rgb(255 255 255 / 0.88);
  box-shadow: var(--ckb-shadow-sm);
}

.ckb-language-switch button {
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

.ckb-language-switch button:hover { background: var(--ckb-blue-50); color: var(--ckb-blue-900); }
.ckb-language-switch button:active { transform: scale(0.98); }
.ckb-language-switch button[aria-pressed="true"] { background: var(--ckb-blue-900); color: var(--ckb-white); }
.ckb-language-switch button:focus-visible { outline: 3px solid rgb(2 132 199 / 0.32); outline-offset: 2px; }

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

.ckb-hero, .ckb-trust-card, .ckb-panel, .ckb-results { will-change: transform, opacity; }

@media (max-width: 820px) {
  #ckb-shell { padding: 14px 12px 36px; }
  .ckb-hero { min-height: 0; border-radius: var(--ckb-radius-lg); }
  .ckb-trust-row { grid-template-columns: 1fr; }
  .ckb-section-heading { display: block; }
  .ckb-coding-note { max-width: none; margin-top: 14px; }
  .ckb-risk-row { grid-template-columns: 104px minmax(90px, 1fr) 48px; gap: 8px; }
  .ckb-shap-grid { grid-template-columns: 1fr; }
  .ckb-shap-card--cluster { grid-column: auto; }
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
          .from(results, { y: 12, autoAlpha: 0 }, '-=0.24');
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

  const setText = (node, value) => {
    if (node && node.textContent !== value) node.textContent = value;
  };
  const setHtml = (node, value) => {
    if (node && node.innerHTML !== value) node.innerHTML = value;
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

    const bar = document.createElement('div');
    bar.className = 'ckb-language-bar';
    bar.innerHTML = '<div class="ckb-language-switch" role="group" aria-label="Language selector"><button type="button" data-language="en">English</button><button type="button" data-language="zh">\u4e2d\u6587</button></div>';
    trustRow.insertAdjacentElement('afterend', bar);

    const applyLanguage = () => {
      const text = copy[language];
      root.dataset.language = language;
      root.querySelectorAll('[data-language]').forEach((button) => {
        button.setAttribute('aria-pressed', String(button.dataset.language === language));
      });
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
        setText(component.querySelector('.info-text'), fields[language].help[field]);
        component.querySelector('input')?.setAttribute('aria-label', fields[language].labels[field]);
      });
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
      const jsonButton = root.querySelector('#raw-result > button');
      if (jsonButton) setText(jsonButton, text.json);
      setHtml(root.querySelector('.ckb-footer-note'), text.footer);
    };

    bar.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-language]');
      if (!button) return;
      language = button.dataset.language === 'zh' ? 'zh' : 'en';
      try { localStorage.setItem('ckb-language', language); } catch (_) { /* Preference remains for this page. */ }
      applyLanguage();
    });
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


def _shap_force_plot_card(kind: str, title: str, plot_path: str, *, cluster: bool = False) -> str:
    """Embed one trusted, locally-generated SHAP HTML force plot by temporary URL."""
    card_class = " ckb-shap-card--cluster" if cluster else ""
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
                result["_shap_force_gallery_html"] = _shap_force_gallery(result)
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
) -> tuple[str, pd.DataFrame, str, dict[str, Any], str]:
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
        '<div class="ckb-shap-placeholder">SHAP force plots are unavailable for this request.</div>',
    )
    return (
        _cluster_card(result["cluster"]),
        _outcome_table(result),
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
                                    "info": DEFAULT_EN_FEATURE_HELP[feature],
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
            outcome_output = gr.Dataframe(
                headers=TABLE_COLUMNS_EN,
                value=pd.DataFrame(columns=TABLE_COLUMNS_EN),
                interactive=False,
                label="结局预测明细",
                elem_id="outcome-table",
            )
            with gr.Accordion("Show 14 SHAP force plots", open=False, elem_id="shap-result"):
                shap_output = gr.HTML(
                    '<div class="ckb-shap-placeholder">Run a prediction to generate 14 SHAP force plots.</div>',
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
        allowed_paths=[str(SHAP_CACHE_DIR)],
    )
