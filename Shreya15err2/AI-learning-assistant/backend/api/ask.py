from fastapi import APIRouter, HTTPException
from rag.retriever import retrieve_chunks, build_context
from models.schemas import QuestionRequest, AnswerResponse

router = APIRouter()

@router.post("/ask", response_model=AnswerResponse)
async def ask_question(request: QuestionRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    chunks = retrieve_chunks(
        query=request.question,
        top_k=request.top_k,
        document_id=request.document_id
    )

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail="No relevant content found. Please upload a document first."
        )

    # Always use direct retrieval for instant response (no LLM wait)
    top_chunks_text = "\n\n".join([f"• {c['text']}" for c in chunks[:3]])
    answer = (
        f"Here is the most relevant content from your study materials:\n\n"
        f"{top_chunks_text}"
    )
    model_used = "direct-retrieval"

    sources = [
        {
            "filename": c["filename"],
            "page": c["page"],
            "similarity": c["similarity"],
            "preview": c["text"][:150] + "..." if len(c["text"]) > 150 else c["text"]
        }
        for c in chunks
    ]

    return AnswerResponse(answer=answer, sources=sources, model_used=model_used)
