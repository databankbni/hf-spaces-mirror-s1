import json
import joblib
import numpy as np
import pandas as pd
import gradio as gr

from transformers import AutoTokenizer, AutoModel
import torch

# ============================================================
# UI 顯示設定（你主要改這裡）
# ============================================================

UI_LABELS = {
    # 欄位標題你想怎麼顯示就怎麼改（不影響後端）
    "sex": "sex",
    "CLINICSBY_cat": "Come to ER by",

    "age": "age",
    "consfullE0V0M0orE4V5M6": "Conscious clear?",
    "backER": "Back to ER for same reason in 24 hours?",
    "VISITINTHREEDAYS": "Ever been to ER in 3 days?",

    "BODYTEMPERATURE_num": "body temperature（°C）",
    "PULSE_num": "heart rate（per minute）",
    "RESPIRATION_num": "respiratory rate（per minute）",
    "SYSTOLIC_num": "systolic BP（mmHg）",
    "DIASTOLIC_num": "diastolic BP（mmHg）",
    "pain_any_1": "Any pain?",
    "PAININDEX_num0to10": "Pain score（painless = 0）",


    "missing_flags_title": "Missing flags (If a value has already been entered, the system will automatically set missing=0; if the value cannot be measured or is blank, it will automatically set missing=1）",
    "BT_missing": "Body temperature missing（0/1）",
    "pulse_missing": "heart rate missing（0/1）",
    "respiration_missing": "respiratory rate missing（0/1）",
    "systolic_missing": "systolic BP missing（0/1）",
    "diastolic_missing": "diastolic BP missing（0/1）",

    "cc_text": "Chief complaint（Enter your own text and explain the reason for seeking medical attention in a simple sentence. Both Chinese and English are acceptable）",
    "title": "# ED Disposition Prediction",
    "subtitle": "Enter triage data and chief complaint text to predict hospitalization probability and classification results",
    "predict_btn": "Predict Now",

    "out_proba": "P(Admission=1) Hospitalization probability",
    "out_label": "Predicted class",
    "out_msg": "Message: If probability of hospitalization exceeds a certain threshold, it is recommended to seek medical attention.",
}

UI_OUTPUT_TEXT = {
    "class_home": "Go home / Observation",
    "class_admission": "Suggest go to ER",
    "pred_label_fmt": "{label}",  # 你也可改成 "{label}（{code}）"
    "message_fmt": "Predict result：{pred_text} ｜ hospitalization probability = {proba:.4f} ｜ Threshold = {threshold:.2f}",
    # 若你想讓訊息更短：
    # "message_fmt": "{pred_text} | P(admit)={proba:.3f} | thr={threshold:.2f}",
}


# ✅ 0/1 下拉選單顯示文字（你可自由改）
# 後端仍會轉回 0/1
BINARY01_DISPLAY = {
    0: "No",
    1: "Yes",
}

# ✅ sex 顯示文字（你可自由改）
# 後端仍會轉回 "M" / "F"
SEX_CODE_TO_DISPLAY = {
    "M": "Male",
    "F": "Female",
}

# ✅ CLINICSBY 顯示文字（你可自由改）
# 後端仍會轉回 "61","63"... 這些原始 code
CLINICBY_CODE_TO_DESC = {
    "61": "by walk",
    "63": "wheelchair",
    "65": "ambulance",
    "6A": "in parent's arm",
    "68": "refer from other hospital",
    "62": "on bed",
    "69": "refer from outpatient clinics",
    "66": "private ambulance",
    "6B": "walk but need other's support",
    "6Z": "others",
}

# ✅ CLINICSBY 顯示格式（你可自由改）
# 例如你想顯示成： "自行步入（61）" 也可以在這邊改
CLINICBY_DISPLAY_FORMAT = "{desc}"  # 例如 61(自行步入)

# ============================================================
# Load artifacts
# ============================================================

pipe = joblib.load("model.joblib")
with open("metadata.json", "r", encoding="utf-8") as f:
    meta = json.load(f)

THRESHOLD = float(meta.get("threshold", 0.30))

DEPLOY_COLS_18 = meta["deploy_cols_18"]
BERT_COLS = meta["bert_cols"]

# 這些是你訓練時出現過的類別選項（後端 code）
SEX_OPTIONS_RAW = [str(x) for x in meta["categorical"]["sex"]]
CLINICBY_OPTIONS_RAW = [str(x) for x in meta["categorical"]["CLINICSBY_cat"]]

