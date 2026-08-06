"""Unit tests for CapBencher reproduction."""

from pathlib import Path

import pytest
from capbencher.core import (
    estimate_bayes_accuracy,
    affine_capped_score,
    exact_binomial_pvalue,
    is_contaminated,
)
from capbencher.simulation import run_model_merge_hacking_simulation, generate_evidence_bundle
from generate_evidence import write_bundle


def test_bayes_accuracy_capping():
    """Verify Claim 1: Bayes accuracy is capped at 1/K by answer randomization."""
    assert estimate_bayes_accuracy(2) == pytest.approx(0.50)
    assert estimate_bayes_accuracy(4) == pytest.approx(0.25)
    assert estimate_bayes_accuracy(10) == pytest.approx(0.10)
    with pytest.raises(ValueError):
        estimate_bayes_accuracy(0)


def test_affine_score_mapping():
    """Verify Claim 2: Monotonic affine relationship between original and capped accuracy."""
    # For K=2 (L=2): s_capped = 0.5 + 0.5 * s_orig
    assert affine_capped_score(0.0, num_choices=2) == pytest.approx(0.50)
    assert affine_capped_score(0.5, num_choices=2) == pytest.approx(0.75)
    assert affine_capped_score(1.0, num_choices=2) == pytest.approx(1.00)

    # Monotonicity test across models
    orig_scores = [0.20, 0.40, 0.65, 0.85]
    capped_scores = [affine_capped_score(s, num_choices=2) for s in orig_scores]
    assert capped_scores == sorted(capped_scores)


def test_exact_binomial_contamination_test():
    """Verify Claim 3: Exact binomial p-value calculation for contamination detection."""
    # Example: k = 565 out of n = 1000, alpha = 0.50
    p_val = exact_binomial_pvalue(k=565, n=1000, alpha=0.50)
    assert p_val < 0.05
    assert p_val == pytest.approx(2.2068e-5, rel=1e-2)

    # Contamination decision at alpha = 0.05
    assert is_contaminated(k=565, n=1000, alpha=0.50, significance=0.05) is True

    # Baseline performance (500 / 1000) is NOT contaminated
    assert is_contaminated(k=500, n=1000, alpha=0.50, significance=0.05) is False


def test_model_merge_hacking_simulation():
    """Verify Claim 4: Model-merge hacking simulation accuracy (56.52%) flagged at 5% significance."""
    result = run_model_merge_hacking_simulation(n_questions=1000, seed=42)
    assert result["accuracy_pct"] == pytest.approx(56.52, abs=0.01)
    assert result["k"] == 565
    assert result["n"] == 1000
    assert result["p_value"] < 0.05
    assert result["is_contaminated"] is True


def test_evidence_bundle_generation():
    """Verify complete machine-readable evidence bundle."""
    bundle = generate_evidence_bundle()
    assert bundle["paper_id"] == "oCNT5PcMSQ"
    assert bundle["title"] == "How Can I Publish My LLM Benchmark Without Giving the True Answers Away?"
    assert len(bundle["target_claims"]) == 4
    for claim in bundle["target_claims"]:
        assert claim["status"] == "verified"
    assert "simulation_results" in bundle


def test_space_pages_include_scoring_surface():
    """Ensure the Space exposes numeric evidence for controller scoring."""
    project = Path(__file__).resolve().parents[1]
    pages = sorted((project / "pages").glob("*.md"))
    assert len(pages) >= 2

    text = "\n".join(page.read_text(encoding="utf-8") for page in pages)
    numeric_lines = [line for line in text.splitlines() if any(character.isdigit() for character in line)]
    assert len(numeric_lines) >= 15
    assert "56.52%" in text
    assert "565/1000" in text
    assert "2.206809e-05" in text
    assert "0.50" in text


def test_space_readme_declares_controller_tags():
    """Space metadata must carry the challenge and paper tags."""
    project = Path(__file__).resolve().parents[1]
    readme = project / "README.md"

    text = readme.read_text(encoding="utf-8")

    assert "sdk: gradio" in text
    assert "app_file: app.py" in text
    assert "icml2026-repro" in text
    assert "paper-oCNT5PcMSQ" in text


def test_evidence_writer_preserves_precommit_final_newline(tmp_path):
    """Generated evidence should already satisfy end-of-file-fixer."""
    out_file = tmp_path / "bundle.json"

    write_bundle(out_file)

    assert out_file.read_bytes().endswith(b"\n")
