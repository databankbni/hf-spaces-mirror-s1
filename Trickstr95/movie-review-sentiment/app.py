import os
from flask import Flask, request, jsonify
from transformers import pipeline

app = Flask(__name__)

# Use a reliable public sentiment model
MODEL_NAME = "distilbert-base-uncased-finetuned-sst-2-english"

# Load the sentiment model
try:
    classifier = pipeline(
        "sentiment-analysis",
        model=MODEL_NAME
    )
    model_loaded = True
    error_message = ""
except Exception as e:
    classifier = None
    model_loaded = False
    error_message = str(e)


@app.route("/")
def home():
    return "Movie Review Sentiment API is running."


@app.route("/predict", methods=["POST"])
def predict():

    if not model_loaded:
        return jsonify({
            "error": "Model failed to load.",
            "details": error_message
        }), 500

    try:
        data = request.get_json()

        if not data or "text" not in data:
            return jsonify({
                "error": "Please provide review text."
            }), 400

        text = data["text"].strip()

        if not text:
            return jsonify({
                "error": "Review cannot be empty."
            }), 400

        result = classifier(text)[0]

        label = result["label"]
        score = result["score"]

        if label == "POSITIVE":
            sentiment = "Positive 😊"
        else:
            sentiment = "Negative 😞"

        return jsonify({
            "label": sentiment,
            "score": round(score * 100, 2)
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(
        host="0.0.0.0",
        port=port
    )