import ee, json, os
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
GEE_SERVICE_KEY = json.loads(os.getenv('GEE_SERVICE_KEY'))
from google.oauth2 import service_account

class EarthEngineService:
    # Class-level flag to track initialization across instantiations
    _is_initialized = False

    def __init__(self):
        if not EarthEngineService._is_initialized:
            try:
                # 1. Construct OAuth2 credentials from the parsed JSON dictionary
                credentials = service_account.Credentials.from_service_account_info(
                    GEE_SERVICE_KEY,
                    scopes=['https://www.googleapis.com/auth/earthengine']
                )

                # 2. Initialize Earth Engine with explicit credentials and project ID
                ee.Initialize(
                    credentials=credentials,
                    project=GEE_SERVICE_KEY.get('project_id')
                )
                EarthEngineService._is_initialized = True
            except Exception as e:
                print(f"GEE Initialization failed: {e}")
                # Terminate explicitly to prevent downstream cascading failures
                raise RuntimeError(f"Failed to initialize Earth Engine API: {e}")

    def fetch_data(self, dataset_id: str, cleaned_data: dict) -> dict:
        if dataset_id == "sentinel-5p":
            return self._process_sentinel_5p(cleaned_data)
        elif dataset_id == "hansen-global-forest-change":
            return self._process_hansen(cleaned_data)
        elif dataset_id == "modis-land-surface-temp":
            return self._process_modis(cleaned_data)
        elif dataset_id == "jrc-global-surface-water":
            return self._process_jrc(cleaned_data)
        raise NotImplementedError("Dataset extraction protocol not defined.")

    def _process_sentinel_5p(self, params: dict) -> dict:
        variable = params.get("variable", "L3_NO2")
        start = params.get("start_date", "2024-01-01")
        end = params.get("end_date", "2024-01-31")

        band_mapping = {
            "L3_NO2": ("tropospheric_NO2_column_number_density", 0, 0.0002,
                       ['black', 'blue', 'purple', 'cyan', 'green', 'yellow', 'red']),
            "L3_CO": ("CO_column_number_density", 0, 0.05,
                      ['black', 'blue', 'purple', 'cyan', 'green', 'yellow', 'red']),
            "L3_O3": ("O3_column_number_density", 0.1, 0.2,
                      ['black', 'blue', 'purple', 'cyan', 'green', 'yellow', 'red']),
            "L3_SO2": ("SO2_column_number_density", 0, 0.0005,
                       ['black', 'blue', 'purple', 'cyan', 'green', 'yellow', 'red'])
        }

        band_name, min_val, max_val, palette = band_mapping[variable]

        # Fetch collection, filter, and execute temporal mean reducer
        collection = ee.ImageCollection(f"COPERNICUS/S5P/OFFL/{variable}") \
            .select(band_name) \
            .filterDate(start, end)

        composite = collection.mean()

        vis_params = {
            'min': min_val,
            'max': max_val,
            'palette': palette
        }

        # Request raster tile URL from GEE servers
        map_id_dict = ee.Image(composite).getMapId(vis_params)

        return {
            'tile_url': map_id_dict['tile_fetcher'].url_format,
            'center_lat': 20.0,
            'center_lon': 0.0,
            'zoom': 3
        }

    def _process_hansen(self, params: dict) -> dict:
        variable = params.get("variable", "treecover2000")
        image = ee.Image("UMD/hansen/global_forest_change_2023_v1_11")

        band_mapping = {
            "treecover2000": (0, 100, ['black', 'green']),
            "loss": (0, 1, ['black', 'red']),
            "gain": (0, 1, ['black', 'blue'])
        }

        min_val, max_val, palette = band_mapping[variable]
        selected_band = image.select(variable)

        # Mask out zero values for transparent overlay visualization
        masked_band = selected_band.updateMask(selected_band.gt(0))

        vis_params = {'min': min_val, 'max': max_val, 'palette': palette}
        map_id_dict = ee.Image(masked_band).getMapId(vis_params)

        return {'tile_url': map_id_dict['tile_fetcher'].url_format, 'center_lat': 0.0, 'center_lon': 0.0, 'zoom': 2}

    def _process_modis(self, params: dict) -> dict:
        variable = params.get("variable", "LST_Day_1km")
        start = params.get("start_date", "2024-01-01")
        end = params.get("end_date", "2024-01-31")

        collection = ee.ImageCollection("MODIS/061/MOD11A1") \
            .select(variable) \
            .filterDate(start, end)

        # Apply scalar (0.02) and convert Kelvin to Celsius
        composite = collection.mean().multiply(0.02).subtract(273.15)

        vis_params = {
            'min': -10.0,
            'max': 50.0,
            'palette': ['blue', 'cyan', 'green', 'yellow', 'red']
        }

        map_id_dict = ee.Image(composite).getMapId(vis_params)

        return {'tile_url': map_id_dict['tile_fetcher'].url_format, 'center_lat': 20.0, 'center_lon': 0.0, 'zoom': 3}

    def _process_jrc(self, params: dict) -> dict:
        variable = params.get("variable", "occurrence")
        image = ee.Image("JRC/GSW1_4/GlobalSurfaceWater")

        band_mapping = {
            "occurrence": (0, 100, ['ffffff', 'ffbbbb', '0000ff']),
            "seasonality": (1, 12, ['ffffff', '0000ff']),
            "change_abs": (-100, 100, ['red', 'white', 'blue'])
        }

        min_val, max_val, palette = band_mapping[variable]
        selected_band = image.select(variable)

        # Isolate relevant water data by masking empty terrain
        if variable == "occurrence":
            masked_band = selected_band.updateMask(selected_band.gt(0))
        else:
            masked_band = selected_band

        vis_params = {'min': min_val, 'max': max_val, 'palette': palette}
        map_id_dict = ee.Image(masked_band).getMapId(vis_params)

        return {'tile_url': map_id_dict['tile_fetcher'].url_format, 'center_lat': 20.0, 'center_lon': 0.0, 'zoom': 3}