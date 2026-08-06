from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services import notebooklm_service as nlm
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["notebooklm"])


class NotebookRequest(BaseModel):
    title: str


class TextSourceRequest(BaseModel):
    notebook_id: str
    title: str
    content: str


class UrlSourceRequest(BaseModel):
    notebook_id: str
    url: str


class ChatRequest(BaseModel):
    notebook_id: str
    question: str


class GenerateRequest(BaseModel):
    notebook_id: str
    instructions: str = ""


class VideoRequest(BaseModel):
    notebook_id: str
    instructions: str = ""
    style: str = "classic"


class QuizRequest(BaseModel):
    notebook_id: str
    difficulty: str = "medium"


class ReportRequest(BaseModel):
    notebook_id: str
    custom_prompt: str = ""


class DeleteRequest(BaseModel):
    notebook_id: str


def _check():
    if not nlm.is_available():
        raise HTTPException(
            status_code=503,
            detail="NotebookLM not configured. Set NBLM_SESSION env var (base64 of storage_state.json).",
        )


@router.get("/nlm/status")
async def nlm_status():
    return {"configured": nlm.is_available()}


@router.get("/nlm/notebooks")
async def list_notebooks():
    _check()
    try:
        return await nlm.list_notebooks()
    except Exception as e:
        logger.exception("Failed to list notebooks")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nlm/notebooks")
async def create_notebook(req: NotebookRequest):
    _check()
    try:
        return await nlm.create_notebook(req.title)
    except Exception as e:
        logger.exception("Failed to create notebook")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/nlm/notebooks")
async def delete_notebook(req: DeleteRequest):
    _check()
    try:
        await nlm.delete_notebook(req.notebook_id)
        return {"deleted": True}
    except Exception as e:
        logger.exception("Failed to delete notebook")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nlm/sources/text")
async def add_text_source(req: TextSourceRequest):
    _check()
    try:
        return await nlm.add_text_source(req.notebook_id, req.title, req.content)
    except Exception as e:
        logger.exception("Failed to add text source")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nlm/sources/url")
async def add_url_source(req: UrlSourceRequest):
    _check()
    try:
        return await nlm.add_url_source(req.notebook_id, req.url)
    except Exception as e:
        logger.exception("Failed to add URL source")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nlm/sources/{notebook_id}")
async def list_sources(notebook_id: str):
    _check()
    try:
        return await nlm.list_sources(notebook_id)
    except Exception as e:
        logger.exception("Failed to list sources")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nlm/chat")
async def nlm_chat(req: ChatRequest):
    _check()
    try:
        return await nlm.chat(req.notebook_id, req.question)
    except Exception as e:
        logger.exception("Failed to chat")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nlm/generate/audio")
async def nlm_generate_audio(req: GenerateRequest):
    _check()
    try:
        return await nlm.generate_audio(req.notebook_id, req.instructions)
    except Exception as e:
        logger.exception("Failed to generate audio")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nlm/generate/video")
async def nlm_generate_video(req: VideoRequest):
    _check()
    try:
        return await nlm.generate_video(req.notebook_id, req.instructions, req.style)
    except Exception as e:
        logger.exception("Failed to generate video")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nlm/generate/quiz")
async def nlm_generate_quiz(req: QuizRequest):
    _check()
    try:
        return await nlm.generate_quiz(req.notebook_id, req.difficulty)
    except Exception as e:
        logger.exception("Failed to generate quiz")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nlm/generate/report")
async def nlm_generate_report(req: ReportRequest):
    _check()
    try:
        return await nlm.generate_report(req.notebook_id, req.custom_prompt)
    except Exception as e:
        logger.exception("Failed to generate report")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nlm/generate/mindmap")
async def nlm_generate_mindmap(req: GenerateRequest):
    _check()
    try:
        return await nlm.generate_mind_map(req.notebook_id)
    except Exception as e:
        logger.exception("Failed to generate mind map")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nlm/generate/slides")
async def nlm_generate_slides(req: GenerateRequest):
    _check()
    try:
        return await nlm.generate_slide_deck(req.notebook_id, req.instructions)
    except Exception as e:
        logger.exception("Failed to generate slide deck")
        raise HTTPException(status_code=500, detail=str(e))


class InfographicRequest(BaseModel):
    notebook_id: str
    instructions: str = ""
    orientation: str = "landscape"


@router.post("/nlm/generate/infographic")
async def nlm_generate_infographic(req: InfographicRequest):
    _check()
    try:
        return await nlm.generate_infographic(
            req.notebook_id, req.instructions, req.orientation
        )
    except Exception as e:
        logger.exception("Failed to generate infographic")
        raise HTTPException(status_code=500, detail=str(e))
