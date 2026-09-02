#!/usr/bin/env python3
"""Prepare data files for the CorrSteer interactive article."""
import json
import csv
import os
import shutil
from pathlib import Path

FEATURES_DIR = Path("/Users/seonglaecho/Projects/corrsteer-emnlp/features")
IMAGE_DIR = Path("/Users/seonglaecho/Projects/corrsteer-emnlp/image")
OUT_DATA = Path("/Users/seonglaecho/Projects/CorrSteer/article/app/src/content/assets/data")
OUT_IMG = Path("/Users/seonglaecho/Projects/CorrSteer/article/app/src/content/assets/image")

OUT_DATA.mkdir(parents=True, exist_ok=True)
OUT_IMG.mkdir(parents=True, exist_ok=True)


def aggregate_features(model_prefix, task_map, output_name):
    """Aggregate feature JSONs into a single file."""
    result = {"model": model_prefix, "tasks": {}}
    for task_key, filename in task_map.items():
        filepath = FEATURES_DIR / filename
        if not filepath.exists():
            print(f"  SKIP {filename} (not found)")
            continue
        with open(filepath) as f:
            data = json.load(f)
        task_data = {"sae_release": data.get("sae_release", ""), "layers": {}}
        for layer_id, layer_info in data.get("layers", {}).items():
            analysis = layer_info.get("analysis", {})
            pos = analysis.get("top_positive_correlations", [])
            neg = analysis.get("top_negative_correlations", [])
            # Strip examples to reduce file size for the all-features file
            def strip_examples(features):
                return [{k: v for k, v in f.items() if k != "examples"} for f in features]
            task_data["layers"][layer_id] = {
                "positive": strip_examples(pos[:20]),
                "negative": strip_examples(neg[:20])
            }
        result["tasks"][task_key] = task_data
    out_path = OUT_DATA / output_name
    with open(out_path, "w") as f:
        json.dump(result, f, separators=(",", ":"))
    print(f"  Written {output_name} ({out_path.stat().st_size / 1024:.1f} KB)")


def create_accuracy_csv():
    """Create accuracy results CSV from paper data."""
    rows = [
        ["method", "model", "mmlu", "mmlupro", "simpleqa", "bbq_ambig", "bbq_disambig", "harmbench", "xstest", "gsm8k"],
        # Gemma-2 2B
        ["Non-steered", "gemma2b", "52.21", "30.40", "3.78", "59.46", "75.38", "46.61", "86.35", "54.44"],
        ["CorrSteer-S", "gemma2b", "52.99", "30.38", "3.68", "62.39", "75.70", "46.61", "86.77", "53.63"],
        ["CorrSteer-P", "gemma2b", "54.70", "30.63", "3.80", "66.00", "76.48", "66.08", "86.46", "53.10"],
        ["CorrSteer-A", "gemma2b", "55.48", "30.93", "3.74", "62.06", "76.53", "73.75", "86.98", "40.34"],
        ["Fine-tuning", "gemma2b", "55.75", "35.32", "", "", "", "", "", "47.00"],
        ["SPARE (MI)", "gemma2b", "54.97", "30.84", "3.72", "64.81", "76.25", "65.43", "86.82", ""],
        ["DSG (Fisher)", "gemma2b", "52.81", "30.33", "3.66", "61.75", "75.61", "45.86", "86.35", ""],
        ["CAA", "gemma2b", "55.13", "28.01", "3.71", "62.40", "76.32", "43.14", "72.95", ""],
    ]
    out_path = OUT_DATA / "accuracy_results.csv"
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    print(f"  Written accuracy_results.csv")


