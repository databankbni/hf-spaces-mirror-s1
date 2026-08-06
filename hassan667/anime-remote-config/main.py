import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Smart Remote Config API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "online", "service": "Remote Config"}

@app.get("/get-config")
def get_config():
    
    secret_auth = os.environ.get("AUTH_HEADER")
    
    return {
        "status": "success",
        "settings": {
            "base_url": "https://anime-cartoon.developer-pro.workers.dev",
            "auth_header": secret_auth if secret_auth else "Basic DEFAULT_OR_FALLBACK_TOKEN",
            "user_agent": "okhttp/5.4.0"
        }
    }
