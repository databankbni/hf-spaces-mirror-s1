"""
src/ml/modal_train.py

On-demand serverless QLoRA fine-tuning for CustomerCore LLM.
Spins up a high-powered cloud GPU (Nvidia A10G/A100) on Modal,
extracts tickets from Supabase, runs PEFT training, and pushes
the trained adapter back to Hugging Face.

Usage:
    doppler run -- python src/ml/modal_train.py
"""

import os
import modal

# ── Define the GPU Container Environment ──────────────────────────────────────
image = (
    modal.Image.debian_slim()
    .apt_install("git")
    .pip_install(
        "setuptools",
        "numpy<2",
        "torch==2.2.0",
        "transformers==4.38.1",
        "peft==0.8.2",
        "bitsandbytes==0.42.0",
        "accelerate==0.27.2",
        "datasets==2.17.1",
        "supabase==2.30.0",
    )
)

app = modal.App("customercore-llm-finetuning")

# Pull credentials automatically from your active shell environment variables
secrets = [
    modal.Secret.from_local_environ(
        [
            "HF_TOKEN",
            "SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY",
        ]
    )
]

# ── Remote GPU Execution Function ─────────────────────────────────────────────
# Requesting an Nvidia A10G GPU (24GB VRAM) - perfect for QLoRA on 8B/9B models.
# Timeout set to 2 hours (7200s).
@app.function(image=image, gpu="A10G", timeout=7200, secrets=secrets)
def train_llm():
    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
        Trainer,
        DataCollatorForLanguageModeling,
    )
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from datasets import Dataset
    from supabase import create_client

    print("🚀 Initializing on-demand GPU environment...")
    
    # 1. Fetch training data from Supabase
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
        
    print("📡 Fetching completed support runs from Supabase...")
    supabase = create_client(supabase_url, supabase_key)
    
    # Fetch completed triage tickets to use as training ground-truth
    response = (
        supabase.table("tickets")
        .select("raw_text, suggested_resolution")
        .eq("status", "complete")
        .limit(1000) # Limit for demonstration, can be raised to fetch full dataset
        .execute()
    )
    
    rows = response.data
    if not rows or len(rows) < 10:
        print(f"❌ Insufficient training data (found {len(rows)} rows). Need at least 10 completed runs.")
        return

    print(f"📊 Loaded {len(rows)} rows of training data from database.")

    # 2. Format dataset for instruction training
    # Standard prompt template matching Llama 3 style
    def format_prompt(row):
        system_prompt = "You are a CustomerCore B2B support agent. Respond to the support ticket professionally."
        user_input = row["raw_text"]
        response = row["suggested_resolution"]
        
        prompt = (
            f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_prompt}<|eot_id|>"
            f"<|start_header_id|>user<|end_header_id|>\n\n{user_input}<|eot_id|>"
            f"<|start_header_id|>assistant<|end_header_id|>\n\n{response}<|eot_id|>"
        )
        return {"text": prompt}

    formatted_data = [format_prompt(r) for r in rows]
    dataset = Dataset.from_list(formatted_data)
    print("🧹 Data formatted into instruction training prompt template.")

    # 3. Configure 4-bit quantization (QLoRA)
    base_model_name = "NousResearch/Meta-Llama-3-8B-Instruct"
    print(f"📥 Loading base model on GPU: {base_model_name}")
    
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    
    tokenizer = AutoTokenizer.from_pretrained(base_model_name)
    tokenizer.pad_token = tokenizer.eos_token
    
    model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=bnb_config,
        device_map="auto",
    )
    
    # Prepare model for k-bit quantization training
    model = prepare_model_for_kbit_training(model)

    # 4. Apply LoRA configuration
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    # Tokenize the dataset
    def tokenize_function(examples):
        return tokenizer(examples["text"], truncation=True, max_length=512)

    tokenized_dataset = dataset.map(tokenize_function, batched=True, remove_columns=["text"])

    # 5. Define Training Arguments
    training_args = TrainingArguments(
        output_dir="./results",
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=100,
        max_steps=500, # Adjust depending on dataset size
        learning_rate=2e-4,
        fp16=True,
        logging_steps=10,
        save_strategy="no",
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        train_dataset=tokenized_dataset,
        args=training_args,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )

    print("🏋️ Starting training loop...")
    trainer.train()
    print("🎉 Training completed successfully!")

    # 6. Push custom fine-tuned adapter to Hugging Face
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("⚠️ HF_TOKEN not found in environment. Skipping adapter push.")
        return
        
    custom_adapter_name = "customercore-llama3-adapter"
    print(f"📤 Pushing fine-tuned LoRA adapter to Hugging Face: {custom_adapter_name}")
    
    # Push weights and tokenizer
    model.push_to_hub(custom_adapter_name, token=hf_token)
    tokenizer.push_to_hub(custom_adapter_name, token=hf_token)
    print("🏆 Adapter weights successfully published to Hugging Face Hub!")


# ── Local CLI Entrypoint ──────────────────────────────────────────────────────
@app.local_entrypoint()
def main():
    print("⏳ Connecting to Modal serverless runners...")
    train_llm.remote()
    print("🏁 Execution finished.")
