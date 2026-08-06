from fastapi.testclient import TestClient
from app.main import app
import os
from dotenv import load_dotenv
load_dotenv()

client = TestClient(app)

API_KEY = os.getenv("API_KEY")

headers = {
    "X-API-Key": API_KEY
}


def test_home():

    response = client.get("/")

    assert response.status_code == 200


def test_predict():

    payload = {
        "YearBuilt": 2005,
        "BuildingAge": 21,
        "NumberofFloors": 5,
        "Log_Surface": 11,
        "PropertyGFATotal": 100000.0,
        "LargestPropertyUseTypeGFA": 80000.0,
        "PropertyGFABuilding_s": 95000.0,
        "BuildingType": "NonResidential",
        "PrimaryPropertyType": "Office",
        "City": "Seattle",
        "State": "WA"
    }

    response = client.post(
        "/predict",
        json=payload,
        headers=headers
    )

    assert response.status_code == 200
    assert "prediction_kbtu" in response.json()


def test_predict_without_api_key():

    payload = {
        "YearBuilt": 2005,
        "BuildingAge": 21,
        "NumberofFloors": 5,
        "Log_Surface": 11,
        "PropertyGFATotal": 100000.0,
        "LargestPropertyUseTypeGFA": 80000.0,
        "PropertyGFABuilding_s": 95000.0,
        "BuildingType": "NonResidential",
        "PrimaryPropertyType": "Office",
        "City": "Seattle",
        "State": "WA"
    }

    response = client.post(
        "/predict",
        json=payload
    )

    assert response.status_code == 403