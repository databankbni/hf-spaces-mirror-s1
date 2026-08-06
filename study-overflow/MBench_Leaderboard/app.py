import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gradio as gr
import numpy as np
import pandas as pd
from huggingface_hub import CommitOperationAdd, HfApi, snapshot_download

from constants import (
    ALL_COLUMNS,
    LEADERBOARD_INTRO,
    LEADERBOARD_REPO,
    LOCAL_LEADERBOARD_DIR,
    METRIC_COLUMNS,
    MODEL_TYPE_CHOICES,
    RESULTS_CSV,
    SUBMISSION_JSON_FILENAME,
    SUBMIT_INTRO,
)
from scripts.validate_submission import validate_submission_json


SPACE_ROOT = Path(__file__).resolve().parent
LOCAL_LEADERBOARD_PATH = Path(LOCAL_LEADERBOARD_DIR).resolve()
RESULTS_PATH = Path(RESULTS_CSV).resolve()
SEED_RESULTS_PATH = SPACE_ROOT / "seed" / "results.csv"
PENDING_DIR = LOCAL_LEADERBOARD_PATH / "submissions" / "pending"
VERIFIED_DIR = LOCAL_LEADERBOARD_PATH / "submissions" / "verified"
NUMERIC_COLUMNS = [
    "Total M-Score",
    "Entity Score",
    "Environment Score",
    "Causal Score",
    *METRIC_COLUMNS,
]
DEFAULT_VISIBLE_METRICS: list[str] = METRIC_COLUMNS.copy()
DISPLAY_INFO_COLUMNS = [
    "Rank",
    "Model Name",
    "Model Type",
    "Total M-Score",
    "Entity Score",
    "Environment Score",
    "Causal Score",
    "Certification",
    "Accessibility",
    "Date",
    "Model Link",
    "Sampled by",
    "Evaluated by",
]


def empty_results() -> pd.DataFrame:
    return pd.DataFrame(columns=ALL_COLUMNS)


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for column in ALL_COLUMNS:
        if column not in df.columns:
            df[column] = 0 if column in NUMERIC_COLUMNS or column == "Rank" else ""
    return df[ALL_COLUMNS]


def clean_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    return df


def read_results_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    return clean_numeric_columns(ensure_columns(df))


def load_seed_results(reason: str) -> tuple[pd.DataFrame, str]:
    if SEED_RESULTS_PATH.exists():
        try:
            df = read_results_csv(SEED_RESULTS_PATH)
            return (
                df,
                f"{reason}\n\nUsing bundled seed results from Table 2 of the MBench paper.",
            )
        except Exception as exc:
            return empty_results(), f"{reason}\n\nCould not read bundled seed results: {exc}"
    return empty_results(), f"{reason}\n\nBundled seed results are missing."


def load_remote_results() -> tuple[pd.DataFrame, str]:
    try:
        snapshot_download(
            repo_id=LEADERBOARD_REPO,
            repo_type="dataset",
            local_dir=str(LOCAL_LEADERBOARD_PATH),
        )
    except Exception as exc:
        message = (
            "Leaderboard data is not available yet. Please run "
            "`python scripts/upload_seed_results.py` after setting `HF_TOKEN`."
            f"\n\nDetails: {exc}"
        )
        return load_seed_results(message)

    if not RESULTS_PATH.exists():
        message = (
            "`results.csv` was not found in the leaderboard data repo. Please run "
            "`python scripts/upload_seed_results.py` to initialize it."
        )
        return load_seed_results(message)

    try:
        df = read_results_csv(RESULTS_PATH)
    except Exception as exc:
        return load_seed_results(f"Could not read `results.csv`: {exc}")

    return df, f"Loaded results from `{LEADERBOARD_REPO}`."


def prepare_leaderboard(
    model_type: str,
    selected_metrics: list[str] | None,
) -> tuple[pd.DataFrame, str]:
    df, status = load_remote_results()

    if model_type and model_type != "All" and not df.empty:
        df = df[df["Model Type"] == model_type].copy()

    if not df.empty:
        df = df.sort_values(
            by="Total M-Score",
            ascending=False,
            kind="mergesort",
        ).reset_index(drop=True)
        df["Rank"] = np.arange(1, len(df) + 1)

    metrics = [metric for metric in METRIC_COLUMNS if metric in (selected_metrics or [])]
    columns = DISPLAY_INFO_COLUMNS[:6] + metrics + DISPLAY_INFO_COLUMNS[6:]
    return df[columns], status


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "model"


