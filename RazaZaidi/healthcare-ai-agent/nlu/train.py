import json
import pickle
import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

def train_nlu():
    with open("nlu/intents.json", "r") as f:
        data = json.load(f)

    texts = []
    labels = []

    for intent in data["intents"]:
        for pattern in intent["patterns"]:
            texts.append(pattern.lower())
            labels.append(intent["tag"])

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2))),
        ("clf", LogisticRegression(max_iter=1000))
    ])

    pipeline.fit(texts, labels)

    os.makedirs("nlu", exist_ok=True)
    with open("nlu/model.pkl", "wb") as f:
        pickle.dump(pipeline, f)

    print("NLU Model trained successfully!")
    print(f"Trained on {len(texts)} examples")
    print(f"Intents: {list(set(labels))}")
    return pipeline

if __name__ == "__main__":
    train_nlu()