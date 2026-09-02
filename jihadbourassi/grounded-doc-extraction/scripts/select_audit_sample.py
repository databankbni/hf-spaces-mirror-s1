from __future__ import annotations

import csv
import difflib
import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path


INPUT_PATH = Path("data/audit/candidates.csv")
OUTPUT_PATH = Path("data/audit/selected_audit_sample.csv")

TARGET_SIZE = 30
BASE_PER_WINDOW = 1
MAX_PER_WINDOW = 3
SEED = "phase1-audit-v2"


# Diversity objectives only.
# These are NOT document labels and NOT ground truth.
COVERAGE_TARGETS = {
    "shaft": 1,
    "trial_pit": 2,
    "borehole": 2,
    "pre_1950": 2,
    "year_2000_plus": 2,
    "length_100m_plus": 2,
    "length_under_5m": 2,
    "missing_year": 2,
    "missing_length": 2,
}


def stable_key(row, salt=""):
    text = (
        f"{SEED}|{salt}|"
        f"{row.get('bgs_id', '')}|"
        f"{row.get('reference', '')}"
    )

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def parse_int(value):
    if value in (None, ""):
        return None

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_float(value):
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify(row):
    name = row.get("name") or ""
    year = parse_int(row.get("year_known"))
    length = parse_float(row.get("length_m"))

    return {
        "shaft": bool(
            re.search(
                r"\bSHAFT\b",
                name,
                re.IGNORECASE,
            )
        ),
        "trial_pit": bool(
            re.search(
                r"\bTP\d*\b|TRIAL PIT",
                name,
                re.IGNORECASE,
            )
        ),
        "borehole": bool(
            re.search(
                r"\bBH\d*\b|\bBORE\b|\bBOREHOLE\b",
                name,
                re.IGNORECASE,
            )
        ),
        "pre_1950": (
            year is not None
            and year < 1950
        ),
        "year_2000_plus": (
            year is not None
            and year >= 2000
        ),
        "length_100m_plus": (
            length is not None
            and length >= 100
        ),
        "length_under_5m": (
            length is not None
            and length < 5
        ),
        "missing_year": (
            year is None
        ),
        "missing_length": (
            length is None
        ),
    }


def normalise_name(value):
    if not value:
        return ""

    value = value.lower()
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def name_similarity(row_a, row_b):
    name_a = normalise_name(row_a.get("name"))
    name_b = normalise_name(row_b.get("name"))

    if not name_a or not name_b:
        return 0.0

    return difflib.SequenceMatcher(
        None,
        name_a,
        name_b,
    ).ratio()


def max_name_similarity(row, selected):
    if not selected:
        return 0.0

    return max(
        name_similarity(row, selected_row)
        for selected_row in selected
    )


def read_candidates():
    with INPUT_PATH.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        return list(csv.DictReader(handle))


def count_coverage(rows):
    counts = Counter()

    for row in rows:
        flags = classify(row)

        for name, present in flags.items():
            if present:
                counts[name] += 1

    return counts


def choose_base_sample(rows):
    by_window = defaultdict(list)

    for row in rows:
        by_window[row["window"]].append(row)

    selected = []

    for window in sorted(
        by_window,
        key=lambda value: int(value),
    ):
        candidates = sorted(
            by_window[window],
            key=lambda row: stable_key(
                row,
                salt=f"base-window-{window}",
            ),
        )

        if len(candidates) < BASE_PER_WINDOW:
            raise RuntimeError(
                f"Window {window} contains only "
                f"{len(candidates)} usable candidates."
            )

        for row in candidates[:BASE_PER_WINDOW]:
            selected_row = dict(row)

            selected_row["selection_reason"] = (
                f"base_window_{window}"
            )

            selected_row["max_name_similarity"] = ""

            selected.append(selected_row)

    return selected