def get_uploaded_path(file_obj: Any) -> Path | None:
    if file_obj is None:
        return None
    if isinstance(file_obj, (str, os.PathLike)):
        return Path(file_obj)
    if isinstance(file_obj, dict):
        path = file_obj.get("path") or file_obj.get("name")
        return Path(path) if path else None
    name = getattr(file_obj, "name", None)
    return Path(name) if name else None


def safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        for member in zip_ref.infolist():
            member_path = (target_root / member.filename).resolve()
            try:
                member_path.relative_to(target_root)
            except ValueError:
                raise ValueError("ZIP contains an unsafe path.")
        zip_ref.extractall(target_root)


def read_submission_json_from_zip(zip_path: Path) -> dict:
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("Uploaded file must be a valid ZIP archive.")

    with tempfile.TemporaryDirectory(prefix="mbench_submission_") as tmp_dir:
        extract_dir = Path(tmp_dir)
        safe_extract_zip(zip_path, extract_dir)
        submission_path = extract_dir / SUBMISSION_JSON_FILENAME
        if not submission_path.is_file():
            raise ValueError(
                f"Submission ZIP must contain {SUBMISSION_JSON_FILENAME} at the root."
            )

        with submission_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"{SUBMISSION_JSON_FILENAME} must contain a JSON object.")
    return data


def require_text(value: str, label: str) -> str:
    if value is None or not str(value).strip():
        raise ValueError(f"{label} is required.")
    return str(value).strip()


def ensure_submission_dirs() -> None:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    VERIFIED_DIR.mkdir(parents=True, exist_ok=True)
    (PENDING_DIR / ".gitkeep").touch(exist_ok=True)
    (VERIFIED_DIR / ".gitkeep").touch(exist_ok=True)


def ensure_local_results_file() -> None:
    if RESULTS_PATH.exists() or not SEED_RESULTS_PATH.exists():
        return
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SEED_RESULTS_PATH, RESULTS_PATH)


def save_pending_submission(
    zip_path: Path,
    result_json: dict,
    model_name: str,
    model_link: str,
    team_name: str,
    contact_email: str,
    model_type: str,
    accessibility: str,
) -> tuple[Path, Path]:
    ensure_submission_dirs()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_model_name = sanitize_filename(model_name)
    stem = f"{timestamp}_{safe_model_name}"

    payload = {
        "submitted_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "model_name": model_name,
        "model_link": model_link,
        "team_name": team_name,
        "contact_email": contact_email,
        "model_type": model_type,
        "accessibility": accessibility,
        "result_json": result_json,
    }

    json_path = PENDING_DIR / f"{stem}.json"
    raw_zip_path = PENDING_DIR / f"{stem}.zip"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    shutil.copyfile(zip_path, raw_zip_path)
    return json_path, raw_zip_path


def upload_pending_submission(
    token: str,
    model_name: str,
    json_path: Path,
    zip_path: Path,
) -> None:
    api = HfApi(token=token)
    operations = [
        CommitOperationAdd(
            path_in_repo=json_path.relative_to(LOCAL_LEADERBOARD_PATH).as_posix(),
            path_or_fileobj=str(json_path),
        ),
        CommitOperationAdd(
            path_in_repo=zip_path.relative_to(LOCAL_LEADERBOARD_PATH).as_posix(),
            path_or_fileobj=str(zip_path),
        ),
    ]
    api.create_commit(
        repo_id=LEADERBOARD_REPO,
        repo_type="dataset",
        operations=operations,
        commit_message=f"Add pending MBench submission for {model_name}",
    )


def submit_result(
    zip_file: Any,
    model_name: str,
    model_link: str,
    team_name: str,
    contact_email: str,
    model_type: str,
    accessibility: str,
) -> str:
    token = os.environ.get("HF_TOKEN")
    if not token:
        return "HF_TOKEN is not set. Please add it in Space Settings -> Secrets."

    try:
        model_name = require_text(model_name, "Model name")
        model_link = require_text(model_link, "Model link")
        contact_email = require_text(contact_email, "Contact email")
        team_name = str(team_name or "").strip()
        accessibility = str(accessibility or "Unknown").strip()

        if model_type not in MODEL_TYPE_CHOICES[1:]:
            raise ValueError("Model type must be text-conditioned or action-conditioned.")

        zip_path = get_uploaded_path(zip_file)
        if zip_path is None or not zip_path.exists():
            raise ValueError("Please upload a ZIP file.")

        result_json = read_submission_json_from_zip(zip_path)
        ok, message = validate_submission_json(result_json)
        if not ok:
            raise ValueError(message)

        # Refresh the local dataset checkout before adding the pending submission.
        try:
            snapshot_download(
                repo_id=LEADERBOARD_REPO,
                repo_type="dataset",
                local_dir=str(LOCAL_LEADERBOARD_PATH),
                token=token,
            )
        except Exception:
            ensure_submission_dirs()

        ensure_local_results_file()
        pending_json_path, pending_zip_path = save_pending_submission(
            zip_path=zip_path,
            result_json=result_json,
            model_name=model_name,
            model_link=model_link,
            team_name=team_name,
            contact_email=contact_email,
            model_type=model_type,
            accessibility=accessibility,
        )
        upload_pending_submission(
            token,
            model_name,
            pending_json_path,
            pending_zip_path,
        )
    except Exception as exc:
        return f"Submission failed: {exc}"

    return "Submission received. It is pending official verification."


