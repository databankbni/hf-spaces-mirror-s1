from pydantic import BaseModel


class ChatRequest(BaseModel):
    source_text: str
    question: str


class ChatResponse(BaseModel):
    answer: str


class AudioRequest(BaseModel):
    source_text: str


class AudioResponse(BaseModel):
    audio_url: str
    script: str


class ImageRequest(BaseModel):
    source_text: str


class VideoRequest(BaseModel):
    source_text: str
