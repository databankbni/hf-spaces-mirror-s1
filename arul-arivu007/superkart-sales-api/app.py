import gradio as gr
import pandas as pd
import joblib

from huggingface_hub import hf_hub_download

# ==========================================================
# Download model and preprocessor from Hugging Face Model Hub
# ==========================================================

MODEL_REPO = "arul-arivu007/tourism-package-xgboost-model"

model_path = hf_hub_download(
    repo_id=MODEL_REPO,
    filename="tourism_package_model.pkl"
)

preprocessor_path = hf_hub_download(
    repo_id=MODEL_REPO,
    filename="preprocessor.pkl"
)

model = joblib.load(model_path)

# ==========================================================
# Prediction Function
# ==========================================================

def predict_package(
    age,
    contact,
    citytier,
    duration,
    occupation,
    gender,
    persons,
    followups,
    product,
    property_star,
    marital,
    trips,
    passport,
    satisfaction,
    own_car,
    children,
    designation,
    income
):

    passport = int(passport)
    own_car = int(own_car)
    
    input_df = pd.DataFrame([{
        "Age": age,
        "TypeofContact": contact,
        "CityTier": citytier,
        "DurationOfPitch": duration,
        "Occupation": occupation,
        "Gender": gender,
        "NumberOfPersonVisiting": persons,
        "NumberOfFollowups": followups,
        "ProductPitched": product,
        "PreferredPropertyStar": property_star,
        "MaritalStatus": marital,
        "NumberOfTrips": trips,
        "Passport": passport,
        "PitchSatisfactionScore": satisfaction,
        "OwnCar": own_car,
        "NumberOfChildrenVisiting": children,
        "Designation": designation,
        "MonthlyIncome": income
    }])

    prediction = model.predict(input_df)[0]
    probability = model.predict_proba(input_df)[0][1]

    if prediction == 1:
        result = "✅ Likely to Purchase"
    else:
        result = "❌ Unlikely to Purchase"
    
    return result, f"{probability:.2%}"

# ==========================================================
# Gradio Interface
# ==========================================================

demo = gr.Interface(

    fn=predict_package,

    inputs=[

        gr.Number(value=35, label="Age"),

        gr.Dropdown(
            ["Company Invited", "Self Enquiry"],
            value="Self Enquiry",
            label="Type of Contact"
        ),

        gr.Slider(1, 3, value=2, step=1, label="City Tier"),

        gr.Number(value=15, label="Duration of Pitch"),

        gr.Dropdown(
            [
                "Free Lancer",
                "Large Business",
                "Salaried",
                "Small Business"
            ],
            value="Salaried",
            label="Occupation"
        ),

        gr.Dropdown(
            [
                "Male",
                "Female",
                "Fe Male"
            ],
            value="Male",
            label="Gender"
        ),

        gr.Number(value=2, label="Number of Persons Visiting"),

        gr.Number(value=3, label="Number of Follow-ups"),

        gr.Dropdown(
            [
                "Basic",
                "Standard",
                "Deluxe",
                "Super Deluxe",
                "King"
            ],
            value="Deluxe",
            label="Product Pitched"
        ),

        gr.Slider(1, 5, value=3, step=1,
                  label="Preferred Property Star"),

        gr.Dropdown(
            [
                "Single",
                "Married",
                "Divorced",
                "Unmarried"
            ],
            value="Married",
            label="Marital Status"
        ),

        gr.Number(value=2, label="Number of Trips"),

        gr.Radio(
            choices=["0", "1"],
            value="1",
            label="Passport Available"
        ),

        gr.Slider(
            1,
            5,
            value=3,
            step=1,
            label="Pitch Satisfaction Score"
        ),

        gr.Radio(
            choices=["0", "1"],
            value="1",
            label="Own Car"
        ),

        gr.Number(value=1,
                  label="Number of Children Visiting"),

        gr.Dropdown(
            [
                "Executive",
                "Manager",
                "Senior Manager",
                "AVP",
                "VP"
            ],
            value="Manager",
            label="Designation"
        ),

        gr.Number(value=25000,
                  label="Monthly Income")

    ],

    outputs=[
        gr.Textbox(label="Prediction"),
        gr.Textbox(label="Probability")
    ],

    title="Tourism Package Purchase Prediction",

    description="""
Predict whether a customer is likely to purchase the Wellness Tourism Package using a trained XGBoost classifier deployed from the Hugging Face Model Hub.
"""
)

demo.launch()