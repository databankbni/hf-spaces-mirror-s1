from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
import rag  # Imports your existing rag.py file

app = FastAPI()

# Configure CORS to allow requests from your GitHub Pages frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ani010.github.io"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        # Pass the bytes to your RAG processor
        result = rag.process_file_content(file_bytes, file.filename)
        return {"status": "success", "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
async def chat_with_document(request: ChatRequest):
    try:
        # Pass the message and history to your RAG generator
        response = rag.get_chat_response(request.message, request.history)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def health_check():
    return {"status": "Backend is running!"}