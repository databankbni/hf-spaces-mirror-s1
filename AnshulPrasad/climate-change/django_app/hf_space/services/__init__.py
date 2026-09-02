from .copernicus import CopernicusService
from .earth_engine import EarthEngineService
from .hugging_face import HuggingFaceService
from .nasa import NASAService
from .noaa import NOAAService
from .owid import OWIDService
from .world_bank import WorldBankService

# Registry mapping URL parameters to handler instances
SERVICE_REGISTRY = {
    "copernicus": CopernicusService(),
    "earth_engine": EarthEngineService(),
    "hugging_face": HuggingFaceService(),
    "nasa": NASAService(),
    "noaa": NOAAService(),
    "owid": OWIDService(),
    "world_bank": WorldBankService(),
}


def fetch_climate_data(config_data: dict) -> dict:
    source_key = config_data.get("source", "").lower()

    service_handler = SERVICE_REGISTRY.get(source_key)
    if not service_handler:
        raise ValueError(f"Unsupported data source: '{source_key}'")

    return service_handler.fetch_data(config_data)