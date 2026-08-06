import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = PROJECT_ROOT / "generate_evidence.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("vggt_motion_generate", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_motion_state_classifier_and_partitioning_preserve_turns():
    module = load_generator()

    states = module.classify_motion(
        static_ratios=[0.95, 0.92, 0.20, 0.10, 0.15, 0.12, 0.25, 0.90],
        turn_scores=[0.1, 0.2, 6.5, 7.1, 6.7, 1.1, 0.9, 0.2],
        tau_static=0.6,
        tau_turn=5.0,
    )
    assert states == ["S", "S", "T", "T", "T", "L", "L", "S"]

    submaps = module.motion_aware_submaps(
        states=states,
        parallaxes=[0.0, 0.2, 3.0, 4.5, 5.5, 16.0, 8.0, 0.1],
        n_max=3,
        tau_parallax=15.0,
    )
    assert [2, 3, 4] in submaps
    assert all(not ({2, 3, 4} - set(submap)) for submap in submaps if 2 in submap)


def test_sim3_estimator_recovers_synthetic_alignment():
    module = load_generator()

    source, target, estimate = module.synthetic_sim3_case()
    aligned = module.apply_sim3(source, estimate)
    residual = float(((aligned - target) ** 2).sum(axis=1).mean() ** 0.5)
    assert residual < 1e-9
    assert abs(estimate["scale"] - 1.75) < 1e-9


def test_evidence_bundle_claims_and_limits(tmp_path):
    module = load_generator()
    output = tmp_path / "bundle.json"
    bundle = module.build_bundle()
    module.write_bundle(bundle, output)
    saved = json.loads(output.read_text())

    assert saved["paper"]["paper_id"] == "GyRMbsYFiG"
    assert saved["upstream"]["arxiv_source_sha256"] == (
        "217fb93bc9b847cef3402395b9b6f97665051aea4872b4785c896fb79fb73b44"
    )
    assert len(saved["claims"]) == 6
    verdicts = {claim["challenge_claim_sha256"]: claim["verdict"] for claim in saved["claims"]}
    assert verdicts["ebc904f759989d500c93913210a4d89954834a560ba0568ef469ddc28566a82c"] == "toy"
    assert verdicts["b2ca94dae5c811e35f6943d2af6b67fb83e2f7e03ec8f3ecb42766e13bcc9ce3"] == "toy"
    assert verdicts["ab3dd21bf3b25d44ffc41f9d84a47993e6b15254326b95fdb60d48a4dc4e734c"] == "inconclusive"

    assert saved["checks"]["kitti_avg_star"]["ours"] == 18.26
    assert saved["checks"]["kitti_avg_star"]["vggt_long"] == 18.28
    assert saved["checks"]["generalization_vggt_long_reduction"]["ate_reductions"]
    assert saved["limitations"]["official_code_released"] is False


def test_space_pages_surface_has_summary_and_claims_pages():
    pages = sorted((PROJECT_ROOT / "pages").glob("*.md"))

    assert len(pages) >= 2
    assert all(page.read_text(encoding="utf-8").strip() for page in pages)
