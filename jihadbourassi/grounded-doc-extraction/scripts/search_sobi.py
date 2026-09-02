from __future__ import annotations

import argparse
import json
import random
import re
import urllib.parse
import urllib.request


BASE_URL = (
    "https://ogcapi.bgs.ac.uk/"
    "collections/onshoreboreholeindex/items"
)

MAX_DOCUMENTS = 30

ATTEMPT_MULTIPLIER = 4
MIN_SAMPLE_ATTEMPTS = 20

TYPE_WINDOW_SIZE = 20
TYPE_MAX_WINDOWS = 15


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Search and randomly sample public "
            "BGS/SOBI borehole records."
        )
    )

    parser.add_argument(
        "--n",
        type=int,
        default=5,
        help="Number of documents to sample (1-30).",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling.",
    )

    parser.add_argument(
        "--year-min",
        type=int,
        default=None,
        help="Minimum known year.",
    )

    parser.add_argument(
        "--year-max",
        type=int,
        default=None,
        help="Maximum known year.",
    )

    parser.add_argument(
        "--length-min",
        type=float,
        default=None,
        help="Minimum registered length/depth in metres.",
    )

    parser.add_argument(
        "--length-max",
        type=float,
        default=None,
        help="Maximum registered length/depth in metres.",
    )

    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=(
            "MIN_LON",
            "MIN_LAT",
            "MAX_LON",
            "MAX_LAT",
        ),
        default=None,
        help=(
            "Optional geographic bounding box "
            "in longitude/latitude."
        ),
    )

    parser.add_argument(
        "--type",
        choices=[
            "any",
            "bh",
            "tp",
            "shaft",
        ],
        default="any",
        help=(
            "Optional heuristic document/entity type "
            "derived from the SOBI name field."
        ),
    )

    return parser.parse_args()


def validate_args(args):
    if not 1 <= args.n <= MAX_DOCUMENTS:
        raise ValueError(
            f"--n must be between 1 and {MAX_DOCUMENTS}."
        )

    if (
        args.year_min is not None
        and args.year_max is not None
        and args.year_min > args.year_max
    ):
        raise ValueError(
            "--year-min cannot be greater than --year-max."
        )

    if (
        args.length_min is not None
        and args.length_max is not None
        and args.length_min > args.length_max
    ):
        raise ValueError(
            "--length-min cannot be greater than --length-max."
        )

    if args.bbox is not None:
        min_lon, min_lat, max_lon, max_lat = args.bbox

        if not -180 <= min_lon <= 180:
            raise ValueError(
                "MIN_LON must be between -180 and 180."
            )

        if not -180 <= max_lon <= 180:
            raise ValueError(
                "MAX_LON must be between -180 and 180."
            )

        if not -90 <= min_lat <= 90:
            raise ValueError(
                "MIN_LAT must be between -90 and 90."
            )

        if not -90 <= max_lat <= 90:
            raise ValueError(
                "MAX_LAT must be between -90 and 90."
            )

        if min_lon >= max_lon:
            raise ValueError(
                "MIN_LON must be smaller than MAX_LON."
            )

        if min_lat >= max_lat:
            raise ValueError(
                "MIN_LAT must be smaller than MAX_LAT."
            )


def quote_cql_string(value):
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def build_filter(args):
    filters = []

    # SOBI exposes year_known as a string.
    if (
        args.year_min is not None
        and args.year_max is not None
        and args.year_min == args.year_max
    ):
        filters.append(
            "year_known = "
            + quote_cql_string(args.year_min)
        )

    else:
        if args.year_min is not None:
            filters.append(
                "year_known >= "
                + quote_cql_string(args.year_min)
            )

        if args.year_max is not None:
            filters.append(
                "year_known <= "
                + quote_cql_string(args.year_max)
            )

    if args.length_min is not None:
        filters.append(
            f"length >= {args.length_min}"
        )

    if args.length_max is not None:
        filters.append(
            f"length <= {args.length_max}"
        )

    if not filters:
        return None

    return " AND ".join(filters)


def build_bbox(args):
    if args.bbox is None:
        return None

    return ",".join(
        str(value)
        for value in args.bbox
    )


def fetch_json(params):
    url = (
        BASE_URL
        + "?"
        + urllib.parse.urlencode(params)
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "grounded-doc-extraction-phase1"
            )
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        return json.load(response)


def is_usable_scan_url(value):
    if not isinstance(value, str):
        return False

    value = value.strip()
    parsed = urllib.parse.urlparse(value)

    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc == "api.bgs.ac.uk"
        and parsed.path.startswith(
            "/sobi-scans/v1/borehole/scans/items/"
        )
    )


def normalise_id(value):
    if value is None:
        return None

    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


def normalise_record(feature):
    properties = feature.get(
        "properties",
        {},
    )

    scan_url = properties.get(
        "scan_url"
    )

    if not is_usable_scan_url(scan_url):
        return None

    length = properties.get("length")

    if (
        isinstance(length, (int, float))
        and length < 0
    ):
        length = None

    return {
        "bgs_id": normalise_id(
            properties.get("bgs_id")
        ),
        "reference": properties.get(
            "reference"
        ),
        "name": properties.get("name"),
        "year_known": properties.get(
            "year_known"
        ),
        "length_m": length,
        "easting": properties.get(
            "easting"
        ),
        "northing": properties.get(
            "northing"
        ),
        "scan_url": scan_url,
    }


