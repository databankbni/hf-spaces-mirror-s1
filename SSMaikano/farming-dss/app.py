import numpy as np
import pandas as pd
import gradio as gr
import plotly.graph_objects as go

from sklearn.naive_bayes import BernoulliNB

from sklearn.model_selection import GridSearchCV, LeaveOneOut

from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    roc_curve
)

# ==========================================
# RANDOM SEED
# ==========================================
np.random.seed(42)

# ==========================================
# CARD
# ==========================================
def card(title, value, color):
    return f"""
    <div style="
        background:{color};
        padding:10px;
        border-radius:10px;
        color:white;
        width:140px;
        margin:2px;
        display:inline-block;
        text-align:center;">
        <h4>{title}</h4>
        <h2>{value}</h2>
    </div>
    """

# ==========================================
# CONFIDENCE CARD
# ==========================================
def confidence_card(value_pct, color):
    pct = int(min(max(value_pct, 0), 100))

    return f"""
    <div style="
        background:{color};
        padding:10px;
        border-radius:10px;
        color:white;
        width:140px;
        margin:2px;
        display:inline-block;
        text-align:center;">
        
        <h4>Confidence</h4>
        <h2>{value_pct:.0f}%</h2>

        <div style="
            background:#ddd;
            height:6px;
            border-radius:6px;">

            <div style="
                width:{pct}%;
                background:white;
                height:6px;">
            </div>
        </div>
    </div>
    """

# ==========================================
# DATA
# ==========================================
n = 112

dates = pd.date_range(
    start="2024-05-10",
    periods=n
)

df = pd.DataFrame({
    "Date": dates,
    "Rainfall": 5 + (np.arange(n) * 0.4) + np.random.normal(0, 2, n),
    "Evaporation": np.random.uniform(0, 15, n),
    "Humidity": np.random.uniform(50, 90, n),
    "Temperature": np.random.uniform(30, 40, n),
    "Wind": np.random.uniform(5, 10, n)
})

df["Month"] = df["Date"].dt.month

df = df[
    df["Month"].isin([5, 6, 7])
].reset_index(drop=True)

# ==========================================
# FEATURES
# ==========================================
df["Net"] = df["Rainfall"] - df["Evaporation"]

df["Moisture_bin"] = (df["Net"] >= 20).astype(int)
df["Humidity_High"] = (df["Humidity"] >= 70).astype(int)
df["Temp_High"] = (df["Temperature"] >= 35).astype(int)
df["Wind_High"] = (df["Wind"] >= 8).astype(int)

# ==========================================
# TRUE AND FALSE ONSET
# ==========================================
df["True_Onset"] = 0
df["False_Onset"] = 0

for i in range(2, len(df) - 10):

    if (df.loc[i - 2:i, "Rainfall"] >= 5).all():

        future = df.loc[i + 1:i + 7, "Rainfall"]

        dry = (future < 5).astype(int)

        max_dry = 0
        counter = 0

        for d in dry:
            if d == 1:
                counter += 1
                max_dry = max(max_dry, counter)
            else:
                counter = 0

        if max_dry >= 5:
            df.loc[i, "False_Onset"] = 1

        else:
            if df.loc[i, "Net"] >= 20:
                df.loc[i, "True_Onset"] = 1

# ==========================================
# SAFETY CHECK
# ==========================================
y = df["True_Onset"]

if y.nunique() < 2:

    positive_idx = df.index[-1]

    df.loc[positive_idx, "True_Onset"] = 1
    y = df["True_Onset"]

# ==========================================
# MODEL (GRID SEARCH + LOOCV + ALPHA TUNING)
# ==========================================

X = df[
    [
        "Moisture_bin",
        "Humidity_High",
        "Temp_High",
        "Wind_High"
    ]
]

# ------------------------------------------
# GRID SEARCH FOR BEST ALPHA
# ------------------------------------------

param_grid = {
    "alpha": [0.01, 0.1, 0.5, 1.0, 2.0, 5.0]
}

