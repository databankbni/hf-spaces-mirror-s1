from fastapi import FastAPI
from pydantic import BaseModel
import joblib

app = FastAPI()

model = joblib.load("models/sentiment_model.pkl")

class Review(BaseModel):
    text: str

@app.get("/")
def home():
    return {"message": "nigga please Sentiment API"}

@app.post("/predict")
def predict(review: Review):

    prediction = model.predict([review.text])

    return {
        "review": review.text,
        "sentiment": prediction[0]
    }