from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import pipeline

app = FastAPI()

#載入輕量級的AI垃圾郵件分類模型
classifier = pipeline("text-classification", model="mrm8488/bert-tiny-finetuned-sms-spam-detection")

#繼承BaseModel 定義外部傳入的JSON格式(確保資料格式正確)
class EmailRequest(BaseModel):
    sender_email: str
    content: str


@app.get("/")
def health_check():
    return {"status": "ok", "message": "AI Phishing API is running on Hugging Face Spaces!"}


@app.post("/predict")
def predict_phishing(email: EmailRequest):
    try:
        #將信件內容丟給AI模型進行預測
        result = classifier(email.content)[0]

        #根據預測結果決定警報層級
        label = result['label']
        score = result['score']

        if label == "LABEL_1" and score > 0.7: #LABEL_1 通常代表 Spam/Phishing
            status = "Critical"
        else:
            status = "Safe"

        return{
            "status": status,
            "ai_confidence_score": round(score, 4),
            "sender": email.sender_email,
            "content_length": len(email.content)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))