import math
import json
import logging
import re
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, load_only

from app.api.deps import get_current_user, get_db
from app.db import models
from app.schemas import schemas
from app.services.groq_service import get_groq_service
from app.services.learning_activity_service import award_activity, get_learning_stats

router = APIRouter(prefix="/quiz", tags=["quiz"])
logger = logging.getLogger(__name__)


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
async def generate_quiz(
    payload: schemas.QuizGenerateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    topic = payload.topic.strip()
    difficulty = payload.difficulty.lower().strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")
    if difficulty not in {"easy", "medium", "hard"}:
        raise HTTPException(status_code=400, detail="Difficulty must be easy, medium, or hard")
    if payload.question_count < 1 or payload.question_count > 20:
        raise HTTPException(status_code=400, detail="Question count must be between 1 and 20")
    source = payload.source if payload.source in {"topic", "resources", "topic_resources"} else None
    if source is None:
        raise HTTPException(status_code=400, detail="Choose a valid quiz source")
    resource_ids = list(dict.fromkeys(payload.resource_ids))
    if source != "topic" and not resource_ids:
        raise HTTPException(status_code=400, detail="Select at least one preparation resource")
    resource_context = []
    if payload.course_id is not None:
        membership = db.query(models.CourseMember).filter(
            models.CourseMember.course_id == payload.course_id,
            models.CourseMember.user_id == current_user.id,
        ).first()
        if not membership:
            raise HTTPException(status_code=403, detail="You do not have access to this course")
    if resource_ids:
        if payload.course_id is None:
            raise HTTPException(status_code=400, detail="A course is required to use preparation resources")
        resources = db.query(models.CourseResource).filter(
            models.CourseResource.course_id == payload.course_id,
            models.CourseResource.id.in_(resource_ids),
            models.CourseResource.topic.ilike(topic),
        ).all()
        if len(resources) != len(resource_ids):
            raise HTTPException(status_code=404, detail="One or more selected resources were not found for this topic")
        resource_context = [{
            "title": item.title,
            "resource_type": item.resource_type,
            "description": (item.description or "").strip()[:1000],
        } for item in resources]

    prior_attempts = db.query(models.QuizAttempt).filter(
        models.QuizAttempt.user_id == current_user.id,
        models.QuizAttempt.topic.ilike(topic),
    ).options(
        load_only(models.QuizAttempt.id, models.QuizAttempt.percentage, models.QuizAttempt.created_at)
    ).order_by(models.QuizAttempt.created_at.desc()).limit(5).all()
    performance_context = None
    if prior_attempts:
        average = round(sum(item.percentage for item in prior_attempts) / len(prior_attempts))
        performance_context = f"The learner's actual average score on this topic across their last {len(prior_attempts)} quizzes is {average}%. Adapt the difficulty and revisit foundations if the score is below 60%. Do not invent specific weak subtopics."
    try:
        raw = await (await get_groq_service()).generate_quiz(
            topic, payload.subject, difficulty, payload.question_count,
            resource_context=resource_context,
            performance_context=performance_context,
        )
        questions = _validate_questions(raw, topic, difficulty)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="The AI returned an invalid quiz. Please retry.") from exc
    if len(questions) != payload.question_count:
        raise HTTPException(status_code=502, detail="The AI returned an incomplete quiz. Please retry.")
    return schemas.QuizGenerateResponse(
        topic=topic, subject=payload.subject, difficulty=difficulty, questions=questions,
        course_id=payload.course_id, resource_ids=resource_ids, source=source,
    )


