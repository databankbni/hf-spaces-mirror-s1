import time

from app.models import Prediction, Monitoring, Dataset


def save_prediction(db, data, prediction):

    start = time.time()

    # -----------------------------
    # Table predictions
    # -----------------------------
    prediction_row = Prediction(
        YearBuilt=data.YearBuilt,
        BuildingAge=data.BuildingAge,
        NumberofFloors=data.NumberofFloors,
        Log_Surface=data.Log_Surface,
        PropertyGFATotal=data.PropertyGFATotal,
        LargestPropertyUseTypeGFA=data.LargestPropertyUseTypeGFA,
        PropertyGFABuilding_s=data.PropertyGFABuilding_s,
        BuildingType=data.BuildingType,
        PrimaryPropertyType=data.PrimaryPropertyType,
        City=data.City,
        State=data.State,
        prediction_kbtu=prediction
    )

    db.add(prediction_row)
    db.commit()
    db.refresh(prediction_row)

    # Temps de réponse
    response_time = round((time.time() - start) * 1000, 2)

    # -----------------------------
    # Table monitoring
    # -----------------------------
    monitoring_row = Monitoring(
        prediction_id=prediction_row.prediction_id,
        response_time_ms=response_time,
        model_version="RandomForest_v1",
        status="SUCCESS"
    )

    db.add(monitoring_row)

  

    db.commit()

    return prediction_row