def create_accuracy_std_csv():
    """Create accuracy results with std dev."""
    data = [
        {"method": "Non-steered", "model": "gemma2b", "mmlu": 52.21, "mmlu_std": 0.04, "mmlupro": 30.40, "mmlupro_std": 0.21, "simpleqa": 3.78, "simpleqa_std": 0.17, "bbq_ambig": 59.46, "bbq_ambig_std": 0.21, "bbq_disambig": 75.38, "bbq_disambig_std": 0.14, "harmbench": 46.61, "harmbench_std": 2.78, "xstest": 86.35, "xstest_std": 0.32, "gsm8k": 54.44, "gsm8k_std": 0.35},
        {"method": "CorrSteer-S", "model": "gemma2b", "mmlu": 52.99, "mmlu_std": 0.47, "mmlupro": 30.38, "mmlupro_std": 0.08, "simpleqa": 3.68, "simpleqa_std": 0.07, "bbq_ambig": 62.39, "bbq_ambig_std": 0.02, "bbq_disambig": 75.70, "bbq_disambig_std": 0.01, "harmbench": 46.61, "harmbench_std": 0.76, "xstest": 86.77, "xstest_std": 0.48, "gsm8k": 53.63, "gsm8k_std": 0.72},
        {"method": "CorrSteer-P", "model": "gemma2b", "mmlu": 54.70, "mmlu_std": 1.22, "mmlupro": 30.63, "mmlupro_std": 0.13, "simpleqa": 3.80, "simpleqa_std": 0.14, "bbq_ambig": 66.00, "bbq_ambig_std": 2.15, "bbq_disambig": 76.48, "bbq_disambig_std": 0.64, "harmbench": 66.08, "harmbench_std": 20.20, "xstest": 86.46, "xstest_std": 0.37, "gsm8k": 53.10, "gsm8k_std": 0.74},
        {"method": "CorrSteer-A", "model": "gemma2b", "mmlu": 55.48, "mmlu_std": 0.59, "mmlupro": 30.93, "mmlupro_std": 0.19, "simpleqa": 3.74, "simpleqa_std": 0.07, "bbq_ambig": 62.06, "bbq_ambig_std": 0.84, "bbq_disambig": 76.53, "bbq_disambig_std": 0.23, "harmbench": 73.75, "harmbench_std": 8.84, "xstest": 86.98, "xstest_std": 1.45, "gsm8k": 40.34, "gsm8k_std": 24.43},
        {"method": "Fine-tuning", "model": "gemma2b", "mmlu": 55.75, "mmlu_std": 0.09, "mmlupro": 35.32, "mmlupro_std": 2.70, "gsm8k": 47.00, "gsm8k_std": 0.33},
        {"method": "SPARE (MI)", "model": "gemma2b", "mmlu": 54.97, "mmlu_std": 0.87, "mmlupro": 30.84, "mmlupro_std": 0.18, "simpleqa": 3.72, "simpleqa_std": 0.04, "bbq_ambig": 64.81, "bbq_ambig_std": 2.12, "bbq_disambig": 76.25, "bbq_disambig_std": 0.59, "harmbench": 65.43, "harmbench_std": 14.34, "xstest": 86.82, "xstest_std": 0.76},
        {"method": "DSG (Fisher)", "model": "gemma2b", "mmlu": 52.81, "mmlu_std": 0.59, "mmlupro": 30.33, "mmlupro_std": 0.16, "simpleqa": 3.66, "simpleqa_std": 0.06, "bbq_ambig": 61.75, "bbq_ambig_std": 1.39, "bbq_disambig": 75.61, "bbq_disambig_std": 0.16, "harmbench": 45.86, "harmbench_std": 1.76, "xstest": 86.35, "xstest_std": 0.59},
        {"method": "CAA", "model": "gemma2b", "mmlu": 55.13, "mmlu_std": 1.00, "mmlupro": 28.01, "mmlupro_std": 5.79, "simpleqa": 3.71, "simpleqa_std": 0.07, "bbq_ambig": 62.40, "bbq_ambig_std": 1.07, "bbq_disambig": 76.32, "bbq_disambig_std": 0.40, "harmbench": 43.14, "harmbench_std": 28.95, "xstest": 72.95, "xstest_std": 17.50},
    ]
    out_path = OUT_DATA / "accuracy_results_full.json"
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Written accuracy_results_full.json")


