from datetime import datetime, date
from fastapi import APIRouter, HTTPException
from models.schemas import StudyPlanRequest, StudyPlanResponse

router = APIRouter()

@router.post("/study-plan", response_model=StudyPlanResponse)
async def create_study_plan(request: StudyPlanRequest):
    try:
        exam_date = datetime.strptime(request.exam_date, "%Y-%m-%d").date()
        today = date.today()
        total_days = (exam_date - today).days
    except ValueError:
        raise HTTPException(status_code=400, detail="exam_date must be YYYY-MM-DD format")

    if total_days <= 0:
        raise HTTPException(status_code=400, detail="Exam date must be in the future")
    if total_days > 365:
        raise HTTPException(status_code=400, detail="Exam date must be within one year")

    plan = []
    subjects = request.subjects or ["General Study"]

    for i in range(total_days):
        day_num = i + 1
        subject = subjects[i % len(subjects)]
        plan.append({
            "day": day_num,
            "date": f"Day {day_num}",
            "subject": subject,
            "topics": [
                f"Review {subject} core concepts",
                f"Practice {subject} problems and exercises"
            ],
            "hours": request.hours_per_day,
            "goal": f"Master key {subject} topics and reinforce understanding."
        })

    tips = [
        "Use active recall — quiz yourself instead of rereading notes.",
        "Apply spaced repetition: review on Day 1, Day 3, and Day 7.",
        "Use the Pomodoro technique (25 min study, 5 min rest).",
        "Focus on high-weight exam topics from past papers.",
        "Sleep well — memory consolidation happens during sleep.",
        "Teach the concept to someone else to test true understanding."
    ]

    return StudyPlanResponse(
        plan=plan,
        total_days=total_days,
        total_hours=round(total_days * request.hours_per_day, 1),
        tips=tips
    )