grid = GridSearchCV(
    estimator=BernoulliNB(),
    param_grid=param_grid,
    scoring="f1",
    cv=5,
    n_jobs=-1
)

grid.fit(X, y)

best_alpha = grid.best_params_["alpha"]

# ------------------------------------------
# LEAVE-ONE-OUT CROSS VALIDATION (LOOCV)
# ------------------------------------------

loo = LeaveOneOut()

loocv_predictions = []
loocv_probabilities = []
loocv_actuals = []

for train_idx, test_idx in loo.split(X):

    X_train = X.iloc[train_idx]
    X_test = X.iloc[test_idx]

    y_train = y.iloc[train_idx]
    y_test = y.iloc[test_idx]

    loo_model = BernoulliNB(
        alpha=best_alpha
    )

    loo_model.fit(X_train, y_train)

    pred = loo_model.predict(X_test)[0]
    prob = loo_model.predict_proba(X_test)[0][1]

    loocv_predictions.append(pred)
    loocv_probabilities.append(prob)
    loocv_actuals.append(y_test.iloc[0])

# ------------------------------------------
# FINAL MODEL USING OPTIMIZED ALPHA
# ------------------------------------------

model = BernoulliNB(
    alpha=best_alpha
)

model.fit(X, y)

y_eval = np.array(loocv_actuals)

preds = np.array(loocv_predictions)

probs = np.array(loocv_probabilities)

threshold = 0.50

cm = confusion_matrix(
    y_eval,
    preds
)

# ==========================================
# CONFUSION MATRIX PLOT
# ==========================================
def cm_plot():

    labels = [["TN", "FP"], ["FN", "TP"]]

    fig = go.Figure(
        go.Heatmap(
            z=cm,
            colorscale=[
                [0, "#f0f8ff"],
                [0.5, "#a8d0e6"],
                [1, "#5fa8d3"]
            ],
            showscale=False
        )
    )

    for i in range(2):
        for j in range(2):
            fig.add_annotation(
                x=j,
                y=i,
                text=f"{labels[i][j]}<br>{cm[i][j]}",
                showarrow=False
            )

    fig.update_layout(
        width=260,
        height=260,
        margin=dict(l=20, r=20, t=20, b=20)
    )

    fig.update_xaxes(title="Predicted")
    fig.update_yaxes(title="Actual")

    return fig

# ==========================================
# ROC PLOT
# ==========================================
def roc_plot():

    fpr, tpr, _ = roc_curve(y_eval, probs)

    fig = go.Figure(
        go.Scatter(
            x=fpr,
            y=tpr,
            mode="lines"
        )
    )

    fig.update_layout(
        width=320,
        height=240,
        title="ROC Curve"
    )

    return fig

# ==========================================
# ONSET PROBABILITY
# ==========================================
def onset_probability_plot():

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=df["Date"],
            y=probs,
            mode="lines+markers"
        )
    )

    fig.update_layout(
        width=500,
        height=250,
        title="Onset Probability"
    )

    return fig

# ==========================================
# DATASET HTML
# ==========================================
def dataset():

    d = df[
        [
            "Moisture_bin",
            "Humidity_High",
            "Temp_High",
            "Wind_High",
            "True_Onset",
            "False_Onset"
        ]
    ]

    return f"""
    <div class="scroll-table">
        {d.to_html(index=False, classes="small-table")}
    </div>
    """

# ==========================================
# METRICS
# ==========================================
def metrics():

    m = pd.DataFrame({
        "Metric": [
            "Accuracy",
            "Precision",
            "Recall",
            "F1 Score"
        ],
        "Value": [
            round(accuracy_score(y_eval, preds), 2),
            round(precision_score(y_eval, preds, zero_division=0), 2),
            round(recall_score(y_eval, preds, zero_division=0), 2),
            round(f1_score(y_eval, preds, zero_division=0), 2)
        ]
    })

    return m.to_html(index=False, classes="small-table")

