import joblib
import pandas as pd
from huggingface_hub import hf_hub_download

model_path = hf_hub_download(
    repo_id="ManouDig/energie",
    filename="model.pkl"
)


model = joblib.load(model_path)

def predict_energy(features):
    df = pd.DataFrame([features])

    df = df.rename(
        columns={
            "PropertyGFABuilding_s": "PropertyGFABuilding(s)"
        }
    )

    prediction = model.predict(df)

    return float(prediction[0])