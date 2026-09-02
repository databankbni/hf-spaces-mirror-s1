from datasets import load_dataset
import pandas as pd


class HuggingFaceService:
    def __init__(self):
        # Cache the dataframe locally to prevent re-downloading the dataset on every query
        self.df = None

    def fetch_data(self, dataset_id: str, cleaned_data: dict) -> list:
        if dataset_id == "climate-fever":
            return self._process_climate_fever(cleaned_data)
        raise NotImplementedError("Dataset extraction protocol not defined.")

    def _process_climate_fever(self, params: dict) -> list:
        try:
            if self.df is None:
                # Use the canonical dataset namespace and the correct "test" split
                dataset = load_dataset("tdiggelm/climate_fever", split="test")
                self.df = dataset.to_pandas()

            label_filter = params.get("claim_label", "ALL")
            try:
                limit = int(params.get("num_records", 10))
            except ValueError:
                limit = 10

            filtered_df = self.df

            # Filter the Pandas Dataframe based on label
            if label_filter != "ALL" and 'claim_label' in filtered_df.columns:
                filtered_df = filtered_df[filtered_df['claim_label'].astype(str) == label_filter]

            if filtered_df.empty:
                return [{"Status": "No claims match the selected criteria."}]

            # Select specific columns to keep the tabular output clean
            cols_to_show = ['claim_id', 'claim', 'claim_label']
            actual_cols = [c for c in cols_to_show if c in filtered_df.columns]

            if not actual_cols:
                actual_cols = list(filtered_df.columns)[:3]

            display_df = filtered_df[actual_cols].head(limit).fillna("N/A").astype(str)
            return display_df.to_dict(orient='records')

        except Exception as e:
            return [{"Processing Error": str(e)}]