# ✅ 只保留你有定義顯示方式的 code（未定義的就不顯示在選單）
CLINICBY_OPTIONS_RAW = [c for c in CLINICBY_OPTIONS_RAW if c in CLINICBY_CODE_TO_DESC]

# 可選：若你想確認有哪些被排除
# dropped = [c for c in [str(x) for x in meta["categorical"]["CLINICSBY_cat"]] if c not in CLINICBY_CODE_TO_DESC]
# print("Dropped CLINICSBY codes:", dropped)


NUMERIC_INPUTS = set(meta["numeric_inputs"])
BINARY_INPUTS = set(meta["binary_inputs"])

# ============================================================
# Helpers: UI 顯示 ↔ 後端 code 轉換
# ============================================================

def build_display_and_map(code_options, code_to_display=None, code_to_desc=None, fmt="{code}({desc})"):
    """
    給一串後端 code（例如 ["61","63"]），產生：
      - display_choices: UI 下拉選單顯示的字串 list
      - display_to_code: 把顯示字串轉回 code 的 dict
    你可以選擇：
      - code_to_display: code -> 想顯示的文字（例如 sex）
      - code_to_desc + fmt: code -> desc + 格式化（例如 CLINICSBY）
    """
    display_choices = []
    display_to_code = {}

    for code in code_options:
        code = str(code)

        if code_to_display is not None:
            display = code_to_display.get(code, f"{code}（未命名）")
        else:
            desc = None
            if code_to_desc is not None:
                desc = code_to_desc.get(code, "你想呈現的選項文字")
            else:
                desc = "你想呈現的選項文字"
            display = fmt.format(code=code, desc=desc)

        # 避免顯示文字重複造成 mapping 覆蓋：若重複，後面自動加上 code
        if display in display_to_code and display_to_code[display] != code:
            display = f"{display} [{code}]"

        display_choices.append(display)
        display_to_code[display] = code

    return display_choices, display_to_code

def decode_dropdown_value(val, display_to_code, valid_codes=None):
    """
    Gradio 可能回傳：
      1) 顯示文字（我們設計的）
      2) 或直接回傳 code（某些版本/用法）
    這邊統一轉成後端 code
    """
    if val is None:
        return ""
    s = str(val)

    # 若本來就是 code
    if valid_codes is not None and s in valid_codes:
        return s

    # 若是顯示文字
    if s in display_to_code:
        return display_to_code[s]

    # 最後保底：直接回傳字串
    return s

def to_float_or_nan(x):
    if x is None:
        return np.nan
    if isinstance(x, str):
        x = x.strip()
        if x == "" or x.lower() in ["nil", "unknown"]:
            return np.nan
    try:
        return float(x)
    except Exception:
        return np.nan

def to_int01(x):
    # Accept 0/1, True/False, "0"/"1", 或顯示文字（例如 "是 / Yes (1)"）
    if x is None:
        return 0
    if isinstance(x, str):
        sx = x.strip()
        # 先嘗試從顯示文字找 0/1
        for k, v in BINARY01_DISPLAY.items():
            if sx == v:
                return int(k)
        x = sx
    try:
        v = int(float(x))
        return 1 if v != 0 else 0
    except Exception:
        return 0

def auto_fix_missing_flags(row):
    mapping = [
        ("BODYTEMPERATURE_num", "BT_missing"),
        ("PULSE_num", "pulse_missing"),
        ("RESPIRATION_num", "respiration_missing"),
        ("SYSTOLIC_num", "systolic_missing"),
        ("DIASTOLIC_num", "diastolic_missing"),
    ]
    for num_col, miss_col in mapping:
        if np.isnan(row[num_col]):
            row[miss_col] = 1
        else:
            row[miss_col] = 0
    return row

# ============================================================
# BERT (same method as your training embedding tool)
# ============================================================

BERT_MODEL_NAME = "bert-base-chinese"
BERT_MAX_LENGTH = 32

tokenizer = AutoTokenizer.from_pretrained(BERT_MODEL_NAME)
bert_model = AutoModel.from_pretrained(BERT_MODEL_NAME)
bert_model.eval()

@torch.no_grad()
def encode_text_to_768(text: str) -> np.ndarray:
    text = "" if text is None else str(text)
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding="max_length",
        max_length=BERT_MAX_LENGTH
    )
    outputs = bert_model(**inputs)
    cls = outputs.last_hidden_state[:, 0, :].squeeze(0).numpy()  # (768,)
    return cls

# ============================================================
# Build dropdown choices (display) + mappings
# ============================================================