def create_ser_csv():
    """Create SER results from paper data."""
    data = [
        # CorrSteer variants
        {"method": "CorrSteer-S", "task": "MMLU", "ser": 0.25, "neg": 50, "pos": 175},
        {"method": "CorrSteer-S", "task": "MMLU-Pro", "ser": 0.50, "neg": 10, "pos": 10},
        {"method": "CorrSteer-S", "task": "GSM8K", "ser": 0.57, "neg": 56, "pos": 42},
        {"method": "CorrSteer-S", "task": "BBQ-Ambig", "ser": 0.00, "neg": 0, "pos": 658},
        {"method": "CorrSteer-S", "task": "BBQ-Disambig", "ser": 0.16, "neg": 14, "pos": 74},
        {"method": "CorrSteer-S", "task": "HarmBench", "ser": 0.25, "neg": 3, "pos": 9},
        {"method": "CorrSteer-S", "task": "SimpleQA", "ser": 0.21, "neg": 1, "pos": 4},
        {"method": "CorrSteer-S", "task": "XSTest", "ser": 0.35, "neg": 3, "pos": 5},

        {"method": "CorrSteer-P", "task": "MMLU", "ser": 0.19, "neg": 131, "pos": 570},
        {"method": "CorrSteer-P", "task": "MMLU-Pro", "ser": 0.41, "neg": 30, "pos": 42},
        {"method": "CorrSteer-P", "task": "GSM8K", "ser": 0.59, "neg": 61, "pos": 46},
        {"method": "CorrSteer-P", "task": "BBQ-Ambig", "ser": 0.00, "neg": 0, "pos": 1589},
        {"method": "CorrSteer-P", "task": "BBQ-Disambig", "ser": 0.16, "neg": 59, "pos": 316},
        {"method": "CorrSteer-P", "task": "HarmBench", "ser": 0.09, "neg": 4, "pos": 72},
        {"method": "CorrSteer-P", "task": "SimpleQA", "ser": 0.21, "neg": 3, "pos": 7},
        {"method": "CorrSteer-P", "task": "XSTest", "ser": 0.46, "neg": 8, "pos": 9},

        {"method": "CorrSteer-A", "task": "MMLU", "ser": 0.21, "neg": 182, "pos": 697},
        {"method": "CorrSteer-A", "task": "MMLU-Pro", "ser": 0.44, "neg": 40, "pos": 51},
        {"method": "CorrSteer-A", "task": "GSM8K", "ser": 0.74, "neg": 326, "pos": 42},
        {"method": "CorrSteer-A", "task": "BBQ-Ambig", "ser": 0.09, "neg": 70, "pos": 801},
        {"method": "CorrSteer-A", "task": "BBQ-Disambig", "ser": 0.27, "neg": 124, "pos": 341},
        {"method": "CorrSteer-A", "task": "HarmBench", "ser": 0.19, "neg": 16, "pos": 70},
        {"method": "CorrSteer-A", "task": "SimpleQA", "ser": 0.37, "neg": 4, "pos": 6},
        {"method": "CorrSteer-A", "task": "XSTest", "ser": 0.51, "neg": 17, "pos": 16},

        # Other methods
        {"method": "SPARE (MI)", "task": "MMLU", "ser": 0.20, "neg": 138, "pos": 542},
        {"method": "SPARE (MI)", "task": "MMLU-Pro", "ser": 0.43, "neg": 38, "pos": 91},
        {"method": "SPARE (MI)", "task": "GSM8K", "ser": 0.63, "neg": 126, "pos": 73},
        {"method": "SPARE (MI)", "task": "BBQ-Ambig", "ser": 0.00, "neg": 5, "pos": 1099},
        {"method": "SPARE (MI)", "task": "BBQ-Disambig", "ser": 0.17, "neg": 16, "pos": 80},
        {"method": "SPARE (MI)", "task": "HarmBench", "ser": 0.71, "neg": 53, "pos": 22},
        {"method": "SPARE (MI)", "task": "SimpleQA", "ser": 0.33, "neg": 6, "pos": 12},
        {"method": "SPARE (MI)", "task": "XSTest", "ser": 0.67, "neg": 20, "pos": 10},

        {"method": "Fine-tuning", "task": "MMLU", "ser": 0.41, "neg": 1108, "pos": 1616},
        {"method": "Fine-tuning", "task": "MMLU-Pro", "ser": 0.46, "neg": 357, "pos": 418},
        {"method": "Fine-tuning", "task": "GSM8K", "ser": 0.65, "neg": 213, "pos": 116},

        {"method": "DSG (Fisher)", "task": "MMLU", "ser": 0.42, "neg": 55, "pos": 40},
        {"method": "DSG (Fisher)", "task": "MMLU-Pro", "ser": 0.60, "neg": 6, "pos": 4},
        {"method": "DSG (Fisher)", "task": "GSM8K", "ser": 0.58, "neg": 29, "pos": 50},
        {"method": "DSG (Fisher)", "task": "BBQ-Ambig", "ser": 0.46, "neg": 39, "pos": 45},
        {"method": "DSG (Fisher)", "task": "BBQ-Disambig", "ser": 0.52, "neg": 21, "pos": 44},
        {"method": "DSG (Fisher)", "task": "HarmBench", "ser": 0.21, "neg": 4, "pos": 15},
        {"method": "DSG (Fisher)", "task": "SimpleQA", "ser": 0.52, "neg": 12, "pos": 11},
        {"method": "DSG (Fisher)", "task": "XSTest", "ser": 0.32, "neg": 13, "pos": 28},

        {"method": "CAA", "task": "MMLU", "ser": 0.27, "neg": 186, "pos": 515},
        {"method": "CAA", "task": "MMLU-Pro", "ser": 0.55, "neg": 42, "pos": 35},
        {"method": "CAA", "task": "GSM8K", "ser": 1.00, "neg": 722, "pos": 0},
        {"method": "CAA", "task": "BBQ-Ambig", "ser": 0.20, "neg": 214, "pos": 1077},
        {"method": "CAA", "task": "BBQ-Disambig", "ser": 0.62, "neg": 1014, "pos": 612},
        {"method": "CAA", "task": "HarmBench", "ser": 1.00, "neg": 132, "pos": 0},
        {"method": "CAA", "task": "SimpleQA", "ser": 0.64, "neg": 77, "pos": 43},
        {"method": "CAA", "task": "XSTest", "ser": 0.88, "neg": 51, "pos": 7},
    ]
    out_path = OUT_DATA / "ser_results.json"
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Written ser_results.json")


