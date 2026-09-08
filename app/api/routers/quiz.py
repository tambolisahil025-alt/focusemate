import math
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.db import models
from app.schemas import schemas
from app.services.groq_service import get_groq_service

router = APIRouter(prefix="/quiz", tags=["quiz"])


def _validate_questions(items: list, topic: str, difficulty: str) -> List[schemas.QuizQuestion]:
    questions = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question", "")).strip()
        options = item.get("options")
        answer = str(item.get("correct_answer", item.get("correctAnswer", ""))).strip()
        explanation = str(item.get("explanation", "")).strip()
        if not question or question.lower() in seen or not isinstance(options, list) or len(options) != 4:
            continue
        options = [str(option).strip() for option in options]
        if len(set(options)) != 4 or answer not in options or not explanation:
            continue
        seen.add(question.lower())
        questions.append(schemas.QuizQuestion(
            question=question, options=options, correct_answer=answer,
            explanation=explanation, difficulty=difficulty, topic=topic,
        ))
    return questions


@router.post("/generate", response_model=schemas.QuizGenerateResponse)
async def generate_quiz(payload: schemas.QuizGenerateRequest, current_user: models.User = Depends(get_current_user)):
    topic = payload.topic.strip()
    difficulty = payload.difficulty.lower().strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")
    if difficulty not in {"easy", "medium", "hard"}:
        raise HTTPException(status_code=400, detail="Difficulty must be easy, medium, or hard")
    if payload.question_count < 1 or payload.question_count > 20:
        raise HTTPException(status_code=400, detail="Question count must be between 1 and 20")
    try:
        raw = await (await get_groq_service()).generate_quiz(topic, payload.subject, difficulty, payload.question_count)
        questions = _validate_questions(raw, topic, difficulty)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="The AI returned an invalid quiz. Please retry.") from exc
    if len(questions) != payload.question_count:
        raise HTTPException(status_code=502, detail="The AI returned an incomplete quiz. Please retry.")
    return schemas.QuizGenerateResponse(topic=topic, subject=payload.subject, difficulty=difficulty, questions=questions)


@router.post("/complete", response_model=schemas.QuizAttemptResponse)
def complete_quiz(payload: schemas.QuizCompleteRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if payload.question_count < 1 or not 0 <= payload.correct_answers <= payload.question_count:
        raise HTTPException(status_code=400, detail="Invalid quiz result")
    difficulty = payload.difficulty.lower()
    bonus = {"easy": 0, "medium": 5, "hard": 15}.get(difficulty, 0)
    score = round((payload.correct_answers / payload.question_count) * 100)
    xp_earned = 10 + (payload.correct_answers * 5) + bonus
    current_user.xp = (current_user.xp or 0) + xp_earned
    current_user.level = max(1, math.floor(current_user.xp / 100) + 1)
    attempt = models.QuizAttempt(
        user_id=current_user.id, subject=payload.subject, topic=payload.topic.strip(),
        difficulty=difficulty, question_count=payload.question_count,
        correct_answers=payload.correct_answers, score=score, percentage=score,
        xp_earned=xp_earned,
    )
    db.add(attempt)
    db.add(models.Notification(
        user_id=current_user.id, notification_type="quiz_result",
        title="Quiz completed", body=f"{score}% on {payload.topic.strip()} (+{xp_earned} XP)",
    ))
    db.commit()
    db.refresh(attempt)
    attempt.user_xp = current_user.xp
    attempt.user_level = current_user.level
    return attempt


@router.get("/attempts", response_model=list[schemas.QuizAttemptResponse])
def get_quiz_attempts(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.QuizAttempt).filter(models.QuizAttempt.user_id == current_user.id).order_by(models.QuizAttempt.created_at.desc()).limit(50).all()


@router.get("/gamification", response_model=schemas.GamificationResponse)
def get_gamification(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    attempts = db.query(models.QuizAttempt).filter(models.QuizAttempt.user_id == current_user.id).all()
    badges = []
    if attempts:
        badges.append({"id": "first_quiz", "name": "First Steps"})
    if any(attempt.percentage == 100 for attempt in attempts):
        badges.append({"id": "perfect_score", "name": "Perfect Score"})
    if len(attempts) >= 5:
        badges.append({"id": "quiz_explorer", "name": "Quiz Explorer"})
    if len(attempts) >= 10:
        badges.append({"id": "quiz_master", "name": "Quiz Master"})
    xp = current_user.xp or 0
    return {
        "xp": xp,
        "level": current_user.level or 1,
        "current_level_xp": xp % 100,
        "xp_to_next_level": 100 - (xp % 100),
        "badges": badges,
    }