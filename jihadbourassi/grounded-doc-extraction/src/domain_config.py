"""Domain configuration loading.

All domain knowledge — anchor vocabulary, value patterns, wrapper markers,
ranges, spatial tolerances, scoring weights — lives in a JSON file, not in
Python. `expert_extractor.py` contains no domain-specific string or number, so
retargeting the engine at a different corpus is a config change.

Stdlib `json` only: no new dependency, no Space rebuild.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "bgs.json"

REQUIRED_TOP_LEVEL = ("fields", "spatial", "scoring", "tie_margin", "wrapper_markers")
REQUIRED_SPATIAL = (
    "min_y_overlap",
    "min_x_overlap",
    "max_gap_frac_x",
    "max_gap_frac_y",
    "near_frac",
    "row_max_gap_frac_x",
    "row_max_centre_dy_frac",
    "overlap_min_x",
    "overlap_min_y",
    "provenance_neighbour_frac",
    "provenance_max_neighbours",
)
REQUIRED_FIELD_KEYS = ("value_pattern", "anchors", "validation")


class ConfigError(ValueError):
    """Raised when a configuration file is missing or structurally invalid."""


@dataclass(frozen=True)
class DomainConfig:
    """A validated configuration plus its content identity."""

    data: dict[str, Any]
    config_id: str
    source_path: str | None = None

    # --- accessors ---

    @property
    def field_names(self) -> list[str]:
        return list(self.data["fields"].keys())

    def field(self, name: str) -> dict[str, Any]:
        try:
            return self.data["fields"][name]
        except KeyError as exc:
            raise ConfigError(f"no configuration for field {name!r}") from exc

    def spatial(self, key: str) -> float:
        return float(self.data["spatial"][key])

    def scoring(self, key: str, default: float = 0.0) -> Any:
        return self.data["scoring"].get(key, default)

    @property
    def tie_margin(self) -> float:
        return float(self.data["tie_margin"])

    @property
    def wrapper_markers(self) -> list[str]:
        return [str(m).lower() for m in self.data["wrapper_markers"]]


def _validate(data: Any, source: str) -> None:
    if not isinstance(data, dict):
        raise ConfigError(f"{source}: top level must be a JSON object")
    for key in REQUIRED_TOP_LEVEL:
        if key not in data:
            raise ConfigError(f"{source}: missing required key {key!r}")
    if not isinstance(data["fields"], dict) or not data["fields"]:
        raise ConfigError(f"{source}: 'fields' must be a non-empty object")
    for key in REQUIRED_SPATIAL:
        if key not in data["spatial"]:
            raise ConfigError(f"{source}: missing spatial key {key!r}")
    for name, spec in data["fields"].items():
        if not isinstance(spec, dict):
            raise ConfigError(f"{source}: field {name!r} must be an object")
        for key in REQUIRED_FIELD_KEYS:
            if key not in spec:
                raise ConfigError(f"{source}: field {name!r} missing key {key!r}")
        if not isinstance(spec["anchors"], list):
            raise ConfigError(f"{source}: field {name!r} 'anchors' must be a list")
        for anchor in spec["anchors"]:
            if "text" not in anchor or "relations" not in anchor:
                raise ConfigError(
                    f"{source}: field {name!r} has an anchor without 'text'/'relations'"
                )


def load_config_bytes(raw: bytes, source: str = "<bytes>") -> DomainConfig:
    """Parse and validate configuration from raw bytes.

    `config_id` is the SHA-256 of the exact bytes, so a result can always be tied
    to the configuration that produced it.
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{source}: not valid JSON: {exc}") from exc
    _validate(data, source)
    return DomainConfig(
        data=data,
        config_id=hashlib.sha256(raw).hexdigest(),
        source_path=source if source not in ("<bytes>", "<dict>") else None,
    )


def load_config(path: str | Path | None = None) -> DomainConfig:
    """Load configuration from disk (defaults to configs/bgs.json)."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigError(f"no such configuration file: {config_path}")
    return load_config_bytes(config_path.read_bytes(), source=str(config_path))


def config_from_dict(data: dict[str, Any]) -> DomainConfig:
    """Build a config from an in-memory dict (used by tests to vary settings)."""
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return load_config_bytes(raw, source="<dict>")
