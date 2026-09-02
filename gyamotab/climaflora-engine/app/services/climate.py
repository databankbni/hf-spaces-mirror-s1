import json
import math
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.domain.models import ClimateProfile, ClimateUncertainty, Horizon, Scenario


class ClimateProvider(ABC):
    @abstractmethod
    def profile(
        self,
        latitude: float,
        longitude: float,
        horizon: Horizon,
        scenario: Scenario,
    ) -> ClimateProfile:
        raise NotImplementedError

    def readiness(self) -> dict[str, Any]:
        return {"ready": True, "provider": self.__class__.__name__}


class ChelsaCogProvider(ClimateProvider):
    REQUIRED_VARIABLES = {"bio01", "bio05", "bio06", "bio12", "bio15"}
    EXPECTED_SCENARIOS = {
        Scenario.LOW: "ssp126",
        Scenario.MEDIUM: "ssp370",
        Scenario.HIGH: "ssp585",
    }
    """Samples CHELSA COGs declared in an explicit, versioned manifest.

    Variable specs support `path`, `scale`, `offset`, `unit` and `decimals`. This is
    intentional: source raster units must never be guessed by the application.
    """

    def __init__(self, manifest_path: str):
        path = Path(manifest_path)
        if not path.exists():
            raise RuntimeError(f"CHELSA manifest not found: {manifest_path}")
        self.manifest_path = path
        self.manifest = json.loads(path.read_text(encoding="utf-8"))
        self._validate_manifest()

    def _validate_manifest(self) -> None:
        if not isinstance(self.manifest.get("profiles"), dict):
            raise RuntimeError("Invalid CHELSA manifest: missing profiles")
        for horizon in Horizon:
            if horizon.value not in self.manifest["profiles"]:
                raise RuntimeError(f"Invalid CHELSA manifest: missing horizon {horizon.value}")

    @staticmethod
    def _sample(spec: dict[str, Any], longitude: float, latitude: float) -> float | None:
        import rasterio
        from rasterio.warp import transform

        primary = spec.get("path")
        candidates = ([primary] if primary else []) + list(spec.get("fallback_paths") or [])
        if not candidates:
            return None

        errors: list[str] = []
        for path in candidates:
            try:
                with rasterio.Env(
                    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                    GDAL_HTTP_MULTIRANGE="YES",
                    GDAL_HTTP_TIMEOUT="20",
                ):
                    with rasterio.open(path) as src:
                        x, y = longitude, latitude
                        if src.crs and str(src.crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
                            xs, ys = transform("EPSG:4326", src.crs, [longitude], [latitude])
                            x, y = xs[0], ys[0]
                        sampled = next(src.sample([(x, y)], masked=True))[0]
                        if getattr(sampled, "mask", False) is not False and bool(sampled.mask):
                            return None
                        try:
                            raw = float(sampled)
                        except (TypeError, ValueError):
                            return None
                        if not math.isfinite(raw):
                            return None
                        if spec.get("use_raster_metadata", False):
                            scale = float((src.scales or [1.0])[0])
                            offset = float((src.offsets or [0.0])[0])
                        else:
                            scale = float(spec.get("scale", 1.0))
                            offset = float(spec.get("offset", 0.0))
                        value = raw * scale + offset
                        decimals = spec.get("decimals")
                        return round(value, int(decimals)) if decimals is not None else value
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path} -> {type(exc).__name__}: {exc}")

        raise RuntimeError("CHELSA COG unavailable; attempted: " + " | ".join(errors))

    @staticmethod
    def _sample_many(
        spec: dict[str, Any],
        coordinates: list[tuple[float, float]],
    ) -> list[float | None]:
        import rasterio
        from rasterio.warp import transform

        primary = spec.get("path")
        candidates = ([primary] if primary else []) + list(spec.get("fallback_paths") or [])
        if not candidates:
            return [None for _ in coordinates]

        errors: list[str] = []
        for path in candidates:
            try:
                with rasterio.Env(
                    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                    GDAL_HTTP_MULTIRANGE="YES",
                    GDAL_HTTP_TIMEOUT="30",
                ):
                    with rasterio.open(path) as src:
                        coords = coordinates
                        if src.crs and str(src.crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
                            xs, ys = transform(
                                "EPSG:4326",
                                src.crs,
                                [c[0] for c in coordinates],
                                [c[1] for c in coordinates],
                            )
                            coords = list(zip(xs, ys))
                        order = sorted(range(len(coords)), key=lambda i: (coords[i][1], coords[i][0]))
                        sorted_coords = [coords[i] for i in order]
                        raw_samples = list(src.sample(sorted_coords, masked=True))
                        output: list[float | None] = [None] * len(coords)
                        for pos, sample in zip(order, raw_samples, strict=True):
                            value0 = sample[0]
                            if getattr(value0, "mask", False) is not False and bool(value0.mask):
                                continue
                            try:
                                raw = float(value0)
                            except (TypeError, ValueError):
                                continue
                            if not math.isfinite(raw):
                                continue
                            if spec.get("use_raster_metadata", False):
                                scale = float((src.scales or [1.0])[0])
                                offset = float((src.offsets or [0.0])[0])
                            else:
                                scale = float(spec.get("scale", 1.0))
                                offset = float(spec.get("offset", 0.0))
                            value = raw * scale + offset
                            decimals = spec.get("decimals")
                            output[pos] = round(value, int(decimals)) if decimals is not None else value
                        return output
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path} -> {type(exc).__name__}: {exc}")
        raise RuntimeError("CHELSA COG unavailable for batch sample; attempted: " + " | ".join(errors))

    def sample_many_profile(
        self,
        coordinates: list[tuple[float, float]],
        horizon: Horizon,
        scenario: Scenario,
    ) -> dict[str, list[float | None]]:
        try:
            node = self.manifest["profiles"][horizon.value][scenario.value]
        except KeyError as exc:
            raise ValueError(
                f"No CHELSA profile for horizon={horizon.value}, scenario={scenario.value}"
            ) from exc
        if node.get("members"):
            raise ValueError("Batch regional envelope sampling currently requires a single profile, not an ensemble")
        return {
            name: self._sample_many(spec, coordinates)
            for name, spec in node.get("variables", {}).items()
        }

    @lru_cache(maxsize=2048)
    def profile(
        self,
        latitude: float,
        longitude: float,
        horizon: Horizon,
        scenario: Scenario,
    ) -> ClimateProfile:
        try:
            node = self.manifest["profiles"][horizon.value][scenario.value]
        except KeyError as exc:
            raise ValueError(
                f"No CHELSA profile for horizon={horizon.value}, scenario={scenario.value}"
            ) from exc

        members = node.get("members") or []
        uncertainty = {}
        member_names = []
        if members:
            import numpy as np

            all_variables = sorted({name for member in members for name in member.get("variables", {})})
            variables = {}
            variable_meta = {}
            samples_by_variable: dict[str, list[tuple[int, float]]] = {
                name: [] for name in all_variables
            }
            tasks: list[tuple[str, int, dict[str, Any]]] = []
            for variable in all_variables:
                for member_index, member in enumerate(members):
                    spec = member.get("variables", {}).get(variable)
                    if not spec:
                        continue
                    variable_meta.setdefault(
                        variable,
                        {
                            "unit": spec.get("unit"),
                            "transform": (
                                "raster_metadata"
                                if spec.get("use_raster_metadata", False)
                                else "manifest_scale_offset"
                            ),
                            "declared_scale": spec.get("scale"),
                            "declared_offset": spec.get("offset"),
                        },
                    )
                    tasks.append((variable, member_index, spec))

            with ThreadPoolExecutor(
                max_workers=min(5, max(1, len(tasks))),
                thread_name_prefix="chelsa-point",
            ) as executor:
                futures = {
                    executor.submit(self._sample, spec, longitude, latitude): (
                        variable,
                        member_index,
                    )
                    for variable, member_index, spec in tasks
                }
                for future in as_completed(futures):
                    variable, member_index = futures[future]
                    sampled = future.result()
                    if sampled is not None:
                        samples_by_variable[variable].append((member_index, float(sampled)))

            for variable in all_variables:
                values = [value for _, value in sorted(samples_by_variable[variable])]
                if values:
                    array = np.asarray(values, dtype=float)
                    variables[variable] = round(float(np.median(array)), 4)
                    uncertainty[variable] = ClimateUncertainty(
                        n=len(values),
                        minimum=float(np.min(array)),
                        p10=float(np.quantile(array, 0.10)),
                        p50=float(np.quantile(array, 0.50)),
                        p90=float(np.quantile(array, 0.90)),
                        maximum=float(np.max(array)),
                    )
                else:
                    variables[variable] = None
            member_names = [member.get("model", "UNKNOWN") for member in members]
            model_name = node.get("model") or f"ensemble-median-{len(members)}-members"
            method = "parallel point sample per declared COG member; median used as central climate profile"
        else:
            variable_specs = list(node.get("variables", {}).items())
            variables = {name: None for name, _ in variable_specs}
            with ThreadPoolExecutor(
                max_workers=min(5, max(1, len(variable_specs))),
                thread_name_prefix="chelsa-point",
            ) as executor:
                futures = {
                    executor.submit(self._sample, spec, longitude, latitude): name
                    for name, spec in variable_specs
                }
                for future in as_completed(futures):
                    variables[futures[future]] = future.result()
            variable_meta = {
                name: {
                    "unit": spec.get("unit"),
                    "transform": (
                        "raster_metadata"
                        if spec.get("use_raster_metadata", False)
                        else "manifest_scale_offset"
                    ),
                    "declared_scale": spec.get("scale"),
                    "declared_offset": spec.get("offset"),
                }
                for name, spec in variable_specs
            }
            model_name = node.get("model")
            method = "parallel point sample from declared COG layers with explicit scale/offset transforms"

        return ClimateProfile(
            latitude=latitude,
            longitude=longitude,
            horizon=horizon,
            scenario=scenario,
            provider="CHELSA",
            model=model_name,
            period=node["period"],
            variables=variables,
            uncertainty=uncertainty,
            provenance={
                "dataset": self.manifest.get("dataset", "CHELSA-bioclim"),
                "version": self.manifest.get("version", "2.1"),
                "license": self.manifest.get("license", "CC0-1.0"),
                "method": method,
                "manifest_revision": self.manifest.get("revision"),
                "scenario_mapping": node.get("scenario"),
                "variable_meta": variable_meta,
                "ensemble_members": member_names,
            },
        )

    def readiness(self) -> dict[str, Any]:
        missing = []
        warnings = []
        variables = 0
        profiles = self.manifest.get("profiles", {})
        for horizon in Horizon:
            scenarios = profiles.get(horizon.value, {})
            for scenario in Scenario:
                node = scenarios.get(scenario.value)
                prefix_base = f"{horizon.value}/{scenario.value}"
                if not node:
                    missing.append(f"{prefix_base}:profile")
                    continue
                expected_scenario = (
                    "observation" if horizon == Horizon.NOW else self.EXPECTED_SCENARIOS[scenario]
                )
                if node.get("scenario") != expected_scenario:
                    missing.append(f"{prefix_base}:scenario_expected_{expected_scenario}")
                period = str(node.get("period", ""))
                if not period or "DECLARE_" in period or "REPLACE_" in period:
                    missing.append(f"{prefix_base}:period")
                groups = node.get("members") or [
                    {"model": node.get("model"), "variables": node.get("variables", {})}
                ]
                available = set()
                for member_index, member in enumerate(groups):
                    member_variables = member.get("variables", {})
                    available.update(member_variables.keys())
                    for variable in sorted(self.REQUIRED_VARIABLES - set(member_variables)):
                        missing.append(f"{prefix_base}/member{member_index}:{variable}")
                    for variable, spec in member_variables.items():
                        variables += 1
                        path = spec.get("path")
                        prefix = f"{prefix_base}/member{member_index}/{variable}"
                        if not spec.get("unit"):
                            missing.append(f"{prefix}:unit")
                        if not path:
                            missing.append(f"{prefix}:path")
                        elif not (
                            str(path).startswith(("http://", "https://", "/vsicurl/", "s3://"))
                            or Path(path).exists()
                        ):
                            missing.append(f"{prefix}:{path}")
                for variable in sorted(self.REQUIRED_VARIABLES - available):
                    missing.append(f"{prefix_base}:{variable}")
                if horizon != Horizon.NOW and node.get("members") and len(node["members"]) < 3:
                    warnings.append(f"{prefix_base}:ensemble_has_fewer_than_3_members")
        return {
            "ready": variables > 0 and not missing,
            "provider": "CHELSA",
            "manifest": str(self.manifest_path),
            "declared_layers": variables,
            "missing": missing[:50],
            "warnings": warnings[:25],
        }


@lru_cache(maxsize=8)
def make_climate_provider(provider_name: str, manifest_path: str) -> ClimateProvider:
    if provider_name.lower() == "chelsa":
        return ChelsaCogProvider(manifest_path)
    raise ValueError(f"Unsupported climate provider: {provider_name}")