@router.post("/complete", response_model=schemas.QuizAttemptResponse)
def complete_quiz(payload: schemas.QuizCompleteRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if payload.question_count < 1 or not 0 <= payload.correct_answers <= payload.question_count:
        raise HTTPException(status_code=400, detail="Invalid quiz result")
    difficulty = payload.difficulty.lower()
    bonus = {"easy": 0, "medium": 5, "hard": 15}.get(difficulty, 0)
    score = round((payload.correct_answers / payload.question_count) * 100)
    xp_earned = 10 + (payload.correct_answers * 5) + bonus
    if payload.source not in {"topic", "resources", "topic_resources"}:
        raise HTTPException(status_code=400, detail="Choose a valid quiz source")
    source = payload.source
    resource_ids = list(dict.fromkeys(payload.resource_ids))
    if source != "topic" and not resource_ids:
        raise HTTPException(status_code=400, detail="Select at least one preparation resource")
    if payload.course_id is not None:
        membership = db.query(models.CourseMember).filter(
            models.CourseMember.course_id == payload.course_id,
            models.CourseMember.user_id == current_user.id,
        ).first()
        if not membership:
            raise HTTPException(status_code=403, detail="You do not have access to this course")
    if resource_ids:
        if payload.course_id is None:
            raise HTTPException(status_code=400, detail="A course is required for quiz resource association")
        linked_resources = db.query(models.CourseResource.id).filter(
            models.CourseResource.course_id == payload.course_id,
            models.CourseResource.topic.ilike(payload.topic.strip()),
            models.CourseResource.id.in_(resource_ids),
        ).all()
        if len(linked_resources) != len(resource_ids):
            raise HTTPException(status_code=404, detail="One or more selected course resources were not found")
    current_user.xp = (current_user.xp or 0) + xp_earned
    current_user.level = max(1, math.floor(current_user.xp / 100) + 1)
    attempt = models.QuizAttempt(
        user_id=current_user.id, subject=payload.subject, topic=payload.topic.strip(),
        difficulty=difficulty, question_count=payload.question_count,
        correct_answers=payload.correct_answers, score=score, percentage=score,
        xp_earned=xp_earned, course_id=payload.course_id, source=source,
        resource_ids=resource_ids,
    )
    db.add(attempt)
    db.add(models.Notification(
        user_id=current_user.id, notification_type="quiz_result",
        title="Quiz completed", body=f"{score}% on {payload.topic.strip()} (+{xp_earned} XP)",
    ))
    db.flush()
    award_activity(
        db, current_user, activity_type="quiz_complete", topic=payload.topic,
        event_key=f"quiz:{attempt.id}", xp=xp_earned, award_xp=False,
    )
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
    return get_learning_stats(db, current_user)


def _parse_brainstorm_json(response: str) -> dict:
    candidate = response.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        parsed = None
        for start, character in enumerate(candidate):
            if character != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[start:])
                break
            except json.JSONDecodeError:
                continue
    if not isinstance(parsed, dict):
        raise ValueError("AI returned invalid brainstorm JSON")
    return parsed


def _authorized_resource_context(db: Session, user_id: int, course_id: int | None, resource_ids: list[int], topic: str):
    if course_id is None:
        if resource_ids:
            raise HTTPException(status_code=400, detail="A course is required to use preparation resources")
        return []
    membership = db.query(models.CourseMember).filter(
        models.CourseMember.course_id == course_id,
        models.CourseMember.user_id == user_id,
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="You do not have access to this course")
    if not resource_ids:
        return []
    ids = list(dict.fromkeys(resource_ids))
    resources = db.query(models.CourseResource).filter(
        models.CourseResource.course_id == course_id,
        models.CourseResource.topic.ilike(topic.strip()),
        models.CourseResource.id.in_(ids),
    ).all()
    if len(resources) != len(ids):
        raise HTTPException(status_code=404, detail="One or more selected resources were not found for this topic")
    return [{
        "title": item.title,
        "resource_type": item.resource_type,
        "description": (item.description or "").strip()[:1000],
    } for item in resources]


