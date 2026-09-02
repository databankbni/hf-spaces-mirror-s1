import requests
import os
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


class NOAAService:
    def __init__(self):
        self.token = os.getenv("NOAA_TOKEN")
        self.endpoint = "https://www.ncei.noaa.gov/cdo-web/api/v2/data"

    def fetch_data(self, dataset_id: str, cleaned_data: dict) -> list:
        if dataset_id == "cdo-gsom":
            return self._process_gsom(cleaned_data)
        raise NotImplementedError("Dataset extraction protocol not defined.")

    def _process_gsom(self, params: dict) -> list:
        if not self.token:
            return [{"Error": "NOAA API token missing. Verify environment configurations."}]

        headers = {"token": self.token}
        api_params = {
            "datasetid": "GSOM",
            "stationid": params.get("station_id", "GHCND:USW00023234"),
            "startdate": params.get("start_date", "2023-01-01"),
            "enddate": params.get("end_date", "2023-12-31"),
            "datatypeid": params.get("datatype", "TMAX"),
            "limit": 1000,
        }

        try:
            response = requests.get(self.endpoint, headers=headers, params=api_params)

            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                if not results:
                    return [{"Status": "No records retrieved for the specified parameters."}]

                # Format to a clean tabular dictionary
                formatted_results = []
                for item in results:
                    formatted_results.append({
                        "Date": item.get("date", "").split("T")[0],
                        "Station": item.get("station"),
                        "Data Type": item.get("datatype"),
                        "Value": item.get("value"),
                        "Attributes": item.get("attributes")
                    })
                return formatted_results
            else:
                return [{"HTTP Error": f"{response.status_code} - {response.text}"}]

        except Exception as e:
            return [{"Processing Error": str(e)}]