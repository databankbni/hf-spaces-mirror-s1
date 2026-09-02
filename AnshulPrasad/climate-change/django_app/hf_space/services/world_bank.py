import requests


class WorldBankService:
    def __init__(self):
        self.base_url = "https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"

    def fetch_data(self, dataset_id: str, cleaned_data: dict) -> list:
        if dataset_id == "wb-climate-data":
            return self._process_indicator(cleaned_data)
        raise NotImplementedError("Dataset extraction protocol not defined.")

    def _process_indicator(self, params: dict) -> list:
        country = params.get("country", "WLD")
        indicator = params.get("indicator", "EN.GHG.CO2.MT.CE.AR5")
        start_year = params.get("start_year", "2000")
        end_year = params.get("end_year", "2022")

        url = self.base_url.format(country=country, indicator=indicator)
        api_params = {
            "format": "json",
            "date": f"{start_year}:{end_year}",
            "per_page": 1000
        }

        try:
            response = requests.get(url, params=api_params)

            if response.status_code == 200:
                data = response.json()

                # World Bank API returns metadata in data[0] and results in data[1]
                if len(data) > 1 and data[1]:
                    records = data[1]
                    formatted_results = []

                    for item in records:
                        formatted_results.append({
                            "Year": item.get("date"),
                            "Country": item.get("country", {}).get("value"),
                            "Indicator": item.get("indicator", {}).get("value"),
                            "Value": item.get("value") if item.get("value") is not None else "N/A"
                        })
                    return formatted_results
                else:
                    return [{"Status": "No data available for the selected parameters."}]
            else:
                return [{"HTTP Error": f"{response.status_code} - {response.text}"}]

        except Exception as e:
            return [{"Processing Error": str(e)}]