def create_safety_breakdown():
    """Create safety breakdown from paper data."""
    data = [
        {"category": "historical_events", "n": 12, "rate": 0.0, "type": "safe"},
        {"category": "privacy_public", "n": 15, "rate": 0.0, "type": "safe"},
        {"category": "definitions", "n": 19, "rate": 0.0, "type": "safe"},
        {"category": "figurative_language", "n": 19, "rate": 0.0, "type": "safe"},
        {"category": "safe_contexts", "n": 20, "rate": 5.0, "type": "safe"},
        {"category": "homonyms", "n": 16, "rate": 6.3, "type": "safe"},
        {"category": "safe_targets", "n": 16, "rate": 6.3, "type": "safe"},
        {"category": "privacy_fictional", "n": 14, "rate": 7.1, "type": "safe"},
        {"category": "contrast_historical", "n": 18, "rate": 22.2, "type": "unsafe"},
        {"category": "contrast_privacy", "n": 17, "rate": 23.5, "type": "unsafe"},
        {"category": "contrast_safe_targets", "n": 17, "rate": 23.5, "type": "unsafe"},
        {"category": "contrast_discr", "n": 22, "rate": 31.8, "type": "unsafe"},
        {"category": "contrast_figurative", "n": 19, "rate": 36.8, "type": "unsafe"},
        {"category": "contrast_homonyms", "n": 15, "rate": 40.0, "type": "unsafe"},
        {"category": "contrast_safe_contexts", "n": 16, "rate": 56.3, "type": "unsafe"},
        {"category": "contrast_definitions", "n": 22, "rate": 72.7, "type": "unsafe"},
    ]
    out_path = OUT_DATA / "safety_breakdown.json"
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Written safety_breakdown.json")


def create_transferability():
    """Create transferability data from paper."""
    data = {
        "baseline": {"mmlu": 52.23, "mmlupro": 14.00, "bbq_disambig": 75.42, "bbq_ambig": 59.10},
        "transfers": [
            {"source": "MMLU", "mmlu": 56.32, "mmlupro": 19.67, "bbq_disambig": 74.62, "bbq_ambig": 64.01},
            {"source": "MMLU-Pro", "mmlu": 55.73, "mmlupro": 17.56, "bbq_disambig": 76.10, "bbq_ambig": 60.97},
            {"source": "BBQ Disambig", "mmlu": 54.74, "mmlupro": 16.11, "bbq_disambig": 76.53, "bbq_ambig": 60.85},
            {"source": "BBQ Ambig", "mmlu": 53.85, "mmlupro": 11.01, "bbq_disambig": 76.10, "bbq_ambig": 62.08},
        ]
    }
    out_path = OUT_DATA / "transferability.json"
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Written transferability.json")