def about_markdown() -> str:
    return """
# About MBench

MBench is a benchmark for evaluating the memory capability of video world models. It focuses on whether a model can preserve a coherent world state across long-horizon video continuation and interaction.

The benchmark is organized around three core memory dimensions:

- **Entity Consistency:** persistent object and human identity, geometry, texture, and appearance.
- **Environment Consistency:** stable spatial layout, reprojection behavior, lighting, and style.
- **Causal Consistency:** reliable state evolution and interaction consequences over time.

*Note: Submitted leaderboard results are not automatically shown. They are saved as 'pending' and only shown here after official verification by the MBench team.*
"""


def build_header_html() -> str:
    return f"""
<section class="mbench-hero">
  <div>
    <div class="mbench-kicker">Video World Model Memory Benchmark</div>
    <h1>🏆 MBench Leaderboard</h1>
    <p>
      MBench evaluates the memory capability of video world models, focusing on whether a model can preserve a coherent world state across long-horizon video continuation and interaction.<br>
      Here we display official leaderboard scores loaded from <code>{LEADERBOARD_REPO}</code>.
    </p>
  </div>
  <div class="mbench-links">
    <a href="https://peanutup.github.io/MBench-project/" target="_blank">Project</a>
    <a href="https://github.com/study-overflow/MBench" target="_blank">GitHub</a>
    <a href="https://huggingface.co/datasets/{LEADERBOARD_REPO}" target="_blank">Data</a>
  </div>
</section>
"""


def build_summary_html(df: pd.DataFrame) -> str:
    if df.empty:
        return """
<div class="mbench-stats">
  <div><span>Models</span><strong>0</strong></div>
  <div><span>Top M-Score</span><strong>-</strong></div>
  <div><span>Text-conditioned</span><strong>0</strong></div>
  <div><span>Action-conditioned</span><strong>0</strong></div>
</div>
"""

    top_score = pd.to_numeric(df["Total M-Score"], errors="coerce").max()
    text_count = int((df["Model Type"] == "text-conditioned").sum())
    action_count = int((df["Model Type"] == "action-conditioned").sum())
    return f"""
<div class="mbench-stats">
  <div><span>Models</span><strong>{len(df)}</strong></div>
  <div><span>Top M-Score</span><strong>{top_score:.2f}</strong></div>
  <div><span>Text-conditioned</span><strong>{text_count}</strong></div>
  <div><span>Action-conditioned</span><strong>{action_count}</strong></div>
</div>
"""