@router.post("/brainstorm/turn", response_model=schemas.BrainstormTurnResponse)
async def brainstorm_turn(
    payload: schemas.BrainstormTurnRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    topic = payload.topic.strip()
    if payload.phase not in {"start", "answer"}:
        raise HTTPException(status_code=400, detail="Invalid brainstorm phase")
    resource_context = _authorized_resource_context(db, current_user.id, payload.course_id, payload.resource_ids, topic)
    try:
        attempts = db.query(models.QuizAttempt).filter(
            models.QuizAttempt.user_id == current_user.id,
            models.QuizAttempt.topic.ilike(topic),
        ).options(
            load_only(models.QuizAttempt.id, models.QuizAttempt.percentage, models.QuizAttempt.created_at)
        ).order_by(models.QuizAttempt.created_at.desc()).limit(5).all()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Could not load quiz history for brainstorm; continuing without it", exc_info=True)
        attempts = []
    performance = None
    if attempts:
        average = round(sum(item.percentage for item in attempts) / len(attempts))
        performance = f"Actual recent quiz average on this topic: {average}% ({len(attempts)} quizzes). Adapt support accordingly; do not claim weak subtopics that are not in the records."

    context = ""
    if resource_context:
        context += " Selected course resource titles, types, and user-provided descriptions (external contents were not fetched): " + "; ".join(
            f"{item['title']} ({item['resource_type']})" + (f": {item['description']}" if item["description"] else "")
            for item in resource_context[:20]
        )
    if performance:
        context += " " + performance
    system_prompt = f"""You run a {payload.total_rounds}-round study question game. Output only a JSON object with keys activity_type, feedback, next_prompt, recommendation, completed.
activity_type must be one of rapid_fire, true_false, recall, quick_mcq, scenario.
Start phase: feedback is null, next_prompt is one short challenge, completed is false.
Answer phase: give brief accurate feedback on the student's answer. Before the final round, offer one different short next_prompt and set recommendation to null. On the final round, set completed to true, set next_prompt to null, and give one specific, encouraging study recommendation that would help the learner improve their understanding of {topic}. Never invent course-resource contents. Keep wording clear and do not include markdown."""
    history = [
        {"role": item.get("role"), "content": str(item.get("content") or "")[:800]}
        for item in payload.history[-6:]
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    if payload.phase == "start":
        if history or not payload.topic.strip():
            history = []
        history.append({"role": "user", "content": f"Start a quick brainstorm about {topic}.{context}"})
        completed_by_count = False
    else:
        if not payload.prompt or not payload.answer:
            raise HTTPException(status_code=400, detail="Include the prompt and your answer")
        if payload.round_number > payload.total_rounds:
            raise HTTPException(status_code=400, detail="Round number cannot exceed the total rounds")
        completed_by_count = payload.round_number >= payload.total_rounds
        history.append({"role": "user", "content": f"The challenge was: {payload.prompt[:800]}\nThe student's answer is: {payload.answer[:1600]}\nTopic: {topic}.{context}\nThis is answer {payload.round_number} of {payload.total_rounds}. Set completed=true only on the final answer."})
    try:
        ai_text = await (await get_groq_service()).chat(
            history, system_prompt=system_prompt, max_tokens=700, temperature=0.5,
        )
        parsed = _parse_brainstorm_json(ai_text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Quick Brainstorm could not generate a valid activity. Please retry.") from exc

    activity_type = parsed.get("activity_type")
    if activity_type not in {"rapid_fire", "true_false", "recall", "quick_mcq", "scenario"}:
        activity_type = "recall"
    feedback = str(parsed.get("feedback") or "").strip() or None
    next_prompt = str(parsed.get("next_prompt") or "").strip() or None
    recommendation = str(parsed.get("recommendation") or "").strip() or None
    completed = payload.phase == "answer" and completed_by_count
    if payload.phase == "start" and not next_prompt:
        raise HTTPException(status_code=502, detail="Quick Brainstorm returned no challenge. Please retry.")
    if payload.phase == "answer" and not feedback:
        raise HTTPException(status_code=502, detail="Quick Brainstorm returned no feedback. Please retry.")
    if completed:
        next_prompt = None
        if not recommendation:
            recommendation = f"Review one example of {topic} and explain the key idea in your own words."
    else:
        recommendation = None
        if payload.phase == "answer" and not next_prompt:
            raise HTTPException(status_code=502, detail="Quick Brainstorm returned no next challenge. Please retry.")
    return schemas.BrainstormTurnResponse(
        activity_type=activity_type, feedback=feedback,
        next_prompt=next_prompt, recommendation=recommendation, completed=completed,
    )