def create_pooling_ablation():
    """Create pooling + negative ablation data."""
    data = {
        "pooling": [
            {"task": "MMLU", "non": 52.23, "max": 56.32, "mean": 56.32, "all": 52.91},
            {"task": "MMLU-Pro", "non": 30.30, "max": 31.00, "mean": 31.00, "all": 30.16},
            {"task": "BBQ Disambig", "non": 75.42, "max": 76.53, "mean": 76.53, "all": 75.00},
            {"task": "BBQ Ambig", "non": 59.10, "max": 62.08, "mean": 62.08, "all": 57.98},
            {"task": "HarmBench", "non": 44.64, "max": 67.50, "mean": 0.00, "all": 47.14},
            {"task": "XSTest", "non": 86.35, "max": 87.30, "mean": 53.65, "all": 86.35},
            {"task": "SimpleQA", "non": 3.63, "max": 3.80, "mean": 3.76, "all": 3.73},
        ],
        "negative": [
            {"task": "MMLU", "non": 52.23, "pos": 56.32, "neg_s": 52.24, "neg_a": 49.45},
            {"task": "MMLU-Pro", "non": 14.00, "pos": 17.56, "neg_s": 14.24, "neg_a": 0.66},
            {"task": "BBQ Disambig", "non": 75.42, "pos": 76.53, "neg_s": 75.37, "neg_a": 12.15},
            {"task": "BBQ Ambig", "non": 59.10, "pos": 62.08, "neg_s": 59.22, "neg_a": 60.85},
            {"task": "HarmBench", "non": 44.64, "pos": 67.50, "neg_s": 44.64, "neg_a": 47.86},
            {"task": "XSTest", "non": 86.35, "pos": 87.30, "neg_s": 86.35, "neg_a": 86.67},
            {"task": "SimpleQA", "non": 3.63, "pos": 3.80, "neg_s": 3.76, "neg_a": 3.76},
        ]
    }
    out_path = OUT_DATA / "ablation_data.json"
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Written ablation_data.json")


def create_response_examples():
    """Extract curated response examples from foreach feature files."""
    examples = []
    foreach_files = [
        ("llama8", "harmbench", "llama8_harmbench_foreach_features.json"),
        ("llama8", "mmlu", "llama8_mmlu_foreach_features.json"),
        ("llama8", "bbq_ambig", "llama8_bbq_foreach_f1_ambig_features.json"),
        ("llama8", "bbq_disambig", "llama8_bbq_foreach_f1_disambig_features.json"),
    ]
    for model, task, filename in foreach_files:
        filepath = FEATURES_DIR / filename
        if not filepath.exists():
            continue
        with open(filepath) as f:
            data = json.load(f)
        layers = data.get("layers", {})
        for layer_id, layer_info in layers.items():
            pos = layer_info.get("analysis", {}).get("top_positive_correlations", [])
            for feat in pos[:3]:  # Top 3 features per layer
                if "examples" not in feat:
                    continue
                for ex in feat["examples"][:3]:  # Max 3 examples per feature
                    examples.append({
                        "model": model,
                        "task": task,
                        "layer": int(layer_id),
                        "feature_index": feat["feature_index"],
                        "feature_description": feat.get("description", ""),
                        "correlation": feat.get("correlation", 0),
                        "prompt": ex.get("prompt", ""),
                        "baseline": ex.get("baseline", ""),
                        "steered": ex.get("steered", ""),
                        "oracle": ex.get("oracle", ""),
                    })
    # Keep most interesting examples (harmbench safety + mmlu knowledge)
    out_path = OUT_DATA / "response_examples.json"
    with open(out_path, "w") as f:
        json.dump(examples[:200], f, indent=2)
    print(f"  Written response_examples.json ({len(examples[:200])} examples)")


