from dataclasses import dataclass
from pathlib import Path
import tomllib
import os

DEFAULT_API_BASE_URL = "https://Arghyadip07-dynamic-pricing-api.hf.space"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_toml_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


@dataclass
class Settings:
    project_root: Path = Path(__file__).resolve().parents[2]
    raw_data_path: Path = Path("data/raw/market_data.csv")
    processed_data_path: Path = Path("data/processed/super_model_data_clean.csv")
    model_artifact_path: Path = Path("artifacts/demand_model.joblib")
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = False
    dashboard_port: int = 8501
    dashboard_headless: bool = True
    dashboard_api_base_url: str = DEFAULT_API_BASE_URL
    dashboard_pricing_endpoint: str = "/calculate_optimal_price"
    sqlite_db_path: str | None = None
    model_random_seed: int = 42
    model_test_size: float = 0.2
    xgb_n_estimators: int = 1000
    xgb_learning_rate: float = 0.05
    xgb_max_depth: int = 8
    xgb_subsample: float = 0.9
    xgb_colsample_bytree: float = 0.9

    @property
    def raw_data_abspath(self) -> Path:
        return self.project_root / self.raw_data_path

    @property
    def processed_data_abspath(self) -> Path:
        return self.project_root / self.processed_data_path

    @property
    def model_artifact_abspath(self) -> Path:
        return self.project_root / self.model_artifact_path


def _build_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    _load_env_file(project_root / ".env")

    config_dir = project_root / "config"

    app_cfg = _load_toml_file(config_dir / "app.toml")
    api_cfg = _load_toml_file(config_dir / "api.toml")
    dashboard_cfg = _load_toml_file(config_dir / "dashboard.toml")
    model_cfg = _load_toml_file(config_dir / "model.toml")

    paths_cfg = app_cfg.get("paths", {})
    api_server_cfg = api_cfg.get("server", {})
    dashboard_server_cfg = dashboard_cfg.get("server", {})
    dashboard_api_cfg = dashboard_cfg.get("api", {})
    training_cfg = model_cfg.get("training", {})
    xgb_cfg = model_cfg.get("xgboost", {})

    # Environment variables take precedence over config files
    api_host = os.getenv("API_HOST") or str(api_server_cfg.get("host", "0.0.0.0"))
    api_port = int(os.getenv("API_PORT") or os.getenv("PORT") or api_server_cfg.get("port", 8000))
    api_reload_env = os.getenv("API_RELOAD")
    api_reload = (
        api_reload_env.lower() == "true"
        if api_reload_env is not None
        else bool(api_server_cfg.get("reload", False))
    )
    dashboard_port = int(os.getenv("STREAMLIT_SERVER_PORT") or dashboard_server_cfg.get("port", 8501))
    dashboard_api_url = os.getenv("DASHBOARD_API_URL") or str(
        dashboard_api_cfg.get("base_url", DEFAULT_API_BASE_URL)
    )

    return Settings(
        project_root=project_root,
        raw_data_path=Path(paths_cfg.get("raw_data", "data/raw/market_data.csv")),
        processed_data_path=Path(paths_cfg.get("processed_data", "data/processed/super_model_data_clean.csv")),
        model_artifact_path=Path(paths_cfg.get("model_artifact", "artifacts/demand_model.joblib")),
        api_host=api_host,
        api_port=api_port,
        api_reload=api_reload,
        dashboard_port=dashboard_port,
        dashboard_headless=bool(dashboard_server_cfg.get("headless", True)),
        dashboard_api_base_url=dashboard_api_url,
        dashboard_pricing_endpoint=str(
            dashboard_api_cfg.get("pricing_endpoint", "/calculate_optimal_price")
        ),
        model_random_seed=int(training_cfg.get("random_seed", 42)),
        model_test_size=float(training_cfg.get("test_size", 0.2)),
        xgb_n_estimators=int(xgb_cfg.get("n_estimators", 1000)),
        xgb_learning_rate=float(xgb_cfg.get("learning_rate", 0.05)),
        xgb_max_depth=int(xgb_cfg.get("max_depth", 8)),
        xgb_subsample=float(xgb_cfg.get("subsample", 0.9)),
        xgb_colsample_bytree=float(xgb_cfg.get("colsample_bytree", 0.9)),
        sqlite_db_path=str(paths_cfg.get("sqlite_db", "data/dpai.sqlite")),
    )


settings = _build_settings()
