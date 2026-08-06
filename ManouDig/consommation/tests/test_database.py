from app.database import SessionLocal
from app.models import Prediction


def test_insert_prediction():

    db = SessionLocal()

    prediction = Prediction(
        YearBuilt=2000,
        BuildingAge=24,
        NumberofFloors=5,
        Log_Surface=11,
        PropertyGFATotal=100000,
        LargestPropertyUseTypeGFA=80000,
        PropertyGFABuilding_s=95000,
        BuildingType="NonResidential",
        PrimaryPropertyType="Office",
        City="Seattle",
        State="WA",
        prediction_kbtu=12345.6
    )

    db.add(prediction)
    db.commit()
    db.refresh(prediction)

    assert prediction.prediction_id is not None

    db.delete(prediction)
    db.commit()

    db.close()


def test_delete_prediction():

    db = SessionLocal()

    prediction = Prediction(
        YearBuilt=2000,
        BuildingAge=24,
        NumberofFloors=5,
        Log_Surface=11,
        PropertyGFATotal=100000,
        LargestPropertyUseTypeGFA=80000,
        PropertyGFABuilding_s=95000,
        BuildingType="NonResidential",
        PrimaryPropertyType="Office",
        City="Seattle",
        State="WA",
        prediction_kbtu=12345.6
    )

    db.add(prediction)
    db.commit()
    db.refresh(prediction)

    prediction_id = prediction.prediction_id

    db.delete(prediction)
    db.commit()

    result = (
        db.query(Prediction)
        .filter(Prediction.prediction_id == prediction_id)
        .first()
    )

    assert result is None

    db.close()