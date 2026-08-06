from fastapi import APIRouter, HTTPException
from rag.retriever import retrieve_chunks, retrieve_all_document_chunks
from models.schemas import FlashcardRequest, FlashcardsResponse, Flashcard

router = APIRouter()

def is_clean_text(text: str) -> bool:
    """Return True only if text looks like real English (not garbled OCR)."""
    if not text or len(text) < 3:
        return False
    words = text.split()
    if not words:
        return False
    # Reject if average word length is suspiciously short (OCR gibberish)
    avg_word_len = sum(len(w) for w in words) / len(words)
    if avg_word_len < 2.5:
        return False
    # Reject if more than 40% of characters are non-alphanumeric
    alnum = sum(1 for c in text if c.isalnum())
    if len(text) > 0 and alnum / len(text) < 0.6:
        return False
    return True

@router.post("/flashcards", response_model=FlashcardsResponse)
async def generate_flashcards(request: FlashcardRequest):
    if request.document_id:
        chunks = retrieve_all_document_chunks(request.document_id)
        chunks = chunks[:12]
    else:
        chunks = retrieve_chunks(
            query="definitions concepts terms key ideas vocabulary",
            top_k=8
        )

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail="No study content found. Please upload a PDF first."
        )

    flashcards = []
    seen_fronts = set()

    # Tier 1: definition-pattern matching (highest quality cards)
    for c in chunks:
        raw_text = c.get("text") or ""
        filename = c.get("filename") or "document"
        topic = filename.split(".")[0][:20]

        sentences = [s.strip() for s in raw_text.split(".") if len(s.strip()) > 30]
        for s in sentences:
            if len(flashcards) >= request.num_cards:
                break
            for indicator in [" refers to ", " defines ", " is defined as ", " is a ", " is the ", " are ", " means "]:
                idx = s.lower().find(indicator)
                if idx != -1:
                    term = s[:idx].strip()
                    defn = s[idx + len(indicator):].strip()
                    if 2 < len(term) < 50 and len(defn) > 10 and is_clean_text(term) and is_clean_text(defn):
                        front = f"What is {term}?"
                        if front not in seen_fronts:
                            seen_fronts.add(front)
                            flashcards.append(Flashcard(
                                front=front,
                                back=defn[0].upper() + defn[1:] if defn else "See source.",
                                topic=topic
                            ))
                        break
        if len(flashcards) >= request.num_cards:
            break

    # Tier 2: key-sentence cards
    if len(flashcards) < request.num_cards:
        for c in chunks:
            raw_text = c.get("text") or ""
            filename = c.get("filename") or "document"
            topic = filename.split(".")[0][:20]
            sentences = [s.strip() for s in raw_text.split(".") if len(s.strip()) > 40]
            for s in sentences:
                if len(flashcards) >= request.num_cards:
                    break
                words = s.split()
                if len(words) > 6:
                    front = f"Explain: {' '.join(words[:5])}..."
                    if front not in seen_fronts:
                        seen_fronts.add(front)
                        flashcards.append(Flashcard(front=front, back=s, topic=topic))

    # Tier 3: raw passage cards (always generates something)
    if not flashcards and chunks:
        for c in chunks[:request.num_cards]:
            raw_text = (c.get("text") or "").strip()
            filename = c.get("filename") or "document"
            topic = filename.split(".")[0][:20]
            if raw_text:
                words = raw_text.split()
                preview = " ".join(words[:8]) + "..."
                flashcards.append(Flashcard(
                    front=f'What does this describe? "{preview}"',
                    back=raw_text[:300] + ("..." if len(raw_text) > 300 else ""),
                    topic=topic
                ))

    return FlashcardsResponse(
        flashcards=flashcards[:request.num_cards],
        total=len(flashcards[:request.num_cards])
    )
