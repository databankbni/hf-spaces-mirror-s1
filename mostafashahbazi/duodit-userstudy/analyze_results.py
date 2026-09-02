#!/usr/bin/env python3
"""Analyze DuoDiT user-study submissions stored in a Hugging Face Dataset repo.

Default source:
    mostafashahbazi/duodit-user-study-results

Outputs are written to analysis_outputs/ by default.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from huggingface_hub import HfApi, hf_hub_download
except Exception as error:  # pragma: no cover
    HfApi = None
    hf_hub_download = None
    HF_IMPORT_ERROR = error
else:
    HF_IMPORT_ERROR = None


DEFAULT_REPO_ID = "mostafashahbazi/duodit-user-study-results"
DEFAULT_RESULTS_DIR = "data/submissions"
DEFAULT_OUTPUT_DIR = "analysis_outputs"
MODEL_DUODIT = "DuoDiT"
MODEL_BASELINE = "LightningDiT"
TIE_LABEL = "About the same"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze DuoDiT vs. LightningDiT user-study results from Hugging Face."
    )
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID, help="HF dataset repo id.")
    parser.add_argument("--revision", default=None, help="Optional dataset revision.")
    parser.add_argument(
        "--results-dir",
        default=DEFAULT_RESULTS_DIR,
        help="Directory in the dataset repo containing submission JSONL files.",
    )
    parser.add_argument(
        "--local-dir",
        type=Path,
        default=None,
        help="Analyze local JSONL files instead of downloading from Hugging Face.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(DEFAULT_OUTPUT_DIR),
        help="Directory for generated CSV/JSON/Markdown analysis files.",
    )
    parser.add_argument(
        "--expected-questions",
        type=int,
        default=None,
        help="Expected rows per complete submission. Defaults to max observed row count.",
    )
    parser.add_argument(
        "--include-incomplete",
        action="store_true",
        help="Include incomplete submissions in preference summaries.",
    )
    parser.add_argument(
        "--latest-per-email",
        action="store_true",
        help="Use only the latest complete submission per email in preference summaries.",
    )
    parser.add_argument(
        "--exclude-email",
        action="append",
        default=[],
        help=(
            "Participant email to exclude from analysis. Can be repeated, "
            "or pass comma-separated emails in one flag."
        ),
    )
    parser.add_argument(
        "--exclude-email-file",
        type=Path,
        default=None,
        help="Text file with one participant email to exclude per line. Lines starting with # are ignored.",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path(".cache/hf-user-study-results"),
        help="Local directory for downloaded HF JSONL files.",
    )
    parser.add_argument("--quiet", action="store_true", help="Print less to stdout.")
    return parser.parse_args()


def require_hf() -> None:
    if HfApi is None or hf_hub_download is None:
        raise SystemExit(
            "huggingface_hub is required for downloads. "
            f"Original import error: {HF_IMPORT_ERROR}"
        )


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def split_email_values(values: list[str]) -> set[str]:
    emails: set[str] = set()
    for value in values:
        for item in str(value).split(","):
            email = normalize_email(item)
            if email:
                emails.add(email)
    return emails


def load_excluded_emails(values: list[str], email_file: Path | None) -> set[str]:
    emails = split_email_values(values)
    if email_file is None:
        return emails
    if not email_file.exists():
        raise SystemExit(f"Exclude email file not found: {email_file}")
    for line in email_file.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].strip()
        if clean:
            emails.update(split_email_values([clean]))
    return emails


def discover_hf_jsonl_files(repo_id: str, revision: str | None, results_dir: str) -> list[str]:
    require_hf()
    api = HfApi()
    files = api.list_repo_files(repo_id=repo_id, repo_type="dataset", revision=revision)
    prefix = results_dir.strip("/")
    return sorted(
        file_name
        for file_name in files
        if file_name.startswith(prefix + "/") and file_name.endswith(".jsonl")
    )


def download_hf_jsonl_files(
    repo_id: str,
    revision: str | None,
    results_dir: str,
    download_dir: Path,
) -> list[Path]:
    require_hf()
    jsonl_files = discover_hf_jsonl_files(repo_id, revision, results_dir)
    if not jsonl_files:
        raise SystemExit(f"No JSONL files found in dataset repo {repo_id}/{results_dir}.")

    download_dir.mkdir(parents=True, exist_ok=True)
    local_paths = []
    for file_name in jsonl_files:
        local_path = hf_hub_download(
            repo_id=repo_id,
            repo_type="dataset",
            filename=file_name,
            revision=revision,
            local_dir=download_dir,
        )
        local_paths.append(Path(local_path))
    return local_paths


def find_local_jsonl_files(local_dir: Path, results_dir: str) -> list[Path]:
    candidates = []
    preferred = local_dir / results_dir.strip("/")
    search_roots = [preferred] if preferred.exists() else [local_dir]
    for root in search_roots:
        candidates.extend(path for path in root.rglob("*.jsonl") if path.is_file())
    return sorted(candidates)


def load_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"Invalid JSON in {path}:{line_number}: {error}") from error
                row["_source_file"] = path.name
                rows.append(row)
    return rows


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def pct(numerator: float, denominator: float) -> float | None:
    value = safe_divide(numerator, denominator)
    return None if value is None else round(value * 100, 2)


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if total == 0:
        return None, None
    p_hat = successes / total
    denom = 1 + z * z / total
    center = (p_hat + z * z / (2 * total)) / denom
    half_width = z * math.sqrt((p_hat * (1 - p_hat) + z * z / (4 * total)) / total) / denom
    return round(center - half_width, 4), round(center + half_width, 4)


def binomial_two_sided_p_value(successes: int, total: int) -> float | None:
    """Exact two-sided binomial test for H0 p=0.5, using log probabilities."""
    if total == 0:
        return None
    log_half = math.log(0.5)

    def log_pmf(k: int) -> float:
        return (
            math.lgamma(total + 1)
            - math.lgamma(k + 1)
            - math.lgamma(total - k + 1)
            + total * log_half
        )

    observed = log_pmf(successes)
    probability = 0.0
    for k in range(total + 1):
        current = log_pmf(k)
        if current <= observed + 1e-12:
            probability += math.exp(current)
    return round(min(1.0, probability), 6)


def selected_model(row: dict[str, Any]) -> str:
    preference = row.get("preference", "")
    if preference == "Option A":
        return row.get("left_model", "")
    if preference == "Option B":
        return row.get("right_model", "")
    if preference == TIE_LABEL:
        return TIE_LABEL
    return ""


def model_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    selected = Counter(selected_model(row) for row in rows)
    options = Counter(row.get("preference", "") for row in rows)
    left_models = Counter(row.get("left_model", "") for row in rows)
    right_models = Counter(row.get("right_model", "") for row in rows)

    duodit = selected[MODEL_DUODIT]
    baseline = selected[MODEL_BASELINE]
    ties = selected[TIE_LABEL]
    decisive = duodit + baseline
    low, high = wilson_interval(duodit, decisive)
    return {
        "rows": len(rows),
        "duodit_wins": duodit,
        "lightningdit_wins": baseline,
        "ties": ties,
        "decisive_rows": decisive,
        "duodit_win_rate_decisive_pct": pct(duodit, decisive),
        "duodit_share_all_pct": pct(duodit, len(rows)),
        "lightningdit_share_all_pct": pct(baseline, len(rows)),
        "tie_share_all_pct": pct(ties, len(rows)),
        "duodit_wilson95_low": low,
        "duodit_wilson95_high": high,
        "binomial_p_value_vs_50_50": binomial_two_sided_p_value(duodit, decisive),
        "option_a_selected": options["Option A"],
        "option_b_selected": options["Option B"],
        "about_same_selected": options[TIE_LABEL],
        "duodit_shown_left": left_models[MODEL_DUODIT],
        "duodit_shown_right": right_models[MODEL_DUODIT],
    }


def group_rows(rows: list[dict[str, Any]], key_fields: list[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field, "") for field in key_fields)
        grouped[key].append(row)

    output = []
    for key, group in grouped.items():
        item = {field: value for field, value in zip(key_fields, key)}
        item.update(model_counts(group))
        output.append(item)
    return sorted(output, key=lambda item: (-int(item["rows"]), tuple(str(item.get(f, "")) for f in key_fields)))


def split_by_submission(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    submissions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        submissions[row.get("submission_id", "")].append(row)
    return dict(submissions)


def submission_summary_rows(
    rows: list[dict[str, Any]],
    expected_questions: int,
) -> list[dict[str, Any]]:
    summaries = []
    for submission_id, group in split_by_submission(rows).items():
        first = group[0]
        started = parse_time(first.get("started_at"))
        submitted = parse_time(first.get("submitted_at"))
        duration_seconds = None
        if started is not None and submitted is not None:
            duration_seconds = round((submitted - started).total_seconds(), 3)
        item = {
            "submission_id": submission_id,
            "participant_email": first.get("participant_email", ""),
            "started_at": first.get("started_at", ""),
            "submitted_at": first.get("submitted_at", ""),
            "duration_seconds": duration_seconds,
            "duration_minutes": None if duration_seconds is None else round(duration_seconds / 60, 3),
            "row_count": len(group),
            "expected_questions": expected_questions,
            "complete": len(group) == expected_questions,
        }
        item.update(model_counts(group))
        summaries.append(item)
    return sorted(summaries, key=lambda item: str(item["submitted_at"]))


def latest_complete_submission_ids_by_email(
    summaries: list[dict[str, Any]],
) -> set[str]:
    latest: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        if not summary["complete"]:
            continue
        email = normalize_email(summary.get("participant_email", ""))
        if not email:
            continue
        existing = latest.get(email)
        if existing is None or str(summary.get("submitted_at", "")) > str(existing.get("submitted_at", "")):
            latest[email] = summary
    return {str(summary["submission_id"]) for summary in latest.values()}


def split_excluded_submissions(
    rows: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    excluded_emails: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    if not excluded_emails:
        return rows, [], set()

    excluded_summaries = [
        summary
        for summary in summaries
        if normalize_email(summary.get("participant_email", "")) in excluded_emails
    ]
    excluded_ids = {str(summary["submission_id"]) for summary in excluded_summaries}
    filtered_rows = [
        row for row in rows if str(row.get("submission_id", "")) not in excluded_ids
    ]
    return filtered_rows, excluded_summaries, excluded_ids


def choose_analysis_rows(
    rows: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    include_incomplete: bool,
    latest_per_email: bool,
) -> tuple[list[dict[str, Any]], set[str]]:
    allowed_ids = {
        str(summary["submission_id"])
        for summary in summaries
        if include_incomplete or summary["complete"]
    }
    if latest_per_email:
        allowed_ids &= latest_complete_submission_ids_by_email(summaries)
    return [row for row in rows if row.get("submission_id", "") in allowed_ids], allowed_ids


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_report(path: Path, summary: dict[str, Any]) -> None:
    model = summary["model_preference"]
    lines = [
        "# DuoDiT User Study Analysis",
        "",
        f"- Source dataset: `{summary['repo_id']}`",
        f"- Result files: `{summary['source_file_count']}`",
        f"- Raw rows: `{summary['raw_rows']}`",
        f"- Total submissions: `{summary['total_submissions']}`",
        f"- Submissions excluded by email: `{summary['excluded_submissions']}`",
        f"- Rows after email exclusion: `{summary['rows_after_email_exclusion']}`",
        f"- Complete submissions analyzed: `{summary['analyzed_submissions']}`",
        f"- Rows analyzed: `{summary['analyzed_rows']}`",
        f"- Expected questions per complete submission: `{summary['expected_questions']}`",
        "",
        "## Model Preference",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| DuoDiT wins | {model['duodit_wins']} |",
        f"| LightningDiT wins | {model['lightningdit_wins']} |",
        f"| About the same | {model['ties']} |",
        f"| Decisive rows | {model['decisive_rows']} |",
        f"| DuoDiT win rate among decisive | {model['duodit_win_rate_decisive_pct']}% |",
        f"| DuoDiT 95% Wilson CI | [{model['duodit_wilson95_low']}, {model['duodit_wilson95_high']}] |",
        f"| Binomial p-value vs 50/50 | {model['binomial_p_value_vs_50_50']} |",
        "",
        "## Output Files",
        "",
        "- `summary.json`: machine-readable headline metrics",
        "- `submissions.csv`: one row per submission, including completeness",
        "- `model_preference.csv`: one-row model preference summary",
        "- `class_summary.csv`: per ImageNet class preference summary",
        "- `prompt_summary.csv`: per prompt/image-pair preference summary",
        "- `participant_summary.csv`: per participant preference summary",
        "- `display_position_summary.csv`: left/right model balancing summary",
        "- `raw_rows.csv`: rows used for analysis after filtering",
        "- `incomplete_submissions.csv`: incomplete submissions excluded by default",
        "- `excluded_submissions.csv`: submissions excluded by participant email",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    if args.local_dir:
        source_paths = find_local_jsonl_files(args.local_dir, args.results_dir)
    else:
        source_paths = download_hf_jsonl_files(
            repo_id=args.repo_id,
            revision=args.revision,
            results_dir=args.results_dir,
            download_dir=args.download_dir,
        )

    if not source_paths:
        raise SystemExit("No JSONL result files found.")

    rows = load_rows(source_paths)
    if not rows:
        raise SystemExit("No rows found in JSONL result files.")

    observed_counts = Counter(row.get("submission_id", "") for row in rows)
    expected_questions = args.expected_questions or max(observed_counts.values())
    submissions = submission_summary_rows(rows, expected_questions)
    excluded_emails = load_excluded_emails(args.exclude_email, args.exclude_email_file)
    filtered_rows, excluded_submissions, excluded_submission_ids = split_excluded_submissions(
        rows,
        submissions,
        excluded_emails,
    )
    filtered_submissions = [
        summary
        for summary in submissions
        if str(summary["submission_id"]) not in excluded_submission_ids
    ]
    analysis_rows, analyzed_submission_ids = choose_analysis_rows(
        filtered_rows,
        filtered_submissions,
        include_incomplete=args.include_incomplete,
        latest_per_email=args.latest_per_email,
    )

    incomplete = [row for row in filtered_submissions if not row["complete"]]
    complete = [row for row in filtered_submissions if row["complete"]]
    participant_emails = {
        normalize_email(row.get("participant_email", ""))
        for row in filtered_submissions
        if row.get("participant_email")
    }
    durations = [
        float(row["duration_seconds"])
        for row in submissions
        if row.get("duration_seconds") is not None and row["complete"]
    ]

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    model_summary = model_counts(analysis_rows)
    position_summary = group_rows(analysis_rows, ["left_model", "right_model"])
    class_summary = group_rows(
        analysis_rows,
        ["class_id", "synset", "class_name", "class_name_fa", "class_dir"],
    )
    prompt_summary = group_rows(
        analysis_rows,
        ["prompt_id", "filename", "class_id", "class_name", "class_name_fa"],
    )
    participant_summary = group_rows(analysis_rows, ["participant_email"])

    summary = {
        "repo_id": args.repo_id,
        "revision": args.revision,
        "results_dir": args.results_dir,
        "source_files": [str(path) for path in source_paths],
        "source_file_count": len(source_paths),
        "raw_rows": len(rows),
        "rows_after_email_exclusion": len(filtered_rows),
        "expected_questions": expected_questions,
        "total_submissions": len(submissions),
        "submissions_after_email_exclusion": len(filtered_submissions),
        "complete_submissions": len(complete),
        "incomplete_submissions": len(incomplete),
        "unique_participants": len(participant_emails),
        "excluded_emails": sorted(excluded_emails),
        "excluded_submission_ids": sorted(excluded_submission_ids),
        "excluded_submissions": len(excluded_submission_ids),
        "excluded_rows": len(rows) - len(filtered_rows),
        "include_incomplete": args.include_incomplete,
        "latest_per_email": args.latest_per_email,
        "analyzed_submissions": len(analyzed_submission_ids),
        "analyzed_rows": len(analysis_rows),
        "complete_duration_seconds_median": (
            round(statistics.median(durations), 3) if durations else None
        ),
        "complete_duration_seconds_mean": (
            round(statistics.mean(durations), 3) if durations else None
        ),
        "model_preference": model_summary,
    }

    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "submissions.csv", filtered_submissions)
    write_csv(output_dir / "incomplete_submissions.csv", incomplete)
    write_csv(output_dir / "excluded_submissions.csv", excluded_submissions)
    write_csv(output_dir / "model_preference.csv", [model_summary])
    write_csv(output_dir / "display_position_summary.csv", position_summary)
    write_csv(output_dir / "class_summary.csv", class_summary)
    write_csv(output_dir / "prompt_summary.csv", prompt_summary)
    write_csv(output_dir / "participant_summary.csv", participant_summary)
    write_csv(output_dir / "raw_rows.csv", analysis_rows)
    write_report(output_dir / "report.md", summary)

    if not args.quiet:
        print(f"Loaded {len(rows)} rows from {len(source_paths)} result files.")
        print(
            f"Submissions: {len(submissions)} total, "
            f"{len(excluded_submission_ids)} excluded by email, "
            f"{len(complete)} complete, {len(incomplete)} incomplete after exclusion."
        )
        print(
            f"Analyzed {len(analysis_rows)} rows from {len(analyzed_submission_ids)} submissions."
        )
        print(
            "DuoDiT decisive win rate: "
            f"{model_summary['duodit_win_rate_decisive_pct']}% "
            f"({model_summary['duodit_wins']}/"
            f"{model_summary['decisive_rows']})"
        )
        print(f"Wrote analysis to: {output_dir.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