def choose_diversity_additions(rows, selected):
    selected_ids = {
        row["bgs_id"]
        for row in selected
    }

    while len(selected) < TARGET_SIZE:
        coverage = count_coverage(selected)

        deficits = {
            name: max(
                0,
                target - coverage.get(name, 0),
            )
            for name, target in COVERAGE_TARGETS.items()
        }

        window_counts = Counter(
            row["window"]
            for row in selected
        )

        remaining = [
            row
            for row in rows
            if (
                row["bgs_id"] not in selected_ids
                and window_counts[row["window"]] < MAX_PER_WINDOW
            )
        ]

        if not remaining:
            raise RuntimeError(
                "Not enough eligible candidates to reach "
                f"target size {TARGET_SIZE} while respecting "
                f"MAX_PER_WINDOW={MAX_PER_WINDOW}."
            )

        ranked = []

        for row in remaining:
            flags = classify(row)

            unmet = [
                name
                for name, deficit in deficits.items()
                if deficit > 0 and flags[name]
            ]

            diversity_score = sum(
                deficits[name]
                for name in unmet
            )

            similarity = max_name_similarity(
                row,
                selected,
            )

            ranked.append(
                (
                    -diversity_score,
                    similarity,
                    window_counts[row["window"]],
                    stable_key(
                        row,
                        salt=f"extra-{len(selected)}",
                    ),
                    row,
                    unmet,
                )
            )

        ranked.sort(
            key=lambda item: (
                item[0],
                item[1],
                item[2],
                item[3],
            )
        )

        (
            _,
            similarity,
            _,
            _,
            chosen,
            unmet,
        ) = ranked[0]

        selected_row = dict(chosen)

        if unmet:
            selected_row["selection_reason"] = (
                "diversity:"
                + "+".join(unmet)
            )
        else:
            selected_row["selection_reason"] = (
                "diversity:name_spread"
            )

        selected_row["max_name_similarity"] = (
            f"{similarity:.3f}"
        )

        selected.append(selected_row)
        selected_ids.add(chosen["bgs_id"])

    return selected


def write_selected(rows):
    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_columns = [
        column
        for column in rows[0].keys()
        if column
        not in {
            "selection_reason",
            "max_name_similarity",
        }
    ]

    fieldnames = source_columns + [
        "selection_order",
        "selection_reason",
        "diversity_flags",
        "max_name_similarity",
    ]

    with OUTPUT_PATH.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for order, row in enumerate(
            rows,
            start=1,
        ):
            output_row = {
                key: value
                for key, value in row.items()
                if key
                not in {
                    "selection_reason",
                    "max_name_similarity",
                }
            }

            flags = classify(row)

            output_row["selection_order"] = order
            output_row["selection_reason"] = (
                row["selection_reason"]
            )

            output_row["diversity_flags"] = ";".join(
                name
                for name, present in flags.items()
                if present
            )

            output_row["max_name_similarity"] = (
                row["max_name_similarity"]
            )

            writer.writerow(output_row)


def main():
    rows = read_candidates()

    if len(rows) < TARGET_SIZE:
        raise RuntimeError(
            f"Only {len(rows)} candidates available, "
            f"but target size is {TARGET_SIZE}."
        )

    base = choose_base_sample(rows)

    selected = choose_diversity_additions(
        rows,
        list(base),
    )

    write_selected(selected)

    coverage = count_coverage(selected)

    window_counts = Counter(
        row["window"]
        for row in selected
    )

    similarities = [
        float(row["max_name_similarity"])
        for row in selected
        if row["max_name_similarity"] != ""
    ]

    print(f"input_candidates = {len(rows)}")
    print(f"base_selected = {len(base)}")
    print(f"final_selected = {len(selected)}")
    print(f"written = {OUTPUT_PATH}")
    print()

    print("selected_per_window")
    print(
        dict(
            sorted(
                window_counts.items(),
                key=lambda item: int(item[0]),
            )
        )
    )
    print()

    print("diversity_coverage")

    for name, target in COVERAGE_TARGETS.items():
        print(
            f"{name}: "
            f"{coverage.get(name, 0)} "
            f"(target >= {target})"
        )

    print()

    if similarities:
        print(
            "max_similarity_among_additions = "
            f"{max(similarities):.3f}"
        )

    print(
        "max_selected_per_window = "
        f"{max(window_counts.values())}"
    )


if __name__ == "__main__":
    main()