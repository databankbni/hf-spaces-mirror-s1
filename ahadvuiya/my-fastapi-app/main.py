from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from core.gateway import ZentraXSecureGateway

app = FastAPI(
    title="ZentraX AI Core API",
    description="Secure backend gateway with input moderation and zero-knowledge encryption.",
    version="1.0.0"
)

# সিকিউর গেটওয়ে ইনিশিয়ালাইজ করা
gateway = ZentraXSecureGateway()

class PromptRequest(BaseModel):
    prompt: str

@app.post("/api/v1/secure-process")
def process_prompt(request: PromptRequest):
    """
    ইউজারের প্রম্পট রিসিভ করে মডারেশন ও জিরো-নলেজ এনক্রিপশন 
    পাইপলাইনের মাধ্যমে প্রসেস করার প্রধান এন্ডপয়েন্ট।
    """
    result = gateway.process_incoming_request(request.prompt)

    if result["status"] == "blocked":
        raise HTTPException(status_code=400, detail=result["error"])
    elif result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["error"])

    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=7860)
