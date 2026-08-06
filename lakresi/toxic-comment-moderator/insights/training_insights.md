# Training Results — Toxic Comment Moderator (DistilBERT)

## Overview

Model: `distilbert-base-uncased` fine-tuned for multilabel toxic comment classification  
Dataset: Jigsaw Toxic Comment Classification Challenge (~145k train, ~16k validation)  
Labels: `toxic`, `severe_toxic`, `obscene`, `threat`, `insult`, `identity_hate`  
Hardware: 2x NVIDIA RTX 3090 (24GB VRAM each) via Vast.ai  
Training time: ~34 minutes (2,845 steps, 5 epochs, batch size 128 per device)  
Loss function: `BCEWithLogitsLoss` with per-label `pos_weight` for class imbalance  

---

## Epoch-by-Epoch Metrics

| Epoch | Train Loss | Eval Loss | F1 Macro | F1 Micro | F1 Weighted | ROC AUC |
|-------|------------|-----------|----------|----------|-------------|---------|
| 1     | 3.917      | 1.598     | 0.6319   | 0.7751   | 0.7644      | 0.9892  |
| 2     | 1.438      | 1.546     | 0.6696   | 0.7866   | 0.7843      | 0.9903  |
| 3     | 1.116      | 1.687     | 0.6707   | 0.7915   | 0.7882      | 0.9892  |
| 4     | 0.857      | 1.880     | 0.6841   | 0.7920   | 0.7915      | 0.9871  |
| 5     | 0.697      | 1.934     | 0.6869   | 0.7966   | 0.7961      | 0.9868  |

---

## Per-Label F1 Scores (Final Epoch)

| Label          | F1 Score | Class Frequency | Notes                        |
|----------------|----------|-----------------|------------------------------|
| obscene        | 0.8500   | ~5.9%           | Best performing label        |
| toxic          | 0.8391   | ~10.2%          | Most frequent, strong result |
| insult         | 0.7632   | ~4.9%           | Decent performance           |
| identity_hate  | 0.5866   | ~0.9%           | Rare, underperforming        |
| severe_toxic   | 0.5472   | ~1.0%           | Rare, underperforming        |
| threat         | 0.5385   | ~0.3%           | Rarest, weakest result       |

---

## Key Insights

### 1. Overfitting Pattern Confirmed

Training loss decreased monotonically across all 5 epochs (3.917 → 0.697), while evaluation
loss began rising after epoch 2 (1.546 → 1.934). This is a textbook generalization gap,
indicating the model began memorizing training examples rather than learning generalizable
features from epoch 3 onwards.

Despite this, F1 macro continued to improve marginally across all epochs. This divergence
between eval loss and F1 macro occurs because `BCEWithLogitsLoss` is sensitive to probability
calibration — as the model becomes overconfident, loss worsens, but the relative ranking of
predictions at the 0.5 decision boundary can still improve. In other words, the model is
overfitting in terms of probability magnitude but not in terms of classification boundary.

The best checkpoint by eval loss would be epoch 2 (1.546); the best checkpoint by F1 macro
is epoch 5 (0.6869). Since `metric_for_best_model="f1_macro"` was set, the epoch 5
checkpoint was saved as the final model.

### 2. ROC AUC vs F1 Macro Divergence

ROC AUC remained consistently high throughout training (0.987–0.990) and actually peaked at
epoch 2 before declining slightly. This indicates the model's ability to rank positive examples
above negative examples is excellent and largely unaffected by overfitting. The primary
weakness is at the decision threshold, not in the underlying discriminative capability of the
model.

This suggests that **threshold tuning per label** is the highest-leverage next step —
the model has strong discriminative power (ROC AUC ~0.99) that is not being fully realized
at the default 0.5 threshold, particularly for rare labels.

### 3. Class Imbalance Effect on Per-Label Performance

Performance correlates strongly with label frequency. Frequent labels (`toxic`, `obscene`)
achieved F1 > 0.83, while rare labels (`threat` at ~0.3% frequency, `severe_toxic` at ~1.0%)
achieved F1 < 0.55. Despite applying `pos_weight` inversely proportional to class frequency
during training, rare labels remain significantly underperforming.

This is expected behavior — `pos_weight` shifts the loss contribution but cannot compensate
for the fundamental scarcity of positive examples from which the model can learn discriminative
features. For `threat` in particular, the combination of extreme rarity and short, contextually
ambiguous text makes it the hardest label to classify.

### 4. Training Efficiency

With 2x RTX 3090 GPUs via `accelerate` multi-GPU training, the full 5-epoch run completed
in approximately 34 minutes (2,845 steps at ~1.57 it/s). Each evaluation pass over the
16,180-sample validation set completed in ~38-41 seconds (~410-420 samples/second).
Single-GPU training on the same hardware would have taken approximately 60-70 minutes.

The effective global batch size was 256 (128 per device × 2 GPUs), which is appropriate
for DistilBERT fine-tuning at this dataset scale.

### 5. Gradient Norm Behavior

Gradient norms fluctuated across epochs:

| Epoch | Grad Norm |
|-------|-----------|
| 1     | 8.277     |
| 2     | 10.530    |
| 3     | 8.442     |
| 4     | 20.280    |
| 5     | 5.951     |

The spike at epoch 4 (20.28) warrants attention — this indicates a momentarily unstable
gradient update, likely caused by the learning rate schedule intersecting with a difficult
region of the loss landscape as the model began to overfit. Gradient clipping (default
`max_grad_norm=1.0` in `TrainingArguments`) mitigated any adverse effect, as training
continued stably into epoch 5.

### 6. Learning Rate Schedule

The learning rate decayed from ~4e-5 at epoch 1 to ~1.76e-8 at epoch 5, indicating a
linear decay schedule reaching near-zero by the final epoch. The near-zero learning rate
at epoch 5 explains why the model's metrics changed minimally between epochs 4 and 5
(F1 macro: 0.6841 → 0.6869) despite train loss still dropping.

---

## Conclusions and Recommended Next Steps

The baseline model achieves **F1 macro 0.687** and **ROC AUC 0.987** on the Jigsaw
validation set, which represents a strong baseline for a first fine-tuning run with no
architectural modifications.

Recommended actions in priority order:

**1. Threshold tuning (immediate, high impact)**  
Per-label threshold optimization using the validation set is expected to yield meaningful
F1 macro gains given the high ROC AUC. Labels like `threat` and `severe_toxic` likely
benefit from lower thresholds (e.g. 0.3) to improve recall without sacrificing precision
excessively.

**2. Regularization for next training run (medium effort)**  
Add `weight_decay=0.01`, `warmup_ratio=0.1`, and `EarlyStoppingCallback(patience=2)`
to address the overfitting observed from epoch 3. Early stopping on eval loss would
terminate training at epoch 2, saving compute and potentially improving generalization.

**3. Learning rate tuning (medium effort)**  
Reduce initial learning rate from default (5e-5) to 2e-5. DistilBERT fine-tuning is
sensitive to learning rate and a lower rate may reduce the generalization gap.

**4. Data augmentation for rare labels (longer term)**  
`threat` and `severe_toxic` may benefit from oversampling or back-translation augmentation
to provide the model with more positive examples to learn from.
