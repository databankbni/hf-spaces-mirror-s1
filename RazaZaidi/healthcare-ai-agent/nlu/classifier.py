import pickle
import os

MODEL_PATH = "nlu/model.pkl"

def load_model():
    if not os.path.exists(MODEL_PATH):
        from nlu.train import train_nlu
        train_nlu()
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)

def classify_intent(text: str) -> dict:
    try:
        model = load_model()
        text = text.lower().strip()
        intent = model.predict([text])[0]
        proba = model.predict_proba([text])[0]
        confidence = max(proba)
        return {
            "intent": intent,
            "confidence": round(float(confidence), 2)
        }
    except Exception as e:
        return {"intent": "general", "confidence": 0.0}