# sex：後端 code -> 顯示文字
SEX_DISPLAY_CHOICES, SEX_DISPLAY_TO_CODE = build_display_and_map(
    code_options=SEX_OPTIONS_RAW,
    code_to_display=SEX_CODE_TO_DISPLAY
)

# clinicby：後端 code -> "61(自行步入)" 顯示
CLINICBY_DISPLAY_CHOICES, CLINICBY_DISPLAY_TO_CODE = build_display_and_map(
    code_options=CLINICBY_OPTIONS_RAW,
    code_to_desc=CLINICBY_CODE_TO_DESC,
    fmt=CLINICBY_DISPLAY_FORMAT
)

# 0/1 顯示選單
BINARY01_DISPLAY_CHOICES = [BINARY01_DISPLAY[0], BINARY01_DISPLAY[1]]

def default_display_for_code(code, code_to_display, fallback_first=None):
    code = str(code)
    if code_to_display is None:
        return fallback_first
    # code_to_display 是「display_to_code」的反向不好找，這裡直接從 mapping 反推
    for disp, c in code_to_display.items():
        if c == code:
            return disp
    return fallback_first

# ============================================================
# Predict
# ============================================================

def predict(
    sex, age, consfull, backER, visit3days, clinicby,
    bodytemp, pulse, resp, systolic, diastolic,
    bt_miss, pulse_miss, resp_miss, sys_miss, dia_miss,
    pain_any, pain_index,
    cc_text
):
    # UI -> 後端 code
    sex_code = decode_dropdown_value(sex, SEX_DISPLAY_TO_CODE, valid_codes=set(SEX_OPTIONS_RAW))
    clinicby_code = decode_dropdown_value(clinicby, CLINICBY_DISPLAY_TO_CODE, valid_codes=set(CLINICBY_OPTIONS_RAW))

    row = {
        "sex": str(sex_code) if sex_code is not None else "",
        "CLINICSBY_cat": str(clinicby_code) if clinicby_code is not None else "",
    }

    # numeric
    row["age"] = to_float_or_nan(age)
    row["BODYTEMPERATURE_num"] = to_float_or_nan(bodytemp)
    row["PULSE_num"] = to_float_or_nan(pulse)
    row["RESPIRATION_num"] = to_float_or_nan(resp)
    row["SYSTOLIC_num"] = to_float_or_nan(systolic)
    row["DIASTOLIC_num"] = to_float_or_nan(diastolic)
    row["PAININDEX_num0to10"] = to_float_or_nan(pain_index)

    # binary (允許顯示文字或 0/1)
    row["consfullE0V0M0orE4V5M6"] = to_int01(consfull)
    row["backER"] = to_int01(backER)
    row["VISITINTHREEDAYS"] = to_int01(visit3days)
    row["BT_missing"] = to_int01(bt_miss)
    row["pulse_missing"] = to_int01(pulse_miss)
    row["respiration_missing"] = to_int01(resp_miss)
    row["systolic_missing"] = to_int01(sys_miss)
    row["diastolic_missing"] = to_int01(dia_miss)
    row["pain_any_1"] = to_int01(pain_any)

    # auto-fix missing flags to avoid inconsistency
    row = auto_fix_missing_flags(row)

    # BERT
    emb = encode_text_to_768(cc_text)
    for i in range(768):
        row[f"bert_{i}"] = float(emb[i])

    X = pd.DataFrame([row])

    proba = float(pipe.predict_proba(X)[:, 1][0])
    pred = 1 if proba >= THRESHOLD else 0

    #label = "Admission (1)" if pred == 1 else "Home (0)"
    #msg = f"Pred = {label} | P(Admission=1) = {proba:.4f} | threshold = {THRESHOLD:.2f}"
    #return proba, label, msg


    # 後端 class code（不建議改）
    pred_code = pred

    # 顯示文字（你可自由改 UI_OUTPUT_TEXT）
    pred_text = UI_OUTPUT_TEXT["class_admission"] if pred_code == 1 else UI_OUTPUT_TEXT["class_home"]

    # Predicted class 欄位要顯示什麼
    label = UI_OUTPUT_TEXT["pred_label_fmt"].format(label=pred_text, code=pred_code)

    # Message 欄位要顯示什麼
    msg = UI_OUTPUT_TEXT["message_fmt"].format(
        pred_text=pred_text,
        code=pred_code,
        proba=proba,
        threshold=THRESHOLD,
    )

    return proba, label, msg


