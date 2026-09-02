from __future__ import annotations

import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://ogcapi.bgs.ac.uk/collections/onshoreboreholeindex/items"

N_WINDOWS = 12
WINDOW_SIZE = 10

OUTPUT_PATH = Path("data/audit/candidates.csv")


def normalise_id(value):
    if value is None:
        return None

    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


def is_usable_scan_url(value):
    if not isinstance(value, str):
        return False

    value = value.strip()
    parsed = urllib.parse.urlparse(value)

    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc == "api.bgs.ac.uk"
        and parsed.path.startswith("/sobi-scans/v1/borehole/scans/items/")
    )


def fetch_json(params):
    url = BASE_URL + "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "grounded-doc-extraction-phase1"},
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def get_number_matched():
    payload = fetch_json(
        {
            "f": "json",
            "limit": 1,
        }
    )

    return int(payload["numberMatched"])


def make_offsets(total, n_windows):
    if n_windows <= 1:
        return [0]

    max_offset = max(0, total - WINDOW_SIZE)

    return [
        round(i * max_offset / (n_windows - 1))
        for i in range(n_windows)
    ]


def fetch_window(offset, limit=WINDOW_SIZE):
    payload = fetch_json(
        {
            "f": "json",
            "offset": offset,
            "limit": limit,
        }
    )

    rows = []

    for feature in payload.get("features", []):
        properties = feature.get("properties", {})

        scan_url = properties.get("scan_url")

        if not is_usable_scan_url(scan_url):
            continue

        length = properties.get("length")

        if isinstance(length, (int, float)) and length < 0:
            length = None

        rows.append(
            {
                "bgs_id": normalise_id(properties.get("bgs_id")),
                "reference": properties.get("reference"),
                "name": properties.get("name"),
                "length_m": length,
                "year_known": properties.get("year_known"),
                "precision": properties.get("precision"),
                "scan_quality": properties.get("scan_quality"),
                "scan_url": scan_url,
            }
        )

    return rows


def write_csv(rows):
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "window",
        "catalog_offset",
        "bgs_id",
        "reference",
        "name",
        "length_m",
        "year_known",
        "precision",
        "scan_quality",
        "scan_url",
    ]

    with OUTPUT_PATH.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(rows)


def main():
    total = get_number_matched()
    offsets = make_offsets(
        total,
        N_WINDOWS,
    )

    print(f"numberMatched = {total}")
    print(f"windows = {N_WINDOWS}")
    print(f"window_size = {WINDOW_SIZE}")
    print()

    all_rows = []

    for window_number, offset in enumerate(
        offsets,
        start=1,
    ):
        rows = fetch_window(offset)

        print(
            f"--- window {window_number:02d} "
            f"offset={offset} "
            f"candidates_with_scan={len(rows)} ---"
        )

        for row in rows:
            output_row = {
                "window": window_number,
                "catalog_offset": offset,
                **row,
            }

            all_rows.append(output_row)

            print(
                f"{row['bgs_id']:>8} | "
                f"{str(row['reference']):<18} | "
                f"length={str(row['length_m']):>8} | "
                f"year={str(row['year_known']):<6} | "
                f"quality={str(row['scan_quality']):<10} | "
                f"{row['name']}"
            )

        print()

    write_csv(all_rows)

    print(f"total_candidates_with_scan = {len(all_rows)}")
    print(f"written = {OUTPUT_PATH}")


if __name__ == "__main__":
    main()