"""
run_pipeline.py

Single entry point that orchestrates the full radiology summarisation
pipeline in the correct order:

    1. preprocess  -- parses raw XML reports -> data/processed_reports.csv
    2. train       -- fine-tunes FLAN-T5-base -> model/
    3. evaluate    -- computes ROUGE + BERTScore on the held-out test set

Usage:
    python run_pipeline.py

Requirements:
    - Raw XML files must be present in data/NLMCXR_reports/ecgen-radiology/
      Download the dataset from: https://openi.nlm.nih.gov
    - All dependencies must be installed:
      pip install -r requirements.txt

IMPORTANT NOTE ON RUNTIME:
    The training step (step 2) runs on CPU or GPU automatically.
    Running the full 25-epoch training on CPU is very slow (hours to days).
    It is strongly recommended to run this pipeline on a GPU environment
    such as Google Colab (T4 GPU). If testing locally on CPU, reduce
    NUM_EPOCHS in src/train.py to 1 before running this script.
"""

import sys
import time

from src.preprocess import run_preprocessing
from src.train import run_training
from src.evaluate import run_evaluation


def run_step(step_number, step_name, fn):
    print(f"\n{'='*60}")
    print(f"STEP {step_number}: {step_name}")
    print(f"{'='*60}")
    start = time.time()
    result = fn()
    elapsed = time.time() - start
    print(f"Step {step_number} completed in {elapsed:.1f}s")
    return result


def main():
    print("\n🏥 Radiology Summarisation Pipeline")
    print("Fine-tuning FLAN-T5-base on NLM Chest X-ray reports")
    print(f"{'='*60}")

    try:
        run_step(1, "Preprocessing XML reports", run_preprocessing)
        run_step(2, "Training FLAN-T5-base model", run_training)
        results = run_step(3, "Evaluating model performance", run_evaluation)

        print(f"\n{'='*60}")
        print("PIPELINE COMPLETE — Final Evaluation Results")
        print(f"{'='*60}")
        print(f"  ROUGE-1:      {results['rouge1']:.4f}")
        print(f"  ROUGE-2:      {results['rouge2']:.4f}")
        print(f"  ROUGE-L:      {results['rougeL']:.4f}")
        print(f"  BERTScore F1: {results['bertscore_f1']:.4f}")
        print(f"{'='*60}\n")

    except FileNotFoundError as e:
        print(f"\n❌ Pipeline failed: {e}")
        print("Please check the setup instructions in the README.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