# ============================================================
# UI
# ============================================================

with gr.Blocks() as demo:
    gr.Markdown(UI_LABELS["title"])
    gr.Markdown(UI_LABELS["subtitle"])

    with gr.Row():
        sex = gr.Dropdown(
            choices=SEX_DISPLAY_CHOICES,
            label=UI_LABELS["sex"],
            value=SEX_DISPLAY_CHOICES[0] if len(SEX_DISPLAY_CHOICES) > 0 else None
        )
        clinicby = gr.Dropdown(
            choices=CLINICBY_DISPLAY_CHOICES,
            label=UI_LABELS["CLINICSBY_cat"],
            value=CLINICBY_DISPLAY_CHOICES[0] if len(CLINICBY_DISPLAY_CHOICES) > 0 else None
        )

    with gr.Row():
        age = gr.Number(label=UI_LABELS["age"], minimum=0, maximum=120, value=40)

        consfull = gr.Dropdown(
            choices=BINARY01_DISPLAY_CHOICES,
            label=UI_LABELS["consfullE0V0M0orE4V5M6"],
            value=BINARY01_DISPLAY[1]
        )
        backER = gr.Dropdown(
            choices=BINARY01_DISPLAY_CHOICES,
            label=UI_LABELS["backER"],
            value=BINARY01_DISPLAY[0]
        )
        visit3days = gr.Dropdown(
            choices=BINARY01_DISPLAY_CHOICES,
            label=UI_LABELS["VISITINTHREEDAYS"],
            value=BINARY01_DISPLAY[0]
        )

    with gr.Row():
        bodytemp = gr.Number(label=UI_LABELS["BODYTEMPERATURE_num"], minimum=25, maximum=45, value=36.5)
        pulse = gr.Number(label=UI_LABELS["PULSE_num"], minimum=0, maximum=250, value=80)
        resp = gr.Number(label=UI_LABELS["RESPIRATION_num"], minimum=0, maximum=80, value=18)

    with gr.Row():
        systolic = gr.Number(label=UI_LABELS["SYSTOLIC_num"], minimum=0, maximum=300, value=120)
        diastolic = gr.Number(label=UI_LABELS["DIASTOLIC_num"], minimum=0, maximum=200, value=70)
        pain_index = gr.Slider(minimum=0, maximum=10, step=1, label=UI_LABELS["PAININDEX_num0to10"], value=0)

    with gr.Row():
        pain_any = gr.Dropdown(
            choices=BINARY01_DISPLAY_CHOICES,
            label=UI_LABELS["pain_any_1"],
            value=BINARY01_DISPLAY[0]
        )

    gr.Markdown(f"### {UI_LABELS['missing_flags_title']}")
    with gr.Row():
        bt_miss = gr.Dropdown(choices=BINARY01_DISPLAY_CHOICES, label=UI_LABELS["BT_missing"], value=BINARY01_DISPLAY[0])
        pulse_miss = gr.Dropdown(choices=BINARY01_DISPLAY_CHOICES, label=UI_LABELS["pulse_missing"], value=BINARY01_DISPLAY[0])
        resp_miss = gr.Dropdown(choices=BINARY01_DISPLAY_CHOICES, label=UI_LABELS["respiration_missing"], value=BINARY01_DISPLAY[0])
        sys_miss = gr.Dropdown(choices=BINARY01_DISPLAY_CHOICES, label=UI_LABELS["systolic_missing"], value=BINARY01_DISPLAY[0])
        dia_miss = gr.Dropdown(choices=BINARY01_DISPLAY_CHOICES, label=UI_LABELS["diastolic_missing"], value=BINARY01_DISPLAY[0])

    cc_text = gr.Textbox(
        label=UI_LABELS["cc_text"],
        lines=3,
        placeholder="Examples: abdominal pain for 3 days."
    )

    btn = gr.Button(UI_LABELS["predict_btn"])

    out_proba = gr.Number(label=UI_LABELS["out_proba"])
    out_label = gr.Textbox(label=UI_LABELS["out_label"])
    out_msg = gr.Textbox(label=UI_LABELS["out_msg"])

    btn.click(
        predict,
        inputs=[sex, age, consfull, backER, visit3days, clinicby,
                bodytemp, pulse, resp, systolic, diastolic,
                bt_miss, pulse_miss, resp_miss, sys_miss, dia_miss,
                pain_any, pain_index,
                cc_text],
        outputs=[out_proba, out_label, out_msg]
    )

if __name__ == "__main__":
    demo.launch()
