import gradio as gr
import joblib
import numpy as np

# load model and scaler
model = joblib.load("credit_risk_model.pkl")
scaler = joblib.load("scaler.pkl")

def predict_default(limit_bal, age, pay_0, pay_2, pay_3, pay_4, pay_5, pay_6,
                    bill_amt1, bill_amt2, bill_amt3, bill_amt4, bill_amt5, bill_amt6,
                    pay_amt1, pay_amt2, pay_amt3, pay_amt4, pay_amt5, pay_amt6,
                    sex, education, marriage):
    
    features = np.array([[limit_bal, sex, education, marriage, age,
                          pay_0, pay_2, pay_3, pay_4, pay_5, pay_6,
                          bill_amt1, bill_amt2, bill_amt3, bill_amt4, bill_amt5, bill_amt6,
                          pay_amt1, pay_amt2, pay_amt3, pay_amt4, pay_amt5, pay_amt6]])
    
    features_scaled = scaler.transform(features)
    prediction = model.predict(features_scaled)[0]
    probability = model.predict_proba(features_scaled)[0][1]
    
    result = "HIGH RISK — Likely to Default" if prediction == 1 else "LOW RISK — Unlikely to Default"
    return f"{result}\nDefault Probability: {probability:.1%}"

demo = gr.Interface(
    fn=predict_default,
    inputs=[
        gr.Number(label="Credit Limit (LIMIT_BAL)"),
        gr.Number(label="Age"),
        gr.Slider(-2, 8, step=1, label="Payment Status Month 1 (PAY_0)"),
        gr.Slider(-2, 8, step=1, label="Payment Status Month 2 (PAY_2)"),
        gr.Slider(-2, 8, step=1, label="Payment Status Month 3 (PAY_3)"),
        gr.Slider(-2, 8, step=1, label="Payment Status Month 4 (PAY_4)"),
        gr.Slider(-2, 8, step=1, label="Payment Status Month 5 (PAY_5)"),
        gr.Slider(-2, 8, step=1, label="Payment Status Month 6 (PAY_6)"),
        gr.Number(label="Bill Amount Month 1 (BILL_AMT1)"),
        gr.Number(label="Bill Amount Month 2 (BILL_AMT2)"),
        gr.Number(label="Bill Amount Month 3 (BILL_AMT3)"),
        gr.Number(label="Bill Amount Month 4 (BILL_AMT4)"),
        gr.Number(label="Bill Amount Month 5 (BILL_AMT5)"),
        gr.Number(label="Bill Amount Month 6 (BILL_AMT6)"),
        gr.Number(label="Payment Amount Month 1 (PAY_AMT1)"),
        gr.Number(label="Payment Amount Month 2 (PAY_AMT2)"),
        gr.Number(label="Payment Amount Month 3 (PAY_AMT3)"),
        gr.Number(label="Payment Amount Month 4 (PAY_AMT4)"),
        gr.Number(label="Payment Amount Month 5 (PAY_AMT5)"),
        gr.Number(label="Payment Amount Month 6 (PAY_AMT6)"),
        gr.Dropdown([1, 2], label="Sex (1=Male, 2=Female)"),
        gr.Dropdown([1, 2, 3, 4], label="Education (1=Grad, 2=Uni, 3=HS, 4=Other)"),
        gr.Dropdown([1, 2, 3], label="Marriage (1=Married, 2=Single, 3=Other)"),
    ],
    outputs=gr.Textbox(label="Prediction"),
    title="Credit Risk Predictor",
    description="Predicts whether a credit card client is likely to default next month."
)

demo.launch()