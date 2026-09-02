from contextlib import asynccontextmanager
from typing import List, AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import logging

# Import and run the logging setup
from logging_config import setup_logging
setup_logging()

# Imported the new streaming function
from agents import run_agent_streaming

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    A simple lifespan function that runs when the server starts.
    The complex ingestion logic has been moved to a separate script.
    """
    logger.info("--- FastAPI application is starting up... ---")
    yield
    logger.info("--- FastAPI application is shutting down. ---")


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProviderMessage(BaseModel):
    role: str
    content: str


class AIChatRequest(BaseModel):
    messages: List[ProviderMessage]
    activeRole: str


@app.get("/")
async def root():
    logger.info("Root endpoint / was hit.")
    return {"message": "✅ Multi-agent AI backend is running"}


@app.post("/ask")
async def ask_post(request: AIChatRequest):
    if not request.messages:
        logger.warning("Request received with no messages.")
        raise HTTPException(status_code=400, detail="No messages in request.")

    # frontend sends all messages, including the last one
    query = request.messages[-1].content
    history = [msg.dict() for msg in request.messages[:-1]]
    role = request.activeRole

    logger.info(
        "Received /ask request.",
        extra={"role": role, "history_len": len(history)}
    )

    try:
        async def stream_generator() -> AsyncGenerator[str, None]:
            try:
                async for chunk in run_agent_streaming(role, query, history):
                    yield chunk
            except Exception as e:
                logger.error("Error in stream_generator", exc_info=True)
                # user-facing info when streaming fails mid-way
                yield f"\n\nSorry, an error occurred: {e}"

        return StreamingResponse(stream_generator(), media_type="text/plain")

    except Exception as e:
        logger.error("Error in /ask endpoint", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing the request: {e}")
