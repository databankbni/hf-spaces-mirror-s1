from fastapi import APIRouter, HTTPException
from rag.retriever import retrieve_chunks, retrieve_all_document_chunks
from models.schemas import SummaryRequest, SummaryResponse

router = APIRouter()

@router.post("/summary", response_model=SummaryResponse)
async def generate_summary(request: SummaryRequest):
    if request.document_id:
        chunks = retrieve_all_document_chunks(request.document_id)
        chunks = chunks[:15]
    else:
        chunks = retrieve_chunks(
            query="overview introduction main topics summary",
            top_k=10
        )

    if not chunks:
        raise HTTPException(status_code=404, detail="No study content found. Please upload a PDF first.")

    combined = " ".join([c.get("text") or "" for c in chunks])

    length_map = {"short": 180, "medium": 400, "long": 700}
    limit = length_map.get(request.length, 400)
    summary_text = combined[:limit] + "..." if len(combined) > limit else combined

    key_points = []
    for c in chunks[:6]:
        sentences = [s.strip() for s in (c.get("text") or "").split(".") if len(s.strip()) > 25]
        if sentences:
            key_points.append(sentences[0])

    return SummaryResponse(
        summary=summary_text,
        key_points=key_points[:6],
        word_count=len(summary_text.split())
    )
