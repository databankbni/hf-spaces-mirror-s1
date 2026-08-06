"""
evaluate.py

Evaluates the fine-tuned FLAN-T5 model (saved by src/train.py) on a
held-out test split, reporting ROUGE-1/2/L and BERTScore F1.

Usage:
    python src/evaluate.py

Expects:
    data/processed_reports.csv  (produced by src/preprocess.py)
    model/                      (fine-tuned model + tokenizer, produced by src/train.py)

Produces:
    Printed evaluation metrics (ROUGE-1, ROUGE-2, ROUGE-L, BERTScore F1)
"""

import os
import pandas as pd
import torch
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import evaluate as hf_evaluate

DATA_PATH = os.path.join("data", "processed_reports.csv")
MODEL_DIR = "model"

MAX_INPUT_LENGTH = 512
MAX_NEW_TOKENS = 64
NUM_BEAMS = 4
LENGTH_PENALTY = 2.0
NO_REPEAT_NGRAM_SIZE = 3

PROMPT_PREFIX = "generate a concise clinical impression from these radiology findings: "


def load_test_split(data_path=DATA_PATH, test_size=0.1, seed=42):
    df = pd.read_csv(data_path)
    df = df.dropna(subset=["findings", "impression"])
    dataset = Dataset.from_pandas(df[["findings", "impression"]])
    split = dataset.train_test_split(test_size=test_size, seed=seed)
    print(f"Evaluating on {len(split['test'])} held-out test examples")
    return split["test"]


def generate_predictions(test_dataset, tokenizer, model, device):
    predictions = []
    references = []

    for example in test_dataset:
        prompt = PROMPT_PREFIX + example["findings"]
        inputs = tokenizer(
            prompt, return_tensors="pt", truncation=True, max_length=MAX_INPUT_LENGTH
        ).to(device)

        output_ids = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            num_beams=NUM_BEAMS,
            length_penalty=LENGTH_PENALTY,
            no_repeat_ngram_size=NO_REPEAT_NGRAM_SIZE,
            early_stopping=True,
        )

        prediction = tokenizer.decode(output_ids[0], skip_special_tokens=True)
        predictions.append(prediction)
        references.append(example["impression"])

    return predictions, references


def run_evaluation(data_path=DATA_PATH, model_dir=MODEL_DIR):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    test_dataset = load_test_split(data_path)

    tokenizer = AutoTokenizer.from_pretrained(model_dir, legacy=False)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_dir).to(device)
    model.eval()

    predictions, references = generate_predictions(test_dataset, tokenizer, model, device)

    rouge = hf_evaluate.load("rouge")
    rouge_scores = rouge.compute(predictions=predictions, references=references)

    bertscore = hf_evaluate.load("bertscore")
    bertscore_result = bertscore.compute(
        predictions=predictions, references=references, lang="en"
    )
    bertscore_f1 = sum(bertscore_result["f1"]) / len(bertscore_result["f1"])

    print("\n--- Evaluation Results ---")
    print(f"ROUGE-1: {rouge_scores['rouge1']:.4f}")
    print(f"ROUGE-2: {rouge_scores['rouge2']:.4f}")
    print(f"ROUGE-L: {rouge_scores['rougeL']:.4f}")
    print(f"BERTScore F1: {bertscore_f1:.4f}")

    return {
        "rouge1": rouge_scores["rouge1"],
        "rouge2": rouge_scores["rouge2"],
        "rougeL": rouge_scores["rougeL"],
        "bertscore_f1": bertscore_f1,
    }


if __name__ == "__main__":
    run_evaluation()
