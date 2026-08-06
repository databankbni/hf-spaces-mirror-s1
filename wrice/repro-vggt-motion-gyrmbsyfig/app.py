from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
BUNDLE_PATH = PROJECT_ROOT / "evidence" / "bundle.json"


def load_bundle() -> dict:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


def render_markdown() -> str:
    bundle = load_bundle()
    paper = bundle["paper"]
    lines = [
        f"# {paper['title']}",
        "",
        f"- Paper ID: `{paper['paper_id']}`",
        f"- Attempt ID: `{paper['attempt_id']}`",
        f"- Primary artifact: `{bundle['upstream']['primary_artifact']}`",
        f"- ArXiv source SHA256: `{bundle['upstream']['arxiv_source_sha256']}`",
        f"- Paid API cost: `${bundle['estimated_paid_api_cost_usd']:.2f}`",
        "",
        "## Claim Results",
    ]
    for claim in bundle["claims"]:
        lines.extend(["", f"### `{claim['verdict']}`", claim["claim"], "", claim["evidence"]])
    lines.extend(
        [
            "",
            "## Limits",
            "",
            "- No official implementation repository, checkpoints, or benchmark logs were available.",
            "- Quantitative table checks are source audits, not independent SLAM reruns.",
        ]
    )
    return "\n".join(lines)


try:
    import gradio as gr

    demo = gr.Interface(
        fn=render_markdown,
        inputs=None,
        outputs=gr.Markdown(),
        title="VGGT-Motion Evidence",
    )
except Exception:  # pragma: no cover
    demo = None


if __name__ == "__main__":
    if demo is None:
        print(render_markdown())
    else:
        demo.launch()
