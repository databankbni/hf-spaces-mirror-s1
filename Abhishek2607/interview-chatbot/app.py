import os
import uvicorn
from main import app

# This is the entry point for Hugging Face Spaces
# It imports your FastAPI app from main.py and runs it

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))  # Hugging Face uses port 7860
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port,
        log_level="info"
    )