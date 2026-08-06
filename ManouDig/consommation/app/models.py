from sqlalchemy import (
    Column,
    Integer,
    Float,
    String,
    DateTime,
    ForeignKey
)

from app.database import Base


# ===================================================
# Table : predictions
# ===================================================

class Prediction(Base):
    __tablename__ = "predictions"

    prediction_id = Column(Integer, primary_key=True, index=True)

    YearBuilt = Column("yearbuilt", Integer)
    BuildingAge = Column("buildingage", Integer)
    NumberofFloors = Column("numberoffloors", Float)
    Log_Surface = Column("log_surface", Float)
    PropertyGFATotal = Column("propertygfatotal", Float)
    LargestPropertyUseTypeGFA = Column(
        "largestpropertyusetypegfa",
        Float
    )
    PropertyGFABuilding_s = Column(
        "propertygfabuilding_s",
        Float
    )

    BuildingType = Column("buildingtype", String)
    PrimaryPropertyType = Column(
        "primarypropertytype",
        String
    )
    City = Column("city", String)
    State = Column("state", String)

    prediction_kbtu = Column(
        "prediction_kbtu",
        Float
    )

    created_at = Column(
        "created_at",
        DateTime
    )


# ===================================================
# Table : monitoring
# ===================================================

class Monitoring(Base):
    __tablename__ = "monitoring"

    monitoring_id = Column(
        "monitoring_id",
        Integer,
        primary_key=True
    )

    prediction_id = Column(
        "prediction_id",
        Integer,
        ForeignKey("predictions.prediction_id")
    )

    response_time_ms = Column(
        "response_time_ms",
        Float
    )

    model_version = Column(
        "model_version",
        String
    )

    status = Column(
        "status",
        String
    )

    created_at = Column(
        "created_at",
        DateTime
    )


# ===================================================
# Table : dataset
# ===================================================

class Dataset(Base):
    __tablename__ = "dataset"

    dataset_id = Column(
        "dataset_id",
        Integer,
        primary_key=True,
        index=True
    )

    YearBuilt = Column(
        "yearbuilt",
        Integer
    )

    BuildingAge = Column(
        "buildingage",
        Integer
    )

    NumberofFloors = Column(
        "numberoffloors",
        Float
    )

    Log_Surface = Column(
        "log_surface",
        Float
    )

    PropertyGFATotal = Column(
        "propertygfatotal",
        Float
    )

    LargestPropertyUseTypeGFA = Column(
        "largestpropertyusetypegfa",
        Float
    )

    PropertyGFABuilding_s = Column(
        "propertygfabuilding_s",
        Float
    )

    BuildingType = Column(
        "buildingtype",
        String
    )

    PrimaryPropertyType = Column(
        "primarypropertytype",
        String
    )

    City = Column(
        "city",
        String
    )

    State = Column(
        "state",
        String
    )

    SiteEnergyUse_kBtu = Column(
        "siteenergyuse_kbtu",
        Float
    )