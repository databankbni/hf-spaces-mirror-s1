from pydantic import BaseModel

class BuildingInput(BaseModel):

    YearBuilt: int
    BuildingAge: int
    NumberofFloors: int
    Log_Surface: float
    PropertyGFATotal: float
    LargestPropertyUseTypeGFA: float
    PropertyGFABuilding_s: float
    BuildingType: str
    PrimaryPropertyType: str
    City: str
    State: str


class PredictionResponse(BaseModel):

    prediction: float