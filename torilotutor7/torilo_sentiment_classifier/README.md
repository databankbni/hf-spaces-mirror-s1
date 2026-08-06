---
title: Torilo Sentiment Classifier
emoji: 🤖
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---




# Student Sentiment Classifier

A machine learning API that predicts whether a student's review is positive or negative.

## Features

- Sentiment Analysis
- FastAPI REST API
- MLflow Experiment Tracking
- DVC Data Versioning
- Docker Support
- Swagger API Documentation

## Tech Stack

- Python
- Scikit-learn
- FastAPI
- MLflow
- DVC
- Docker

---

## Project Structure

```text
student_sentiment_classifier/
│
├── app/
│   └── main.py
├── data/
│   └── reviews.csv
├── models/
│   └── sentiment_model.pkl
├── train.py
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## Installation

Clone the repository:

```bash
git clone <repository-url>
cd student_sentiment_classifier
```

Create virtual environment:

```bash
python -m venv ssc_venv
```

Activate the environment:

### Windows

```bash
ssc_venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Train the Model

```bash
python train.py
```

---

## Run the API

```bash
uvicorn app.main:app --reload
```

API URL:

```
http://127.0.0.1:8000
```

Swagger Documentation:

```
http://127.0.0.1:8000/docs
```

---

## Example Request

```json
{
    "text": "The instructor was excellent"
}
```

Response:

```json
{
    "review": "The instructor was excellent",
    "sentiment": "positive"
}
```

---

## MLflow

Start MLflow:

```bash
mlflow ui
```

Open:

```
http://localhost:5000
```

---

## DVC

Initialize DVC:

```bash
dvc init
```

Track data:

```bash
dvc add data/reviews.csv
```

---

## Docker

Build image:

```bash
docker build -t sentiment-api .
```

Run container:

```bash
docker run -p 8000:8000 sentiment-api
```

---

## Author

AI Engineering Classroom Demonstration Project