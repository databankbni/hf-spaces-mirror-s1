import earthaccess
import xarray as xr
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

class NASAService:
    _is_authenticated = False

    def __init__(self):
        # Authenticate once per application lifecycle
        if not NASAService._is_authenticated:
            try:
                # Expects EARTHDATA_USERNAME and EARTHDATA_PASSWORD in environment
                earthaccess.login(strategy="environment")
                NASAService._is_authenticated = True
            except Exception as e:
                print(f"NASA Earthdata Auth Failed. Ensure ENV vars are set: {e}")

    def fetch_data(self, dataset_id: str, cleaned_data: dict) -> list:
        if dataset_id == "mur-sst":
            return self._process_mur_sst(cleaned_data)
        raise NotImplementedError("Dataset extraction protocol not defined.")

    def _process_mur_sst(self, params: dict) -> list:
        if not self._is_authenticated:
            return [{"Error": "NASA Earthdata authentication failed. Check credentials."}]

        try:
            start_date = params.get("start_date", "2023-01-01")
            end_date = params.get("end_date", "2023-01-02")
            variable = params.get("variable", "analysed_sst")

            # Search NASA catalog
            results = earthaccess.search_data(
                short_name="MUR25-JPL-L4-GLOB-v04.2",
                temporal=(start_date, end_date),
                cloud_hosted=True,
                count=1  # Limit to 1 file for UI performance
            )

            if not results:
                return [{"Error": "No data found for the selected temporal range."}]

            # Open remote files directly into Xarray memory
            files = earthaccess.open(results)
            ds = xr.open_mfdataset(files, engine='h5netcdf', chunks=None)

            # Convert 3D matrix to 2D Tabular format for our UI
            if variable in ds:
                df = ds[variable].to_dataframe().reset_index().dropna().head(100).astype(str)
                return df.to_dict(orient='records')
            else:
                return [{"Error": f"Variable '{variable}' not found in dataset."}]

        except Exception as e:
            return [{"Processing Error": str(e)}]