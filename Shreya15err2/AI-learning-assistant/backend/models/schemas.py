from pydantic import BaseModel
from typing import List, Optional

class QuestionRequest(BaseModel):
    question: str
    top_k: int = 5
    document_id: Optional[str] = None
    direct_retrieval: Optional[bool] = False

class AnswerResponse(BaseModel):
    answer: str
    sources: List[dict]
    model_used: str

class QuizRequest(BaseModel):
    num_questions: int = 5
    difficulty: str = "medium"
    document_id: Optional[str] = None

class QuizQuestion(BaseModel):
    question: str
    options: List[str]
    correct_answer: str
    explanation: str

class QuizResponse(BaseModel):
    questions: List[QuizQuestion]
    total: int
    difficulty: str

class FlashcardRequest(BaseModel):
    num_cards: int = 10
    document_id: Optional[str] = None

class Flashcard(BaseModel):
    front: str
    back: str
    topic: str

class FlashcardsResponse(BaseModel):
    flashcards: List[Flashcard]
    total: int

class SummaryRequest(BaseModel):
    document_id: Optional[str] = None
    length: str = "medium"

class SummaryResponse(BaseModel):
    summary: str
    key_points: List[str]
    word_count: int

class StudyPlanRequest(BaseModel):
    exam_date: str
    hours_per_day: float
    subjects: List[str]
    difficulty_level: str = "medium"

class StudyPlanResponse(BaseModel):
    plan: List[dict]
    total_days: int
    total_hours: float
    tips: List[str]

class UploadResponse(BaseModel):
    message: str
    document_id: str
    filename: str
    chunks: int
    pages: int
