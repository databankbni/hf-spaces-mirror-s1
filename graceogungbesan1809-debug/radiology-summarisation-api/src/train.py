"""
train.py

Fine-tunes FLAN-T5-base on radiology findings -> impression pairs.

Runs on CPU or GPU automatically (PyTorch device detection). For actual
training, a GPU runtime (e.g. Google Colab T4) is strongly recommended --
running this on CPU locally is mainly useful for verifying the pipeline
structure end-to-end.

NOTE ON RUNTIME:
    Training for the full 25 epochs on CPU is very slow (can take hours
    to days depending on hardware) and is NOT recommended. If running
    locally on CPU, reduce NUM_EPOCHS to 1 (or pass num_train_epochs=1
    to Seq2SeqTrainingArguments) purely to confirm the pipeline runs
    end-to-end without errors. The actual full training run for this
    project was performed on Google Colab using a T4 GPU.

Usage:
    python src/train.py

Expects:
    data/processed_reports.csv  (produced by src/preprocess.py)

Produces:
    model/  (fine-tuned model + tokenizer saved here)
"""

import os
import pandas as pd
import torch
from datasets import Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
    DataCollatorForSeq2Seq,
)

DATA_PATH = os.path.join("data", "processed_reports.csv")
MODEL_NAME = "google/flan-t5-base"
OUTPUT_DIR = "model"

MAX_INPUT_LENGTH = 512
MAX_TARGET_LENGTH = 32
NUM_EPOCHS = 25  # NOTE: reduce to 1 if testing locally on CPU -- 25 epochs on CPU is very slow
LEARNING_RATE = 5e-5

PROMPT_PREFIX = "generate a concise clinical impression from these radiology findings: "


def load_dataset(data_path=DATA_PATH):
    df = pd.read_csv(data_path)
    df = df.dropna(subset=["findings", "impression"])
    print(f"Loaded {len(df)} training examples from {data_path}")
    return Dataset.from_pandas(df[["findings", "impression"]])


def preprocess_function(examples, tokenizer):
    inputs = [PROMPT_PREFIX + text for text in examples["findings"]]
    model_inputs = tokenizer(
        inputs, max_length=MAX_INPUT_LENGTH, truncation=True
    )

    labels = tokenizer(
        text_target=examples["impression"],
        max_length=MAX_TARGET_LENGTH,
        truncation=True,
    )

    model_inputs["labels"] = labels["input_ids"]
    return model_inputs


def run_training(data_path=DATA_PATH, output_dir=OUTPUT_DIR):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    dataset = load_dataset(data_path)
    dataset = dataset.train_test_split(test_size=0.1, seed=42)

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, legacy=False)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME).to(device)

    tokenized_dataset = dataset.map(
        lambda examples: preprocess_function(examples, tokenizer),
        batched=True,
        remove_columns=dataset["train"].column_names,
    )

    data_collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer, model=model
    )

    training_args = Seq2SeqTrainingArguments(
        output_dir=output_dir,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        learning_rate=LEARNING_RATE,
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        predict_with_generate=True,
        load_best_model_at_end=True,
        logging_steps=50,
        report_to="none",
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset["train"],
        eval_dataset=tokenized_dataset["test"],
        processing_class=tokenizer,
        data_collator=data_collator,
    )

    trainer.train()

    os.makedirs(output_dir, exist_ok=True)
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"Model and tokenizer saved to {output_dir}")


if __name__ == "__main__":
    run_training()
