import cdsapi
from pathlib import Path
import xarray as xr
import zipfile
import tarfile

class CopernicusService:
    def __init__(self):
        self.client = cdsapi.Client()

    def fetch_data(self, dataset_id: str, cleaned_data: dict) -> list:
        # Determine file extension based on user selection
        data_format = cleaned_data.get("format", "grib")
        file_ext = ".nc" if data_format == "netcdf" else ".grib"

        output_path = Path(f"/tmp/{dataset_id}_output{file_ext}")

        if "area" in cleaned_data and isinstance(cleaned_data["area"], str):
            cleaned_data["area"] = [float(x.strip()) for x in cleaned_data["area"].split(",")]

        # CDS API Pre-flight Sanitation
        if dataset_id == "ecv-for-climate-change":
            # Translate standard 'format' to dataset-specific 'data_format'
            if "format" in cleaned_data:
                cleaned_data["data_format"] = cleaned_data.pop("format")

            product_types = cleaned_data.get("product_type", [])
            if isinstance(product_types, str):
                product_types = [product_types]

            # Remove reference period if no anomaly or climatology is requested
            if not any(pt in ["anomaly", "climatology"] for pt in product_types):
                cleaned_data.pop("climate_reference_period", None)

            # Remove specific years if ONLY a climatology is requested
            if product_types == ["climatology"]:
                cleaned_data.pop("year", None)

        # Download the file via CDS API
        self.client.retrieve(dataset_id, cleaned_data, str(output_path))

        # Parse the downloaded binary file into a tabular dictionary
        return self._parse_file_to_table(output_path, data_format)

    def _parse_file_to_table(self, file_path: Path, data_format: str) -> list:
        """Opens the dataset, extracting it first if Copernicus delivered an archive."""
        try:
            # 1. Archive Detection and Extraction
            if zipfile.is_zipfile(file_path):
                extract_dir = file_path.parent / f"{file_path.stem}_extracted"
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
                # Target the first valid data file inside the extracted directory
                extracted_files = [f for f in extract_dir.rglob("*") if f.is_file()]
                if extracted_files:
                    file_path = extracted_files[0]

            elif tarfile.is_tarfile(file_path):
                extract_dir = file_path.parent / f"{file_path.stem}_extracted"
                with tarfile.open(file_path, 'r') as tar_ref:
                    tar_ref.extractall(extract_dir)
                extracted_files = [f for f in extract_dir.rglob("*") if f.is_file()]
                if extracted_files:
                    file_path = extracted_files[0]

            # 2. Xarray Parsing Pipeline
            engine = "netcdf4" if data_format == "netcdf" else "cfgrib"
            ds = xr.open_dataset(file_path, engine=engine)

            # Flatten to tabular dataframe
            df = ds.to_dataframe().reset_index()
            df = df.dropna()

            # Sub-sample for UI performance and stringify
            df_subset = df.head(100).astype(str)

            return df_subset.to_dict(orient='records')

        except Exception as e:
            return [{"Data Processing Error": f"Failed to parse {data_format.upper()} file: {str(e)}"}]