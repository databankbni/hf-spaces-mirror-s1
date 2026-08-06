import gradio as gr
import torch
import torch.nn as nn
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

# ===================== Model Definition =====================
class HFA_PINN(nn.Module):
    def __init__(self, sx, sy):
        super().__init__()
        self.register_buffer('x_min',   torch.tensor(sx.data_min_, dtype=torch.float32))
        self.register_buffer('x_scale', torch.tensor(sx.scale_,    dtype=torch.float32))
        self.register_buffer('y_min',   torch.tensor(sy.data_min_, dtype=torch.float32))
        self.register_buffer('y_scale', torch.tensor(sy.scale_,    dtype=torch.float32))
        self.w1     = nn.Parameter(torch.tensor(0.0))
        self.w2     = nn.Parameter(torch.tensor(0.0))
        self.w3     = nn.Parameter(torch.tensor(0.0))
        self.w4     = nn.Parameter(torch.tensor(0.0))
        self.k_act  = nn.Parameter(torch.tensor(0.0))
        self.k_temp = nn.Parameter(torch.tensor(0.0))
        self.k_eps  = nn.Parameter(torch.tensor(0.0))
        self.mlp = nn.Sequential(
            nn.Linear(5, 32), nn.Tanh(),
            nn.Linear(32, 32), nn.Tanh(),
            nn.Linear(32, 1))

    def forward(self, xn):
        xr = xn / self.x_scale + self.x_min
        fcu, c, d   = xr[:, 0:1], xr[:, 1:2], xr[:, 2:3]
        l, T, eps   = xr[:, 3:4], xr[:, 4:5], xr[:, 5:6]
        cd = c / (d + 1e-6)
        ld = l / (d + 1e-6)
        w1, w2 = torch.abs(self.w1), torch.abs(self.w2)
        w3, w4 = torch.abs(self.w3), torch.abs(self.w4)
        t1 = torch.relu(w1 - w2 * ld) + 1e-6
        t2 = w3 + w4 * torch.log(1 + cd)
        sma = (1 + self.k_act * (T > 0).float()
                 + self.k_temp * (T / 100)
                 + self.k_eps  * (eps / 0.02))
        tp = (t1 * t2 * torch.sqrt(torch.clamp(fcu, min=1e-6)) * sma
              - self.y_min) * self.y_scale
        feats = torch.cat([xn[:, 0:1], (cd-5)/5, (ld-5)/5,
                           xn[:, 4:5], xn[:, 5:6]], dim=1)
        return tp + self.mlp(feats)

# ===================== Load Model =====================
FEAT = ['fcu', 'c', 'd', 'l', 't_act', 'eps']
df_train = pd.read_excel('data.xlsx')
df_train.columns = [c.lower() for c in df_train.columns]
X_tr = df_train[FEAT].values
Y_tr = df_train[['tu']].values
sx = MinMaxScaler().fit(X_tr)
sy = MinMaxScaler().fit(Y_tr)

model = HFA_PINN(sx, sy)
model.load_state_dict(torch.load('model_weights.pth', map_location='cpu', weights_only=True))
model.eval()

TRAIN_RANGES = {col: (X_tr[:, i].min(), X_tr[:, i].max())
                for i, col in enumerate(FEAT)}

# ===================== Prediction Function =====================
def predict(fcu, c, d, l, t_act, eps_pct):
    eps = eps_pct / 100.0
    x = np.array([[fcu, c, d, l, t_act, eps]], dtype=np.float32)
    xn = torch.tensor(sx.transform(x), dtype=torch.float32)
    with torch.no_grad():
        yn = model(xn).numpy()
    tau = float(sy.inverse_transform(yn).ravel()[0])

    vals = {'fcu': fcu, 'c': c, 'd': d, 'l': l, 't_act': t_act, 'eps': eps}
    ood_flags = []
    for col, v in vals.items():
        lo, hi = TRAIN_RANGES[col]
        if v < lo or v > hi:
            ood_flags.append(col)

    result_text = f"### Predicted Ultimate Bond Strength  τ_u = **{tau:.3f} MPa**"
    if ood_flags:
        ood_names = {'fcu': 'Concrete Strength', 'c': 'Cover Thickness', 'd': 'Rebar Diameter',
                     'l': 'Anchorage Length', 't_act': 'Activation Temperature', 'eps': 'Pre-strain'}
        flags_str = ', '.join([ood_names.get(f, f) for f in ood_flags])
        warning = f"\n\n⚠️ **Extrapolation Warning**: {flags_str} is outside the training data range. This prediction is an out-of-domain extrapolation — please use with caution."
    else:
        warning = "\n\n✅ **In-domain Prediction**: All parameters are within the training data range. Prediction reliability is high."

    return result_text + warning


# ===================== Interface =====================
CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&display=swap');

body, .gradio-container {
    background: #f5f6fa !important;
    font-family: 'DM Sans', sans-serif !important;
}

.gradio-container { max-width: 1100px !important; }

.gr-panel, .gr-box, .gr-form, .gr-block {
    background: #ffffff !important;
    border: 1px solid #e2e6f0 !important;
    border-radius: 12px !important;
    box-shadow: 0 2px 8px rgba(15,30,80,0.05) !important;
}