def matches_type(row, type_filter):
    if type_filter == "any":
        return True

    name = row.get("name") or ""

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

    return False


def make_query_params(
    *,
    offset,
    limit,
    filter_expression,
    bbox,
):
    params = {
        "f": "json",
        "offset": offset,
        "limit": limit,
    }

    if filter_expression:
        params["filter"] = (
            filter_expression
        )

    if bbox:
        params["bbox"] = bbox

    return params


def get_number_matched(
    filter_expression,
    bbox,
):
    params = make_query_params(
        offset=0,
        limit=1,
        filter_expression=filter_expression,
        bbox=bbox,
    )

    payload = fetch_json(params)

    return int(
        payload.get(
            "numberMatched",
            0,
        )
    )


def fetch_record_at_offset(
    offset,
    filter_expression,
    bbox,
):
    params = make_query_params(
        offset=offset,
        limit=1,
        filter_expression=filter_expression,
        bbox=bbox,
    )

    payload = fetch_json(params)

    features = payload.get(
        "features",
        [],
    )

    if not features:
        return None

    return normalise_record(
        features[0]
    )


def fetch_window(
    offset,
    limit,
    filter_expression,
    bbox,
):
    params = make_query_params(
        offset=offset,
        limit=limit,
        filter_expression=filter_expression,
        bbox=bbox,
    )

    payload = fetch_json(params)

    rows = []

    for feature in payload.get(
        "features",
        [],
    ):
        row = normalise_record(feature)

        if row is not None:
            rows.append(row)

    return rows


def sample_any_type(
    number_matched,
    n,
    seed,
    filter_expression,
    bbox,
):
    rng = random.Random(seed)

    max_attempts = min(
        number_matched,
        max(
            MIN_SAMPLE_ATTEMPTS,
            n * ATTEMPT_MULTIPLIER,
        ),
    )

    random_offsets = rng.sample(
        range(number_matched),
        k=max_attempts,
    )

    selected = []
    selected_ids = set()

    for offset in random_offsets:
        row = fetch_record_at_offset(
            offset=offset,
            filter_expression=filter_expression,
            bbox=bbox,
        )

        if row is None:
            continue

        if row["bgs_id"] in selected_ids:
            continue

        selected.append(row)
        selected_ids.add(
            row["bgs_id"]
        )

        if len(selected) >= n:
            break

    return selected


def sample_filtered_type(
    number_matched,
    n,
    seed,
    filter_expression,
    bbox,
    type_filter,
):
    rng = random.Random(seed)

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

    selected = []
    selected_ids = set()

    for offset in offsets:
        rows = fetch_window(
            offset=offset,
            limit=window_size,
            filter_expression=filter_expression,
            bbox=bbox,
        )

        matches = [
            row
            for row in rows
            if matches_type(
                row,
                type_filter,
            )
        ]

        rng.shuffle(matches)

        for row in matches:
            if row["bgs_id"] in selected_ids:
                continue

            selected.append(row)
            selected_ids.add(
                row["bgs_id"]
            )

            if len(selected) >= n:
                return selected

    return selected


def sample_records(
    number_matched,
    n,
    seed,
    filter_expression,
    bbox,
    type_filter,
):
    if number_matched <= 0:
        return []

    if type_filter == "any":
        return sample_any_type(
            number_matched=number_matched,
            n=n,
            seed=seed,
            filter_expression=filter_expression,
            bbox=bbox,
        )

    return sample_filtered_type(
        number_matched=number_matched,
        n=n,
        seed=seed,
        filter_expression=filter_expression,
        bbox=bbox,
        type_filter=type_filter,
    )


def print_preview(rows):
    print()
    print("PREVIEW")
    print("-" * 100)

    for index, row in enumerate(
        rows,
        start=1,
    ):
        print(
            f"{index:02d} | "
            f"BGS {row['bgs_id']} | "
            f"{row['reference']} | "
            f"year={row['year_known']} | "
            f"length={row['length_m']} | "
            f"E={row['easting']} | "
            f"N={row['northing']}"
        )

        print(
            f"     {row['name']}"
        )

        print(
            f"     {row['scan_url']}"
        )


def main():
    args = parse_args()
    validate_args(args)

    filter_expression = build_filter(
        args
    )

    bbox = build_bbox(
        args
    )

    print(
        "server_filter =",
        filter_expression or "<none>",
    )

    print(
        "bbox =",
        bbox or "<none>",
    )

    print(
        "type_filter =",
        args.type,
    )

    number_matched = get_number_matched(
        filter_expression=filter_expression,
        bbox=bbox,
    )

    print(
        "numberMatched_before_local_type_filter =",
        number_matched,
    )

    rows = sample_records(
        number_matched=number_matched,
        n=args.n,
        seed=args.seed,
        filter_expression=filter_expression,
        bbox=bbox,
        type_filter=args.type,
    )

    print(
        "usable_documents_sampled =",
        len(rows),
    )

    if len(rows) < args.n:
        print(
            "WARNING: requested",
            args.n,
            "documents but found only",
            len(rows),
            "usable documents matching the "
            "requested heuristic type within "
            "the sampling windows.",
        )

    print_preview(rows)


if __name__ == "__main__":
    main()