def build_demo() -> gr.Blocks:
    initial_df, initial_status = prepare_leaderboard("All", DEFAULT_VISIBLE_METRICS)

    css = """
    .mbench-hero { padding-bottom: 20px; border-bottom: 1px solid #eaeaea; margin-bottom: 20px; }
    .mbench-kicker { font-size: 12px; font-weight: bold; text-transform: uppercase; color: #888; margin-bottom: 5px; }
    .mbench-hero h1 { font-size: 2.5rem; margin: 0 0 10px 0; font-weight: 800; }
    .mbench-hero p { font-size: 1rem; color: #444; margin: 0 0 15px 0; max-width: 800px; }
    .mbench-links { display: flex; gap: 10px; flex-wrap: wrap; }
    .mbench-links a { text-decoration: none; padding: 6px 12px; border: 1px solid #ddd; background: #fafafa; border-radius: 6px; color: #333; font-weight: 500; }
    .mbench-links a:hover { background: #eee; }
    /* Decrease line height in the dataframe */
    #leaderboard-table table td, #leaderboard-table table th {
      padding: 6px 10px !important;
      line-height: 1.3 !important;
    }
        #leaderboard-table table th:nth-child(2),
        #leaderboard-table table td:nth-child(2) {
            min-width: 240px !important;
            max-width: 320px !important;
            white-space: normal !important;
            word-break: break-word !important;
        }
        /* Model Type */
        #leaderboard-table table th:nth-child(3),
        #leaderboard-table table td:nth-child(3) {
            min-width: 140px !important;
            max-width: 160px !important;
            white-space: normal !important;
        }
        /* Total M-Score */
        #leaderboard-table table th:nth-child(4),
        #leaderboard-table table td:nth-child(4) {
            min-width: 130px !important;
            font-weight: 600 !important;
        }
    #controls-row {
      align-items: end;
    }
    .toggle-btn { margin-bottom: 2px !important; }
    
    /* Make the whole column header clickable for sorting */
    #leaderboard-table table th {
      position: relative;
    }
    #leaderboard-table table th .sort-button::after {
      content: "";
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      cursor: pointer;
    }
    /* Prevent the descending sort class from shrinking the clickable area by forming a new containing block */
    #leaderboard-table table th .sort-button.des {
      transform: none !important;
    }
    #leaderboard-table table th .sort-button.des svg {
      transform: scaleY(-1);
    }
    """

    with gr.Blocks(
        title="MBench Leaderboard",
        theme=gr.themes.Default(primary_hue="purple"),
        css=css,
    ) as demo:
        with gr.Tab("Leaderboard"):
            gr.HTML(build_header_html())
            gr.Markdown(about_markdown())
            status = gr.Markdown(initial_status, elem_id="status-line")

            with gr.Row(elem_id="controls-row"):
                with gr.Column(scale=5):
                    model_type_filter = gr.Radio(
                        choices=MODEL_TYPE_CHOICES,
                        value="All",
                        label="Model Type (Filter)",
                    )
                    metric_selector = gr.CheckboxGroup(
                        choices=METRIC_COLUMNS,
                        value=DEFAULT_VISIBLE_METRICS,
                        label="Detailed Metrics (Select to show in table)",
                    )
                with gr.Column(scale=1, min_width=120):
                    toggle_metrics_btn = gr.Button("✗ Deselect All", size="sm", elem_classes=["toggle-btn"])
                    refresh_button = gr.Button("↻ Refresh", size="sm")

            def toggle_metrics(current):
                if len(current) == len(METRIC_COLUMNS):
                    return gr.update(value=[]), "✓ Select All"
                else:
                    return gr.update(value=METRIC_COLUMNS), "✗ Deselect All"
            
            toggle_metrics_btn.click(
                fn=toggle_metrics,
                inputs=[metric_selector],
                outputs=[metric_selector, toggle_metrics_btn],
            )

            leaderboard_table = gr.Dataframe(
                value=initial_df,
                label="MBench Results",
                interactive=False,
                wrap=True,
                height=560,
                elem_id="leaderboard-table",
            )

            refresh_button.click(
                fn=prepare_leaderboard,
                inputs=[model_type_filter, metric_selector],
                outputs=[leaderboard_table, status],
                api_name="refresh_leaderboard",
            )
            model_type_filter.change(
                fn=prepare_leaderboard,
                inputs=[model_type_filter, metric_selector],
                outputs=[leaderboard_table, status],
                api_name=False,
            )
            metric_selector.change(
                fn=prepare_leaderboard,
                inputs=[model_type_filter, metric_selector],
                outputs=[leaderboard_table, status],
                api_name=False,
            )

        with gr.Tab("Submit"):
            gr.Markdown(SUBMIT_INTRO, elem_id="submit-intro")
            with gr.Row(elem_id="submit-panel"):
                with gr.Column():
                    zip_input = gr.File(
                        label="Submission ZIP",
                        file_types=[".zip"],
                        type="filepath",
                    )
                    model_name_input = gr.Textbox(label="Model Name")
                    model_link_input = gr.Textbox(label="Model Link")
                    team_name_input = gr.Textbox(label="Team Name")
                    contact_email_input = gr.Textbox(label="Contact Email")
                    model_type_input = gr.Dropdown(
                        choices=MODEL_TYPE_CHOICES[1:],
                        value="text-conditioned",
                        label="Model Type",
                    )
                    accessibility_input = gr.Dropdown(
                        choices=[
                            "Open weights",
                            "API only",
                            "Closed",
                            "Research preview",
                            "Unknown",
                        ],
                        value="Unknown",
                        label="Accessibility",
                    )
                    submit_button = gr.Button(
                        "Submit",
                        variant="primary",
                        elem_id="submit-button",
                    )

                with gr.Column():
                    submit_status = gr.Markdown()

            submit_button.click(
                fn=submit_result,
                inputs=[
                    zip_input,
                    model_name_input,
                    model_link_input,
                    team_name_input,
                    contact_email_input,
                    model_type_input,
                    accessibility_input,
                ],
                outputs=submit_status,
                api_name="submit_result",
            )



    return demo


demo = build_demo()


if __name__ == "__main__":
    demo.launch(show_api=True)
