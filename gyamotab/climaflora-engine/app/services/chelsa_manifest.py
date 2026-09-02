from typing import Any

BASES = [
    "https://os.zhdk.cloud.switch.ch/envicloud/chelsa/chelsa_V2/GLOBAL/climatologies",
    "https://os.zhdk.cloud.switch.ch/chelsav2/GLOBAL/climatologies",
]
BASE = BASES[0]
MODELS = ["GFDL-ESM4", "IPSL-CM6A-LR", "MPI-ESM1-2-HR"]
VARIABLES = {
    "bio01": ("bio1", "°C"),
    "bio05": ("bio5", "°C"),
    "bio06": ("bio6", "°C"),
    "bio12": ("bio12", "kg m-2 year-1"),
    "bio15": ("bio15", "coefficient of variation"),
}
PERIODS = {
    "NOW": "1981-2010",
    "2035": "2011-2040",
    "2050": "2041-2070",
    "2070": "2041-2070",
    "2100": "2071-2100",
}
SCENARIOS = {"LOW": "ssp126", "MEDIUM": "ssp370", "HIGH": "ssp585"}


def _baseline_spec(source_name: str, unit: str) -> dict[str, Any]:
    url = f"{BASE}/1981-2010/bio/CHELSA_{source_name}_1981-2010_V.2.1.tif"
    return {
        "path": url,
        "fallback_paths": [f"{base}/1981-2010/bio/CHELSA_{source_name}_1981-2010_V.2.1.tif" for base in BASES[1:]],
        "unit": unit, "use_raster_metadata": True, "decimals": 3,
    }


def _future_spec(period: str, model: str, scenario: str, source_name: str, unit: str) -> dict[str, Any]:
    file_name = f"CHELSA_{source_name}_{period}_{model.lower()}_{scenario}_V.2.1.tif"
    url = f"{BASE}/{period}/{model}/{scenario}/bio/{file_name}"
    return {
        "path": url,
        "fallback_paths": [f"{base}/{period}/{model}/{scenario}/bio/{file_name}" for base in BASES[1:]],
        "unit": unit, "use_raster_metadata": True, "decimals": 3,
    }


def production_manifest() -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for horizon, period in PERIODS.items():
        profiles[horizon] = {}
        for scenario_name, ssp in SCENARIOS.items():
            if horizon == "NOW":
                variables = {key: _baseline_spec(src, unit) for key, (src, unit) in VARIABLES.items()}
                profiles[horizon][scenario_name] = {
                    "scenario": "observation",
                    "period": period,
                    "model": "CHELSA 1981-2010",
                    "variables": variables,
                }
            else:
                members = []
                for model in MODELS:
                    variables = {
                        key: _future_spec(period, model, ssp, src, unit)
                        for key, (src, unit) in VARIABLES.items()
                    }
                    members.append({"model": model, "variables": variables})
                profiles[horizon][scenario_name] = {
                    "scenario": ssp,
                    "period": period,
                    "model": f"median of {len(MODELS)} CHELSA CMIP6 GCMs",
                    "members": members,
                }
    return {
        "dataset": "CHELSA-bioclim",
        "version": "2.1",
        "license": "CC0-1.0",
        "revision": "climaflora-prod-0.6.0",
        "source": "https://www.chelsa-climate.org/datasets/chelsa_bioclim",
        "models": MODELS,
        "profiles": profiles,
    }
