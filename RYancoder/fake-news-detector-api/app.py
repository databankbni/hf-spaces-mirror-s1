import gradio as gr
import torch
from transformers import DistilBertTokenizer, DistilBertForSequenceClassification

MODEL_REPO = "RYancoder/fake-news-detector-models"
MODEL_SUBFOLDER = "distilbert_model"

tokenizer = DistilBertTokenizer.from_pretrained(MODEL_REPO, subfolder=MODEL_SUBFOLDER)
model = DistilBertForSequenceClassification.from_pretrained(MODEL_REPO, subfolder=MODEL_SUBFOLDER)
model.eval()

def predict(text):
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=512,
    )

    with torch.no_grad():
        outputs = model(**inputs)

    probs = torch.softmax(outputs.logits, dim=1).squeeze().tolist()
    
    label = "FAKE" if probs[1] > probs[0] else "REAL"
    confidence = round(max(probs) * 100, 2)

    return {
        "prediction": label,
        "confidence": f"{confidence}%"
    }

demo = gr.Interface(
    fn=predict,
    inputs=gr.Textbox(lines=8, label="News Text"),
    outputs=gr.JSON(label="Prediction"),
    title="Fake News Detector API",
    description="DistilBERT-based fake news classification",
)

demo.launch()