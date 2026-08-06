from flask import Flask, request, jsonify

from flask_cors import CORS

from transformers import AutoTokenizer
from transformers import AutoModelForSequenceClassification

import torch
import pickle

app = Flask(__name__)

CORS(app)


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

model_path = "Chatbot_BERT_Model"

tokenizer = AutoTokenizer.from_pretrained(model_path)

model = AutoModelForSequenceClassification.from_pretrained(model_path)

model.to(device)

model.eval()

with open("label_encoder.pkl","rb") as f:

    label_encoder = pickle.load(f)


def predict(text):

    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=64
    )

    inputs = {k:v.to(device) for k,v in inputs.items()}

    with torch.no_grad():

        outputs = model(**inputs)

    logits = outputs.logits

    prediction = torch.argmax(logits,dim=1).item()

    confidence = torch.softmax(logits,dim=1)[0][prediction].item()

    intent = label_encoder.inverse_transform([prediction])[0]

    return intent, confidence


@app.route("/predict",methods=["POST"])

def classify():

    data = request.get_json()

    text = data["message"]

    intent, confidence = predict(text)

    return jsonify({

        "intent":intent,

        "confidence":float(confidence)

    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=7860
    )