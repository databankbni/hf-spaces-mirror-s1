import logging
from fastapi import APIRouter, File, UploadFile, Depends
from fastapi.responses import JSONResponse
from app.config import require_api_key, DEV_BYPASS_FACE
from app.face_recognition.image_utils import read_and_detect_face_and_get_embedding

router = APIRouter()

logger = logging.getLogger("uvicorn.error")


@router.post('/face-embedding', dependencies=[Depends(require_api_key)])
async def face_embedding(file: UploadFile = File(...)):
    logger.info("face_embedding handler called")

    if DEV_BYPASS_FACE:
        return JSONResponse(content={"faceDetected": True, "dev_bypass": True})

    img_bytes = await file.read()
    _, emb = read_and_detect_face_and_get_embedding(img_bytes)

    if emb is None:
        return JSONResponse(
            content={"faceDetected": False, "error": "No valid single face detected"},
            status_code=200,
        )

    return JSONResponse(
        content={
            "faceDetected": True,
            "embedding": emb.tolist(),
        },
        status_code=200,
    )
