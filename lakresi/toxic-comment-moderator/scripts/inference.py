import json
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from ..app.utils import label_cols

tokenizer = AutoTokenizer.from_pretrained("final_model")
model = AutoModelForSequenceClassification.from_pretrained("final_model")

model.eval()

with open("final_model/thresholds.json") as f:
    thresholds = json.load(f)

def predict(text:str):
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding="max_length",
        max_length=512
    )

    with torch.no_grad():
        logits = model(**inputs).logits

    probs = torch.sigmoid(logits).squeeze().tolist()

    return{
        label: {
            "probability":round(prob, 4),
            "flagged": prob>=thresholds[label]
        } for label, prob in zip(label_cols, probs)
    }
