import pandas as pd


class OWIDService:
    def __init__(self):
        # We cache the dataframe on the class instance to avoid downloading the large CSV repeatedly on the same server instance
        self.df = None
        self.url = 'https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv'

    def fetch_data(self, dataset_id: str, cleaned_data: dict) -> list:
        if dataset_id == "co2-data":
            return self._process_co2(cleaned_data)
        raise NotImplementedError("Dataset extraction protocol not defined.")

    def _process_co2(self, params: dict) -> list:
        try:
            if self.df is None:
                self.df = pd.read_csv(self.url)

            country = params.get("country", "World")
            try:
                start_year = int(params.get("start_year", 2000))
                end_year = int(params.get("end_year", 2022))
            except ValueError:
                start_year, end_year = 2000, 2022

            # Filter the dataframe
            filtered_df = self.df[
                (self.df['country'] == country) &
                (self.df['year'] >= start_year) &
                (self.df['year'] <= end_year)
                ]

            if filtered_df.empty:
                return [{"Status": "No data found for the selected region and time frame."}]

            # Select the most relevant columns to keep the UI clean (OWID has 70+ columns)
            cols = ['country', 'year', 'co2', 'co2_per_capita', 'cumulative_co2', 'coal_co2', 'oil_co2', 'gas_co2']
            available_cols = [c for c in cols if c in filtered_df.columns]

            # Format and convert to dictionary
            display_df = filtered_df[available_cols].fillna("N/A").astype(str)
            return display_df.to_dict(orient='records')

        except Exception as e:
            return [{"Processing Error": str(e)}]