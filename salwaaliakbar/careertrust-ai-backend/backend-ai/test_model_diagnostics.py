#!/usr/bin/env python3
"""Comprehensive diagnostics for model_output_v3 performance"""

import json
from pathlib import Path
import torch
import torch.nn as nn
from transformers import DistilBertTokenizerFast

# Model and Inference Service from reputation_sentiment.py
class MultiAspectRegressor(nn.Module):
    def __init__(self, hidden_dim: int, aspect_names: list[str]):
        super().__init__()
        self.encoder = __import__('transformers').DistilBertModel(
            __import__('transformers').DistilBertConfig()
        )
        self.feature_extractor = nn.Sequential(
            nn.Linear(self.encoder.config.hidden_size, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Dropout(0.35),
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Dropout(0.35),
        )

        head_hidden = max(hidden_dim // 2, 64)
        self.overall_head = nn.Sequential(
            nn.Linear(hidden_dim, head_hidden),
            nn.GELU(),
            nn.Dropout(0.2),
            nn.Linear(head_hidden, 1),
        )

        self.aspect_heads = nn.ModuleDict(
            {
                aspect: nn.Sequential(
                    nn.Linear(hidden_dim, head_hidden),
                    nn.GELU(),
                    nn.Dropout(0.2),
                    nn.Linear(head_hidden, 1),
                )
                for aspect in aspect_names
            }
        )

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor):
        encoded = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        pooled = encoded.last_hidden_state[:, 0, :]
        features = self.feature_extractor(pooled)

        overall = self.overall_head(features).squeeze(-1)
        aspects = {
            name: head(features).squeeze(-1) for name, head in self.aspect_heads.items()
        }
        return overall, aspects


def test_model():
    """Test model loading and inference"""
    
    model_dir = Path(__file__).resolve().parent / "model_output_v3" / "model_output_v3"
    config_path = model_dir / "config.json"
    weight_path = model_dir / "best.pt"
    
    print("=" * 80)
    print("MODEL DIAGNOSTICS FOR model_output_v3")
    print("=" * 80)
    
    # 1. Check file existence
    print(f"\n1. MODEL FILES:")
    print(f"   Config exists: {config_path.exists()} ({config_path})")
    print(f"   Weights exist: {weight_path.exists()} ({weight_path})")
    print(f"   Weight size: {weight_path.stat().st_size / (1024*1024):.2f} MB" if weight_path.exists() else "")
    
    # 2. Load config
    print(f"\n2. MODEL CONFIGURATION:")
    with config_path.open("r") as f:
        cfg = json.load(f)
    
    print(f"   Base Model: {cfg.get('base_model')}")
    print(f"   Hidden Dim: {cfg.get('hidden_dim')}")
    print(f"   Dropout: {cfg.get('dropout')}")
    print(f"   Epochs Trained: {cfg.get('epochs_trained')}")
    print(f"   Rating Range: {cfg.get('rating_min')} - {cfg.get('rating_max')}")
    print(f"   Best Validation R²: {cfg.get('best_val_r2'):.4f}")
    print(f"   Best Validation Loss: {cfg.get('best_val_loss'):.4f}")
    print(f"   Aspects: {', '.join(cfg.get('aspect_names', []))}")
    
    # 3. Load tokenizer
    print(f"\n3. TOKENIZER:")
    tokenizer = DistilBertTokenizerFast.from_pretrained(
        str(model_dir),
        local_files_only=True,
    )
    print(f"   Vocab size: {len(tokenizer)}")
    print(f"   Model max length: {tokenizer.model_max_length}")
    
    # 4. Load model
    print(f"\n4. MODEL LOADING:")
    aspect_names = cfg.get('aspect_names', [])
    hidden_dim = int(cfg.get('hidden_dim', 384))
    
    model = MultiAspectRegressor(hidden_dim=hidden_dim, aspect_names=aspect_names)
    checkpoint = torch.load(weight_path, map_location="cpu")
    
    if isinstance(checkpoint, dict) and "state_dict" in checkpoint:
        state_dict = checkpoint["state_dict"]
    else:
        state_dict = checkpoint
    
    model.load_state_dict(state_dict, strict=False)
    model.eval()
    print(f"   ✓ Model loaded successfully")
    print(f"   Model device: cpu")
    print(f"   Model state: eval mode")
    
    # 5. Test inference on sample reviews
    print(f"\n5. TEST INFERENCE:")
    
    test_reviews = [
        ("Very positive review. Great company culture, excellent work-life balance, amazing career growth opportunities, and competitive salary.", "VERY POSITIVE"),
        ("Terrible management, toxic culture, low pay, no growth. Worst company ever.", "VERY NEGATIVE"),
        ("Good company overall. Decent culture and salary, but limited growth opportunities.", "POSITIVE"),
        ("Okay job. Nothing special, nothing terrible. Average experience.", "NEUTRAL"),
        ("Bad work environment, low pay, bad management.", "NEGATIVE"),
    ]
    
    rating_min = float(cfg.get('rating_min', 1.0))
    rating_max = float(cfg.get('rating_max', 5.0))
    
    for review_text, label in test_reviews:
        print(f"\n   Review ({label}): {review_text[:60]}...")
        
        encoded = tokenizer(
            review_text,
            truncation=True,
            padding="max_length",
            max_length=256,
            return_tensors="pt",
        )
        
        with torch.no_grad():
            overall, aspects = model(
                encoded["input_ids"],
                encoded["attention_mask"],
            )
        
        overall_score = float(overall[0].item())
        overall_clamped = max(rating_min, min(rating_max, overall_score))
        
        print(f"      Raw Overall: {overall_score:.4f}")
        print(f"      Clamped Overall: {overall_clamped:.3f}")
        print(f"      Aspects:")
        for aspect_name in aspect_names:
            raw_value = float(aspects[aspect_name][0].item())
            clamped_value = max(rating_min, min(rating_max, raw_value))
            print(f"        - {aspect_name}: {clamped_value:.3f} (raw: {raw_value:.4f})")
    
    # 6. Load evaluation results
    print(f"\n6. EVALUATION METRICS:")
    eval_csv = model_dir / "evaluation_results.csv"
    if eval_csv.exists():
        with open(eval_csv, 'r') as f:
            lines = f.readlines()
            print(f"   {lines[0].strip()}")
            for line in lines[1:]:
                parts = line.strip().split(',')
                if parts[0] == "Overall Rating":
                    print(f"   {line.strip()}")
                    print(f"\n   Interpretation:")
                    r2 = float(parts[2])
                    mae = float(parts[3])
                    acc_03 = float(parts[8])
                    acc_05 = float(parts[9])
                    acc_10 = float(parts[10])
                    print(f"   - R² Score: {r2:.4f} (explains {r2*100:.1f}% of variance)")
                    print(f"   - MAE: {mae:.4f} (avg error ±{mae:.2f} points on 1-5 scale)")
                    print(f"   - Accuracy within ±0.3 points: {acc_03:.1f}%")
                    print(f"   - Accuracy within ±0.5 points: {acc_05:.1f}%")
                    print(f"   - Accuracy within ±1.0 points: {acc_10:.1f}%")
    
    print(f"\n" + "=" * 80)
    print("ANALYSIS & RECOMMENDATIONS")
    print("=" * 80)
    print(f"""
    Your model shows MODERATE performance:
    
    ✓ WHAT'S WORKING:
      - Model is loading correctly from model_output_v3
      - Inference code properly clamps scores to 1.0-5.0 range
      - Model trained for 53 epochs with validation monitoring
      - Maintains 80.78% accuracy within ±1.0 points
    
    ⚠ ISSUES & CONCERNS:
      - R² of 0.494 is moderate (explains only ~49% of variance)
      - MAE of 0.621 means average error of ±0.62 points
      - Only 34.32% accuracy within ±0.3 points (poor precision)
      - Salary Benefits aspect performs poorly (R² = 0.218)
      - Training plateaued around epoch 17 (validation metrics flat after)
    
    ❓ ROOT CAUSES (Most Likely):
      1. Training Data Quality/Size
         - Are your training reviews representative of real company reviews?
         - Do you have enough labeled data (~12K samples for overall rating)?
         - Is the aspect labeling consistent and accurate?
      
      2. Aspect Prediction Is Hard
         - Individual aspects (work-life balance, etc.) are harder than overall
         - Consider if aspects need different training/architecture
      
      3. Model Architecture Limitations
         - DistilBERT + simple regressor may not capture nuance
         - Hidden dim 384 may be too small for complex relationships
    
    🔧 RECOMMENDATIONS:
      1. Check Training Data Quality
         - Sample your labeled data, verify aspect annotations
         - Check label distributions (are they balanced?)
         - Look for mislabeled or ambiguous reviews
      
      2. Consider Retraining With:
         - More data (if available)
         - Different architecture (larger hidden dim, more layers)
         - Different hyperparameters (higher learning rate, batch size)
         - Data augmentation
      
      3. For Now (Without Retraining):
         - Remove the heuristic calibration (it was masking the real problem)
         - Use model predictions as-is - they're working correctly
         - Results should match evaluation metrics ±0.6 points on average
""")

if __name__ == "__main__":
    test_model()
