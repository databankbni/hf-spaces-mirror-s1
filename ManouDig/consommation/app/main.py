from fastapi import FastAPI, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import gradio as gr

from app.schemas import BuildingInput
from app.ml_model import predict_energy
from app.database import Base, engine, get_db
from app.crud import save_prediction
from app.app_gradio import gradio_interface
from app.security import verify_api_key   # <-- AJOUT


# Création des tables si elles n'existent pas
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Seattle Energy Prediction API",
    description="API de prédiction de la consommation énergétique des bâtiments de Seattle.",
    version="2.0.0"
)


@app.get("/")
def home():
    return RedirectResponse(url="/gradio/")


@app.post("/predict", tags=["Prediction"])
def predict(
    building: BuildingInput,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    features = {
        "YearBuilt": building.YearBuilt,
        "BuildingAge": building.BuildingAge,
        "NumberofFloors": building.NumberofFloors,
        "Log_Surface": building.Log_Surface,
        "PropertyGFATotal": building.PropertyGFATotal,
        "LargestPropertyUseTypeGFA": building.LargestPropertyUseTypeGFA,
        "PropertyGFABuilding_s": building.PropertyGFABuilding_s,
        "BuildingType": building.BuildingType,
        "PrimaryPropertyType": building.PrimaryPropertyType,
        "City": building.City,
        "State": building.State,
    }

    prediction = predict_energy(features)

    # Historisation dans Neon
    save_prediction(
        db=db,
        data=building,
        prediction=prediction
    )

    return {
        "prediction_kbtu": round(prediction, 2)
    }


# Interface Gradio
app = gr.mount_gradio_app(
    app,
    gradio_interface,
    path="/gradio"
    )