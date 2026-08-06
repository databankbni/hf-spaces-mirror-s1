from app.ml_model import predict_energy

def test_prediction():

    data = {
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

    prediction = predict_energy(data)

    assert isinstance(prediction, float)
    assert prediction > 0