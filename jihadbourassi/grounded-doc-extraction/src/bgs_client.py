"""Small BGS/SOBI client for the deployed application.

This module exposes the Phase 1 public-data logic as a reusable Python API.

Responsibilities:
- search the public BGS Onshore Borehole Index;
- keep only records with usable public scan URLs;
- apply the small BH / TP / shaft heuristic when requested;
- download and validate a selected public PDF.

It deliberately contains no Gradio code and no extraction logic.
"""

from __future__ import annotations

import json
import random
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SOBI_ITEMS_URL = (
    "https://ogcapi.bgs.ac.uk/"
    "collections/onshoreboreholeindex/items"
)

SCAN_URL_TEMPLATE = (
    "https://api.bgs.ac.uk/"
    "sobi-scans/v1/borehole/scans/items/{bgs_id}"
)

USER_AGENT = "grounded-doc-extraction-demo"

MAX_DOCUMENTS = 30
ATTEMPT_MULTIPLIER = 4
MIN_SAMPLE_ATTEMPTS = 20
TYPE_WINDOW_SIZE = 20
TYPE_MAX_WINDOWS = 15


class BGSClientError(RuntimeError):
    """A public BGS search/download operation could not be completed."""


def normalise_bgs_id(value: Any) -> str:
    """Return the public BGS id in its canonical integer-string form."""

    if value is None:
        raise ValueError("BGS ID cannot be empty.")

    text = str(value).strip()

    if not text:
        raise ValueError("BGS ID cannot be empty.")

    try:
        return str(int(float(text)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid BGS ID: {value!r}") from exc


def is_usable_scan_url(value: Any) -> bool:
    """Accept only the public BGS SOBI scan endpoint."""

    if not isinstance(value, str):
        return False

    parsed = urllib.parse.urlparse(value.strip())

    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc == "api.bgs.ac.uk"
        and parsed.path.startswith(
            "/sobi-scans/v1/borehole/scans/items/"
        )
    )


def _normalise_record(feature: dict[str, Any]) -> dict[str, Any] | None:
    properties = feature.get("properties", {})

    scan_url = properties.get("scan_url")

    if not is_usable_scan_url(scan_url):
        return None

    bgs_id = properties.get("bgs_id")

    if bgs_id is None:
        return None

    try:
        bgs_id = normalise_bgs_id(bgs_id)
    except ValueError:
        return None

    length = properties.get("length")

    if isinstance(length, (int, float)) and length < 0:
        length = None

    return {
        "bgs_id": bgs_id,
        "reference": properties.get("reference"),
        "name": properties.get("name"),
        "year_known": properties.get("year_known"),
        "length_m": length,
        "easting": properties.get("easting"),
        "northing": properties.get("northing"),
        "scan_url": scan_url.strip(),
    }


def _quote_cql_string(value: Any) -> str:
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _build_filter(
    *,
    year_min: int | None,
    year_max: int | None,
    length_min: float | None,
    length_max: float | None,
) -> str | None:
    filters: list[str] = []

    if year_min is not None and year_max is not None and year_min > year_max:
        raise ValueError("year_min cannot be greater than year_max.")

    if (
        length_min is not None
        and length_max is not None
        and length_min > length_max
    ):
        raise ValueError("length_min cannot be greater than length_max.")

    # SOBI exposes year_known as a string.
    if (
        year_min is not None
        and year_max is not None
        and year_min == year_max
    ):
        filters.append(
            "year_known = " + _quote_cql_string(year_min)
        )
    else:
        if year_min is not None:
            filters.append(
                "year_known >= " + _quote_cql_string(year_min)
            )

        if year_max is not None:
            filters.append(
                "year_known <= " + _quote_cql_string(year_max)
            )

    if length_min is not None:
        filters.append(f"length >= {float(length_min)}")

    if length_max is not None:
        filters.append(f"length <= {float(length_max)}")

    return " AND ".join(filters) if filters else None


def _normalise_bbox(
    bbox: tuple[float, float, float, float] | list[float] | None,
) -> str | None:
    if bbox is None:
        return None

    if len(bbox) != 4:
        raise ValueError(
            "bbox must contain min_lon, min_lat, max_lon, max_lat."
        )

    min_lon, min_lat, max_lon, max_lat = (
        float(value) for value in bbox
    )

    if not -180 <= min_lon <= 180:
        raise ValueError("min_lon must be between -180 and 180.")

    if not -180 <= max_lon <= 180:
        raise ValueError("max_lon must be between -180 and 180.")

    if not -90 <= min_lat <= 90:
        raise ValueError("min_lat must be between -90 and 90.")

    if not -90 <= max_lat <= 90:
        raise ValueError("max_lat must be between -90 and 90.")

    if min_lon >= max_lon:
        raise ValueError("min_lon must be smaller than max_lon.")

    if min_lat >= max_lat:
        raise ValueError("min_lat must be smaller than max_lat.")

    return ",".join(
        str(value)
        for value in (min_lon, min_lat, max_lon, max_lat)
    )


def _fetch_json(params: dict[str, Any]) -> dict[str, Any]:
    url = (
        SOBI_ITEMS_URL
        + "?"
        + urllib.parse.urlencode(params)
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            return json.load(response)

    except urllib.error.HTTPError as exc:
        raise BGSClientError(
            f"BGS search returned HTTP {exc.code}: {exc.reason}"
        ) from exc

    except urllib.error.URLError as exc:
        raise BGSClientError(
            f"BGS search network failure: {exc.reason}"
        ) from exc

    except Exception as exc:
        raise BGSClientError(
            f"BGS search failed: {type(exc).__name__}: {exc}"
        ) from exc


def _query_params(
    *,
    offset: int,
    limit: int,
    filter_expression: str | None,
    bbox: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "f": "json",
        "offset": int(offset),
        "limit": int(limit),
    }

    if filter_expression:
        params["filter"] = filter_expression

    if bbox:
        params["bbox"] = bbox

    return params


def _number_matched(
    *,
    filter_expression: str | None,
    bbox: str | None,
) -> int:
    payload = _fetch_json(
        _query_params(
            offset=0,
            limit=1,
            filter_expression=filter_expression,
            bbox=bbox,
        )
    )

    return int(payload.get("numberMatched", 0))


def _fetch_record(
    *,
    offset: int,
    filter_expression: str | None,
    bbox: str | None,
) -> dict[str, Any] | None:
    payload = _fetch_json(
        _query_params(
            offset=offset,
            limit=1,
            filter_expression=filter_expression,
            bbox=bbox,
        )
    )

    features = payload.get("features", [])

    if not features:
        return None

    return _normalise_record(features[0])


def _fetch_window(
    *,
    offset: int,
    limit: int,
    filter_expression: str | None,
    bbox: str | None,
) -> list[dict[str, Any]]:
    payload = _fetch_json(
        _query_params(
            offset=offset,
            limit=limit,
            filter_expression=filter_expression,
            bbox=bbox,
        )
    )

    rows: list[dict[str, Any]] = []

    for feature in payload.get("features", []):
        row = _normalise_record(feature)

        if row is not None:
            rows.append(row)

    return rows

def get_record_by_bgs_id(
    bgs_id: str | int,
) -> dict[str, Any] | None:
    """Return one exact public SOBI record by BGS id."""

    canonical_id = normalise_bgs_id(bgs_id)

    payload = _fetch_json(
        _query_params(
            offset=0,
            limit=5,
            filter_expression=f"bgs_id = {int(canonical_id)}",
            bbox=None,
        )
    )

    for feature in payload.get("features", []):
        row = _normalise_record(feature)

        if row is None:
            continue

        if row["bgs_id"] == canonical_id:
            return row

    return None

def _matches_type(
    row: dict[str, Any],
    type_filter: str,
) -> bool:
    if type_filter == "any":
        return True

    name = str(row.get("name") or "")

    if type_filter == "tp":
        return bool(
            re.search(
                r"\bTP[A-Z0-9/-]*\b|TRIAL\s+PIT",
                name,
                re.IGNORECASE,
            )
        )

    if type_filter == "bh":
        return bool(
            re.search(
                r"\bBH[A-Z0-9/-]*\b"
                r"|\bBOREHOLE\b"
                r"|\bBORE\b",
                name,
                re.IGNORECASE,
            )
        )

    if type_filter == "shaft":
        return bool(
            re.search(
                r"\bSHAFT\b",
                name,
                re.IGNORECASE,
            )
        )

    raise ValueError(
        "type_filter must be one of: any, bh, tp, shaft."
    )


def search_records(
    *,
    n: int = 5,
    seed: int = 42,
    year_min: int | None = None,
    year_max: int | None = None,
    length_min: float | None = None,
    length_max: float | None = None,
    bbox: tuple[float, float, float, float] | list[float] | None = None,
    type_filter: str = "any",
) -> list[dict[str, Any]]:
    """Return a small deterministic sample of usable public SOBI scans."""

    if not 1 <= int(n) <= MAX_DOCUMENTS:
        raise ValueError(
            f"n must be between 1 and {MAX_DOCUMENTS}."
        )

    if type_filter not in {"any", "bh", "tp", "shaft"}:
        raise ValueError(
            "type_filter must be one of: any, bh, tp, shaft."
        )

    filter_expression = _build_filter(
        year_min=year_min,
        year_max=year_max,
        length_min=length_min,
        length_max=length_max,
    )

    bbox_text = _normalise_bbox(bbox)

    number_matched = _number_matched(
        filter_expression=filter_expression,
        bbox=bbox_text,
    )

    if number_matched <= 0:
        return []

    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    if type_filter == "any":
        max_attempts = min(
            number_matched,
            max(
                MIN_SAMPLE_ATTEMPTS,
                int(n) * ATTEMPT_MULTIPLIER,
            ),
        )

        offsets = rng.sample(
            range(number_matched),
            k=max_attempts,
        )

        for offset in offsets:
            row = _fetch_record(
                offset=offset,
                filter_expression=filter_expression,
                bbox=bbox_text,
            )

            if row is None:
                continue

            if row["bgs_id"] in selected_ids:
                continue

            selected.append(row)
            selected_ids.add(row["bgs_id"])

            if len(selected) >= n:
                break

        return selected

    window_size = min(
        TYPE_WINDOW_SIZE,
        number_matched,
    )

    max_offset = max(
        0,
        number_matched - window_size,
    )

    possible_offsets = max_offset + 1

    n_windows = min(
        TYPE_MAX_WINDOWS,
        possible_offsets,
    )

    if max_offset == 0:
        offsets = [0]
    else:
        offsets = rng.sample(
            range(possible_offsets),
            k=n_windows,
        )

    for offset in offsets:
        rows = _fetch_window(
            offset=offset,
            limit=window_size,
            filter_expression=filter_expression,
            bbox=bbox_text,
        )

        matches = [
            row
            for row in rows
            if _matches_type(row, type_filter)
        ]

        rng.shuffle(matches)

        for row in matches:
            if row["bgs_id"] in selected_ids:
                continue

            selected.append(row)
            selected_ids.add(row["bgs_id"])

            if len(selected) >= n:
                return selected

    return selected


def _sanitise_filename(value: str) -> str:
    value = value.strip()

    value = re.sub(
        r'[<>:"/\\|?*]+',
        "-",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    value = value.strip(" .")

    if not value:
        return "scan.pdf"

    if not value.lower().endswith(".pdf"):
        value += ".pdf"

    return value


def _filename_from_headers(
    headers: Any,
    bgs_id: str,
) -> str:
    disposition = headers.get(
        "Content-Disposition",
        "",
    )

    match = re.search(
        r'filename="([^"]+)"',
        disposition,
        re.IGNORECASE,
    )

    if match:
        return _sanitise_filename(
            match.group(1)
        )

    return f"{bgs_id}.pdf"


def download_scan(
    *,
    bgs_id: str | int,
    output_dir: str | Path,
    scan_url: str | None = None,
) -> Path:
    """Download one selected public SOBI PDF and return its local path."""

    canonical_id = normalise_bgs_id(bgs_id)

    if scan_url is None:
        url = SCAN_URL_TEMPLATE.format(
            bgs_id=canonical_id
        )
    else:
        url = scan_url.strip()

        if not is_usable_scan_url(url):
            raise BGSClientError(
                "Refusing to download an unexpected scan URL."
            )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=60,
        ) as response:
            status = response.status
            content_type = response.headers.get_content_type()

            filename = _filename_from_headers(
                response.headers,
                canonical_id,
            )

            data = response.read()

    except urllib.error.HTTPError as exc:
        raise BGSClientError(
            f"BGS scan returned HTTP {exc.code}: {exc.reason}"
        ) from exc

    except urllib.error.URLError as exc:
        raise BGSClientError(
            f"BGS scan network failure: {exc.reason}"
        ) from exc

    except Exception as exc:
        raise BGSClientError(
            f"BGS scan download failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if status != 200:
        raise BGSClientError(
            f"BGS scan returned unexpected HTTP status {status}."
        )

    if content_type != "application/pdf":
        raise BGSClientError(
            f"BGS scan is not application/pdf: {content_type!r}."
        )

    if not data.startswith(b"%PDF-"):
        raise BGSClientError(
            "BGS response does not contain a valid PDF signature."
        )

    destination = Path(output_dir)
    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = destination / filename
    output_path.write_bytes(data)

    return output_path