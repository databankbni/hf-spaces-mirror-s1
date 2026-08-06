import gradio as gr
import pandas as pd
import joblib
from huggingface_hub import hf_hub_download

# =========================
# LOAD TRAINED AI MODEL
# =========================

MODEL_PATH = hf_hub_download(
    repo_id="Manii77/loan-approval-prediction",
    filename="loan_approval_model.pkl"
)

package = joblib.load(MODEL_PATH)

model = package["model"]
preprocessor = package["preprocessor"]


# =========================
# AI PREDICTION FUNCTION
# =========================

def predict_loan(
    age,
    gender,
    married,
    dependents,
    education,
    self_employed,
    applicant_income,
    coapplicant_income,
    loan_amount,
    loan_term,
    credit_history,
    property_area
):

    data = pd.DataFrame([{
        "Age": age,
        "Gender": gender,
        "Married": married,
        "Dependents": dependents,
        "Education": education,
        "Self_Employed": self_employed,
        "ApplicantIncome": applicant_income,
        "CoapplicantIncome": coapplicant_income,
        "LoanAmount": loan_amount,
        "Loan_Term_Months": loan_term,
        "Credit_History": credit_history,
        "Property_Area": property_area
    }])

    processed_data = preprocessor.transform(data)

    prediction = model.predict(processed_data)[0]

    # Probability if supported by model
    confidence = None

    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(processed_data)[0]
        confidence = max(probabilities) * 100

    if str(prediction).lower() == "approved":
        result = "✅ LOAN APPROVED"
        message = "The AI model predicts that this application is likely to be approved."
    else:
        result = "❌ LOAN REJECTED"
        message = "The AI model predicts that this application is likely to be rejected."

    if confidence is not None:
        confidence_text = f"### 🤖 AI Confidence: {confidence:.2f}%"
    else:
        confidence_text = "### 🤖 AI Confidence: Not available"

    return result, message, confidence_text


# =========================
# PROFESSIONAL UI
# =========================

css = """
#title {
    text-align: center;
    font-size: 32px;
    font-weight: bold;
}

#subtitle {
    text-align: center;
    font-size: 16px;
}

#result {
    text-align: center;
    font-size: 26px;
    font-weight: bold;
}

#predict_btn {
    font-size: 18px;
    font-weight: bold;
}

.footer {
    text-align: center;
    margin-top: 20px;
}
"""


with gr.Blocks(
    title="AI Loan Approval System",
    css=css
) as demo:

    gr.Markdown(
        """
        # 🏦 AI-BASED LOAN APPROVAL PREDICTION SYSTEM
        """,
        elem_id="title"
    )

    gr.Markdown(
        """
        ### Intelligent Machine Learning System for Loan Eligibility Prediction
        Enter applicant information below and let the trained AI model predict the loan decision.
        """,
        elem_id="subtitle"
    )

    gr.Markdown("---")

    with gr.Row():

        # =====================
        # APPLICANT INFORMATION
        # =====================

        with gr.Column():

            gr.Markdown("## 👤 Applicant Information")

            age = gr.Number(
                label="Age",
                value=30
            )

            gender = gr.Dropdown(
                ["Male", "Female"],
                label="Gender",
                value="Male"
            )

            married = gr.Dropdown(
                ["Yes", "No"],
                label="Married",
                value="Yes"
            )

            dependents = gr.Dropdown(
                ["0", "1", "2", "3+"],
                label="Dependents",
                value="0"
            )

            education = gr.Dropdown(
                ["Graduate", "Not Graduate"],
                label="Education",
                value="Graduate"
            )

            self_employed = gr.Dropdown(
                ["Yes", "No"],
                label="Self Employed",
                value="No"
            )

        # =====================
        # FINANCIAL INFORMATION
        # =====================

        with gr.Column():

            gr.Markdown("## 💰 Financial Information")

            applicant_income = gr.Number(
                label="Applicant Income",
                value=5000
            )

            coapplicant_income = gr.Number(
                label="Coapplicant Income",
                value=2000
            )

            loan_amount = gr.Number(
                label="Loan Amount",
                value=150
            )

            loan_term = gr.Number(
                label="Loan Term (Months)",
                value=360
            )

            credit_history = gr.Dropdown(
                [0, 1],
                label="Credit History",
                value=1
            )

            property_area = gr.Dropdown(
                ["Urban", "Semiurban", "Rural"],
                label="Property Area",
                value="Urban"
            )

    gr.Markdown("---")

    predict_btn = gr.Button(
        "🚀 PREDICT LOAN APPROVAL",
        variant="primary",
        elem_id="predict_btn"
    )

    gr.Markdown("## 📊 AI Prediction Result")

    result = gr.Textbox(
        label="Decision",
        elem_id="result"
    )

    message = gr.Textbox(
        label="AI Analysis"
    )

    confidence = gr.Markdown(
        "### 🤖 AI Confidence: --"
    )

    predict_btn.click(
        fn=predict_loan,
        inputs=[
            age,
            gender,
            married,
            dependents,
            education,
            self_employed,
            applicant_income,
            coapplicant_income,
            loan_amount,
            loan_term,
            credit_history,
            property_area
        ],
        outputs=[
            result,
            message,
            confidence
        ]
    )

    gr.Markdown(
        """
        ---

        ### 🧠 About This Project

        **Model:** Random Forest Classifier  
        **Task:** Loan Approval Prediction  
        **Training:** Machine Learning  
        **Dataset:** 50,000 records  
        **Training Samples:** 4,000  
        **Testing Samples:** 1,000  
        **Unseen Samples:** 150  

        **Note:** This application is an academic machine-learning project.
        The prediction is not a real financial decision.

        <div class="footer">
        🎓 AI Academic Project | Built with Python, Scikit-learn & Gradio
        </div>
        """
    )


# =========================
# LAUNCH APPLICATION
# =========================

if __name__ == "__main__":
    demo.launch()