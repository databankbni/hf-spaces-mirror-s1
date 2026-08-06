import random
import re
from fastapi import APIRouter, HTTPException
from rag.retriever import retrieve_chunks, retrieve_all_document_chunks
from models.schemas import QuizRequest, QuizResponse, QuizQuestion

router = APIRouter()

@router.post("/generate-quiz", response_model=QuizResponse)
async def generate_quiz(request: QuizRequest):
    if request.document_id:
        chunks = retrieve_all_document_chunks(request.document_id)
        chunks = chunks[:12]
    else:
        chunks = retrieve_chunks(
            query="main concepts key topics important facts",
            top_k=8
        )

    if not chunks:
        raise HTTPException(status_code=404, detail="No study content found. Please upload a PDF first.")

    questions = []
    all_sentences = []
    for c in chunks:
        sentences = [s.strip() for s in (c.get("text") or "").split(".") if len(s.strip()) > 35]
        all_sentences.extend(sentences)

    random.shuffle(all_sentences)

    for s in all_sentences:
        if len(questions) >= request.num_questions:
            break
        words = s.split()
        if len(words) < 8:
            continue
        candidates = [w for w in words[3:-2] if len(w) > 4 and w.isalnum()]
        if not candidates:
            continue

        target = random.choice(candidates)
        clean_target = re.sub(r'[^\w]', '', target)
        if not clean_target:
            continue

        blanked = s.replace(target, "_______")
        q_text = f'Fill in the blank:\n\n"{blanked}"'

        other = [re.sub(r'[^\w]', '', w) for w in candidates if re.sub(r'[^\w]', '', w).lower() != clean_target.lower()]
        if len(other) >= 3:
            distractors = random.sample(other, 3)
        else:
            distractors = [f"Modified {clean_target}", f"{clean_target} factor", "None of the above"]

        options = [clean_target] + distractors
        random.shuffle(options)

        formatted = []
        correct = ""
        for idx, opt in enumerate(options):
            prefix = ["A) ", "B) ", "C) ", "D) "][idx]
            fmt = f"{prefix}{opt}"
            formatted.append(fmt)
            if opt == clean_target:
                correct = fmt

        questions.append(QuizQuestion(
            question=q_text,
            options=formatted,
            correct_answer=correct,
            explanation=f'From source: "{s}"'
        ))

    # Fallback if not enough questions extracted
    if not questions:
        for i in range(request.num_questions):
            opts = ["Option A", "Option B", "Option C", "Option D"]
            questions.append(QuizQuestion(
                question=f"Review Question {i+1}: Which concept is described in the materials?",
                options=opts, correct_answer="Option A",
                explanation="Review your uploaded study material for details."
            ))

    return QuizResponse(
        questions=questions[:request.num_questions],
        total=len(questions[:request.num_questions]),
        difficulty=request.difficulty
    )