# ==========================================
# THRESHOLD TABLE
# ==========================================
def threshold_table(r, e, w, h, t):

    net = r - e

    th = pd.DataFrame({
        "Parameter": [
            "Rainfall",
            "Net Moisture",
            "Humidity",
            "Temperature",
            "Wind"
        ],
        "Value": [r, net, h, t, w],
        "Threshold": [5, 20, 70, 35, 8],
        "Status": [
            "High" if r >= 5 else "Low",
            "Adequate" if net >= 20 else "Low",
            "High" if h >= 70 else "Low",
            "High" if t >= 35 else "Normal",
            "High" if w >= 8 else "Low"
        ]
    })

    return th.to_html(index=False, classes="small-table")

# ==========================================
# PREDICTION
# ==========================================
def predict(r, e, w, h, t):

    features = pd.DataFrame({
        "Moisture_bin": [int((r - e) >= 20)],
        "Humidity_High": [int(h >= 70)],
        "Temp_High": [int(t >= 35)],
        "Wind_High": [int(w >= 8)]
    })

    p = model.predict_proba(features)[0][1]

    conf = abs(p - threshold) / threshold * 100

    if conf >= 55:
        color = "#00ff87"
    elif conf >= 25:
        color = "#ffc107"
    else:
        color = "#ff4b2b"

    decision = (
        "START FARMING"
        if p >= threshold
        else "WAIT"
    )

    cards = (
        card(
            "Accuracy",
            round(
                accuracy_score(y, preds),
                2
            ),
            "#00c9ff"
        )
        +
        card(
            "Probability",
            round(p, 2),
            "#ff7a18"
        )
        +
        card(
            "Decision",
            decision,
            "green"
        )
        +
        confidence_card(
            conf,
            color
        )
    )

    return (
        cards,
        onset_probability_plot(),
        cm_plot(),
        roc_plot(),
        metrics(),
        dataset(),
        threshold_table(r, e, w, h, t)
    )

# ==========================================
# CSS
# ==========================================
css = """
.small-table table{
    width:100%;
    font-size:12px;
    border-collapse:collapse;
}

.small-table th,
.small-table td{
    padding:6px;
    border:1px solid #ddd;
    text-align:center;
}

.scroll-table{
    max-height:350px;
    overflow-y:auto;
    border:1px solid #ddd;
    border-radius:8px;
}

.scroll-table thead th{
    position:sticky;
    top:0;
    background:#f5f5f5;
    z-index:100;
}
"""

# ==========================================
# UI
# ==========================================
with gr.Blocks() as app:

    gr.Markdown("""
    # 🌱 Rainfall Onset Prediction System
    ### Optimized Bernoulli Naïve Bayes Model
    Provide meteorological conditions for rainfall onset analysis.
    """)

    with gr.Group():

        gr.Markdown(
            "#### 🌦️ Meteorological Input Parameters"
        )

        with gr.Row():

            r = gr.Slider(
                0,
                60,
                value=30,
                label="🌧️ Rainfall (mm)"
            )

            e = gr.Slider(
                0,
                20,
                value=5,
                label="💧 Evaporation (mm)"
            )

            w = gr.Slider(
                0,
                15,
                value=7,
                label="🌬️ Wind Speed (m/s)"
            )

        with gr.Row():

            h = gr.Slider(
                0,
                100,
                value=70,
                label="💦 Relative Humidity (%)"
            )

            t = gr.Slider(
                20,
                45,
                value=35,
                label="🌡️ Temperature (°C)"
            )

        btn = gr.Button("Analyze")

        cards = gr.HTML()
        op = gr.Plot()

        with gr.Tabs():

            with gr.Tab("Confusion Matrix"):
                cmg = gr.Plot()

            with gr.Tab("ROC"):
                rc = gr.Plot()

            with gr.Tab("Metrics"):
                mt = gr.HTML()

            with gr.Tab("Dataset"):
                dt = gr.HTML()

            with gr.Tab("Threshold"):
                th = gr.HTML()

        btn.click(
            fn=predict,
            inputs=[r, e, w, h, t],
            outputs=[
                cards,
                op,
                cmg,
                rc,
                mt,
                dt,
                th
            ]
        )

app.launch(
    share=True,
    css=css
)