h1, h2, h3 { color: #1a1d2e !important; font-weight: 600 !important; }

.gr-button-primary {
    background: linear-gradient(135deg, #e05a3a 0%, #c0392b 100%) !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
    color: #ffffff !important;
    box-shadow: 0 4px 14px rgba(224,90,58,0.30) !important;
}

.gr-button-primary:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(224,90,58,0.42) !important;
}

label, .gr-block-label {
    color: #4a5068 !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
}

.gr-markdown p {
    color: #4a5068 !important;
    font-size: 0.95rem !important;
    line-height: 1.7 !important;
}

.gr-markdown h3 {
    color: #1a1d2e !important;
    font-size: 1.1rem !important;
    margin-top: 14px !important;
    margin-bottom: 8px !important;
}

.output-text {
    background: #fff8f6 !important;
    border-left: 4px solid #e05a3a !important;
    border-radius: 0 12px 12px 0 !important;
    padding: 22px 26px !important;
    min-height: 120px !important;
}

.output-text h3 {
    font-size: 1.25rem !important;
    color: #c0392b !important;
}

#hfa-badge {
    display: inline-block;
    background: rgba(224,90,58,0.10);
    border: 1px solid rgba(224,90,58,0.35);
    border-radius: 22px;
    padding: 3px 14px;
    font-size: 0.72rem;
    color: #c0392b;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
}

#range-info {
    background: linear-gradient(135deg, #f0f4ff 0%, #e8eeff 100%);
    border: 1px solid #d4dcf3;
    border-radius: 10px;
    padding: 14px 20px;
    margin-top: 4px;
    margin-bottom: 4px;
}
"""

HEADER = """
<div style="padding: 24px 0 12px 0;">
  <span id="hfa-badge">HFA-PINN · Construction and Building Materials</span>
  <h1 style="margin: 14px 0 8px 0; font-size: 1.85rem; color: #1a1d2e; font-weight: 700; letter-spacing: -0.5px;">
    Fe-SMA Rebar–Concrete Interface Ultimate Bond Strength Prediction
  </h1>
  <p style="color: #6b7280; font-size: 0.92rem; margin: 0; line-height: 1.7;">
    Powered by the High-Fidelity Adaptive Physics-Guided Neural Network (HFA-PINN) ·
    LOOCV Validation Accuracy:
    <strong style="color:#c0392b;">R²=0.983</strong>　·　
    <strong style="color:#c0392b;">RMSE=1.449 MPa</strong>　·　
    <strong style="color:#c0392b;">MAPE=9.46%</strong>
  </p>
</div>
"""

PARAM_INFO = """
<div id="range-info">
  <p style="color:#3b4a6b; font-size:0.82rem; margin:0; line-height:1.8; font-weight:500;">
    <span style="color:#1a1d2e; font-weight:600;">Training Data Range:</span>　
    <span style="color:#3b5bdb;">fcu: 33.5-116.8 MPa</span>　·　
    <span style="color:#3b5bdb;">c: 50-75 mm</span>　·　
    <span style="color:#3b5bdb;">d: 6-16 mm</span>　·　
    <span style="color:#3b5bdb;">l: 30-80 mm</span>　·　
    <span style="color:#3b5bdb;">T_act: 0-350 °C</span>　·　
    <span style="color:#3b5bdb;">ε: 0-4 %</span>
  </p>
</div>
"""

with gr.Blocks(css=CSS, theme=gr.themes.Soft(
        primary_hue="orange", neutral_hue="slate")) as demo:
    gr.HTML(HEADER)
    gr.HTML(PARAM_INFO)

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### Input Parameters")
            fcu = gr.Slider(20, 150, value=43, step=0.5,
                            label="Concrete Compressive Strength, fcu (MPa)")
            c   = gr.Slider(20, 100, value=50, step=1,
                            label="Concrete Cover Thickness, c (mm)")
            d   = gr.Slider(6, 20, value=10, step=1,
                            label="Fe-SMA Rebar Diameter, d (mm)")
            l   = gr.Slider(20, 150, value=50, step=5,
                            label="Anchorage Length, l (mm)")
            t   = gr.Slider(0, 400, value=200, step=10,
                            label="Activation Temperature, T_act (°C)")
            eps = gr.Slider(0, 10, value=2, step=0.5,
                            label="Pre-strain, ε (%)")

            btn = gr.Button("▶  Predict", variant="primary", size="lg")

        with gr.Column(scale=1):
            gr.Markdown("### Prediction Result")
            result = gr.Markdown(elem_classes=["output-text"])

    btn.click(fn=predict,
              inputs=[fcu, c, d, l, t, eps],
              outputs=[result])

    gr.HTML("""
<div style="text-align:center; padding:20px 0 8px 0; border-top:1px solid #e2e6f0; margin-top:24px;">
  <p style="color:#8a92a8; font-size:0.78rem; margin:0; line-height:1.7;">
    HFA-PINN · High-Fidelity Adaptive Physics-Guided Neural Network · N=46 · LOOCV validated<br>
    <span style="color:#aab0c2;">Submitted to: Construction and Building Materials</span>
  </p>
</div>
""")

if __name__ == "__main__":
    demo.launch()
