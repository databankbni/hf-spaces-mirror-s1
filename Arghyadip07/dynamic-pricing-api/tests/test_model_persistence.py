import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from src.features.data_generation import generate_market_data
from src.features.pipeline import run_feature_pipeline
from src.models.demand import (
    FEATURE_COLUMNS,
    build_feature_row,
    load_model_artifact,
    train_and_save_model_artifact,
)


class TestModelPersistence(unittest.TestCase):
    def test_save_and_load_model_artifact_keeps_predictions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            raw_path = tmp_path / "market_data.csv"
            processed_path = tmp_path / "clean_market_data.csv"
            artifact_path = tmp_path / "demand_model.joblib"

            raw_df = generate_market_data(n_samples=350, seed=42)
            raw_df.to_csv(raw_path, index=False)
            processed_df = run_feature_pipeline(
                input_path=str(raw_path),
                output_path=str(processed_path),
            )

            model, reference_row, _ = train_and_save_model_artifact(
                data_path=str(processed_path),
                artifact_path=str(artifact_path),
            )

            loaded_model, loaded_reference_row = load_model_artifact(str(artifact_path))
            self.assertIsNotNone(loaded_model)
            self.assertIsNotNone(loaded_reference_row)
            loaded_model = cast(Any, loaded_model)
            loaded_reference_row = cast(pd.Series, loaded_reference_row)

            sample = processed_df.iloc[10]
            X = build_feature_row(
                price=float(sample["price"]),
                competitor_price=float(sample["competitor_price"]),
                inventory=int(sample["inventory"]),
                day_of_week=int(sample["day_of_week"]),
                reference_row=reference_row,
            )
            X_loaded = build_feature_row(
                price=float(sample["price"]),
                competitor_price=float(sample["competitor_price"]),
                inventory=int(sample["inventory"]),
                day_of_week=int(sample["day_of_week"]),
                reference_row=loaded_reference_row,
            )

            original_pred = float(model.predict(X)[0])
            loaded_pred = float(loaded_model.predict(X_loaded)[0])

            self.assertEqual(list(X.columns), FEATURE_COLUMNS)
            np.testing.assert_allclose(original_pred, loaded_pred, rtol=1e-10, atol=1e-10)


if __name__ == "__main__":
    unittest.main()