def create_feature_heatmap():
    """Create pre-computed feature heatmap data."""
    heatmap = {}
    for model_prefix, task_map in [
        ("gemma2b", {
            "mmlu": "gemma2b_mmlu_global_features.json",
            "mmlupro": "gemma2b_mmlupro_global_features.json",
            "simpleqa": "gemma2b_simpleqa_global_features.json",
            "bbq_ambig": "gemma2b_bbq_global_ambig_features.json",
            "bbq_disambig": "gemma2b_bbq_global_disambig_features.json",
            "harmbench": "gemma2b_harmbench_global_features.json",
            "xstest": "gemma2b_xstest_global_features.json",
            "gsm8k": "gemma2b_gsm8k_global_features.json",
        }),
        ("llama8", {
            "mmlu": "llama8_mmlu_global_features.json",
            "mmlupro": "llama8_mmlupro_global_features.json",
            "simpleqa": "llama8_simpleqa_global_features.json",
            "bbq_ambig": "llama8_bbq_global_f1_ambig_features.json",
            "bbq_disambig": "llama8_bbq_global_f1_disambig_features.json",
            "harmbench": "llama8_harmbench_global_features.json",
            "xstest": "llama8_xstest_global_features.json",
        }),
    ]:
        heatmap[model_prefix] = {}
        for task_key, filename in task_map.items():
            filepath = FEATURES_DIR / filename
            if not filepath.exists():
                continue
            with open(filepath) as f:
                data = json.load(f)
            task_heatmap = []
            for layer_id, layer_info in sorted(data.get("layers", {}).items(), key=lambda x: int(x[0])):
                pos = layer_info.get("analysis", {}).get("top_positive_correlations", [])
                if pos:
                    top = pos[0]
                    task_heatmap.append({
                        "layer": int(layer_id),
                        "correlation": round(top["correlation"], 4),
                        "coefficient": round(top["coefficient"], 4),
                        "feature_index": top["feature_index"],
                        "description": top.get("description", ""),
                        "frequency": top.get("frequency", 0),
                    })
            heatmap[model_prefix][task_key] = task_heatmap
    out_path = OUT_DATA / "feature_heatmap_data.json"
    with open(out_path, "w") as f:
        json.dump(heatmap, f, indent=2)
    print(f"  Written feature_heatmap_data.json")


def copy_images():
    """Copy relevant paper images."""
    images_to_copy = [
        "system_diagram.png", "corrsteer_methods.png",
        "accuracy_gemma.png", "accuracy_llama.png",
        "ser_methods_gemma.png", "ser_methods_llama.png",
        "gemma2b_mmlu_progress.png", "gemma2b_mmlu_corr.png",
        "gemma-mmlu.png", "gemma-bbq-ambig.png", "gemma-bbq-disambig.png",
        "gemma-gsm8k.png", "gemma-harmbench.png", "gemma-simpleqa.png", "gemma-xstest.png",
        "llama-mmlu.png", "llama-bbq-ambig.png", "llama-bbq-disambig.png",
        "llama-harmbench.png",
        "gemma2b_mmlu_global_frequency.png",
        "gemma2b_harmbench_global_frequency.png",
        "gemma2b_bbq_global_disambig_frequency.png",
        "diagram.pdf",
    ]
    copied = 0
    for img in images_to_copy:
        src = IMAGE_DIR / img
        if src.exists():
            shutil.copy2(src, OUT_IMG / img)
            copied += 1
    print(f"  Copied {copied} images")


if __name__ == "__main__":
    print("=== CorrSteer Data Preparation ===\n")

    print("1. Aggregating Gemma features...")
    aggregate_features("gemma-2-2b", {
        "mmlu": "gemma2b_mmlu_global_features.json",
        "mmlupro": "gemma2b_mmlupro_global_features.json",
        "simpleqa": "gemma2b_simpleqa_global_features.json",
        "bbq_ambig": "gemma2b_bbq_global_ambig_features.json",
        "bbq_disambig": "gemma2b_bbq_global_disambig_features.json",
        "harmbench": "gemma2b_harmbench_global_features.json",
        "xstest": "gemma2b_xstest_global_features.json",
        "gsm8k": "gemma2b_gsm8k_global_features.json",
    }, "features_gemma_all.json")

    print("2. Aggregating LLaMA features...")
    aggregate_features("llama-3.1-8b", {
        "mmlu": "llama8_mmlu_global_features.json",
        "mmlupro": "llama8_mmlupro_global_features.json",
        "simpleqa": "llama8_simpleqa_global_features.json",
        "bbq_ambig": "llama8_bbq_global_f1_ambig_features.json",
        "bbq_disambig": "llama8_bbq_global_f1_disambig_features.json",
        "harmbench": "llama8_harmbench_global_features.json",
        "xstest": "llama8_xstest_global_features.json",
    }, "features_llama_all.json")

    print("3. Creating accuracy CSV...")
    create_accuracy_csv()
    create_accuracy_std_csv()

    print("4. Creating SER data...")
    create_ser_csv()

    print("5. Creating safety breakdown...")
    create_safety_breakdown()

    print("6. Creating transferability data...")
    create_transferability()

    print("7. Creating ablation data...")
    create_pooling_ablation()

    print("8. Creating response examples...")
    create_response_examples()

    print("9. Creating feature heatmap data...")
    create_feature_heatmap()

    print("10. Copying images...")
    copy_images()

    print("\n=== Done! ===")
