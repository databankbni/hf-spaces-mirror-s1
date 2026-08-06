import torch
import numpy as np
from sklearn.metrics import f1_score
from transformers import AutoModelForSequenceClassification
from scripts.train import val_ds, trainer

trainer.model = AutoModelForSequenceClassification.from_pretrained("final_model")
logits, labels, _ = trainer.predict(val_ds)
probs  = 1 / (1 + np.exp(-logits))


label_cols = ["toxic", "severe_toxic", "obscene", "threat", "insult", "identity_hate"]
best_thresholds = []

for i in range(labels.shape[1]):
    best_t, best_f1 = 0.5, 0
    for t in np.arange(0.2, 0.8, 0.02):
        f1 = f1_score(labels[:, i], (probs[:, i] >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1, best_t = f1, t
    best_thresholds.append((label_cols[i], best_t, best_f1))

print(best_thresholds)
