import json
from pathlib import Path
import gradio as gr
from capbencher.core import (
    estimate_bayes_accuracy,
    affine_capped_score,
    exact_binomial_pvalue,
    is_contaminated,
)

# Load evidence bundle
bundle_path = Path(__file__).parent / "evidence" / "bundle.json"
bundle_data = {}
if bundle_path.exists():
    with open(bundle_path) as f:
        bundle_data = json.load(f)


def calculate_binomial_test(k: int, n: int, num_choices: int, significance: float):
    alpha = estimate_bayes_accuracy(num_choices)
    p_val = exact_binomial_pvalue(k, n, alpha)
    flagged = is_contaminated(k, n, alpha, significance)
    accuracy_pct = (k / n) * 100.0 if n > 0 else 0.0

    status = "🚨 CONTAMINATED (Rejected H0)" if flagged else "✅ UNCONTAMINATED (Fail to reject H0)"

    return (
        f"{accuracy_pct:.2f}%",
        f"{alpha:.4f} ({alpha * 100:.1f}%)",
        f"{p_val:.6e}",
        status,
    )


def calculate_capped_score(orig_score: float, num_choices: int):
    capped = affine_capped_score(orig_score, num_choices)
    return f"{capped:.4f} ({capped * 100:.2f}%)"


with gr.Blocks(title="CapBencher ICML 2026 Reproduction") as demo:
    gr.Markdown("# 🛡️ CapBencher: Benchmark Capping & Contamination Detection")
    gr.Markdown(
        "**Paper:** *How Can I Publish My LLM Benchmark Without Giving the True Answers Away?* (ICML 2026)\n"
        "**Authors:** Takashi Ishida, Thanawat Lodkaew, Ikko Yamane | **Paper ID:** `oCNT5PcMSQ`\n"
        "**Reproduction Space:** `wrice/repro-capbencher-ocnt5pcmsq`"
    )

    with gr.Tab("Target Claims & Reproduced Evidence"):
        gr.JSON(label="Canonical Evidence Bundle", value=bundle_data)

    with gr.Tab("Exact Binomial Contamination Calculator"):
        gr.Markdown("### Interactive One-Sided Exact Binomial Test (Section 4)")
        with gr.Row():
            k_input = gr.Number(label="Correct Predictions (k)", value=565, precision=0)
            n_input = gr.Number(label="Total Questions (n)", value=1000, precision=0)
            choices_input = gr.Slider(label="Answer Choices per Question (K)", minimum=2, maximum=10, value=2, step=1)
            sig_input = gr.Number(label="Significance Level (alpha)", value=0.05)

        calc_btn = gr.Button("Run Contamination Test")

        with gr.Row():
            acc_output = gr.Textbox(label="Model Accuracy")
            cap_output = gr.Textbox(label="Bayes Accuracy Cap (1/K)")
            pval_output = gr.Textbox(label="Exact Binomial P-Value")
            status_output = gr.Textbox(label="Contamination Verdict")

        calc_btn.click(
            calculate_binomial_test,
            inputs=[k_input, n_input, choices_input, sig_input],
            outputs=[acc_output, cap_output, pval_output, status_output],
        )

    with gr.Tab("Score Mapping (Theorem 1)"):
        gr.Markdown("### Monotonic Affine Score Mapping")
        with gr.Row():
            orig_score_input = gr.Slider(label="Original Benchmark Score", minimum=0.0, maximum=1.0, value=0.75, step=0.01)
            k_choices_input = gr.Slider(label="Answer Choices per Question (K)", minimum=2, maximum=10, value=2, step=1)

        map_btn = gr.Button("Calculate Capped Score")
        capped_output = gr.Textbox(label="Expected Capped Benchmark Score")

        map_btn.click(
            calculate_capped_score,
            inputs=[orig_score_input, k_choices_input],
            outputs=[capped_output],
        )

if __name__ == "__main__":
    demo.launch()
