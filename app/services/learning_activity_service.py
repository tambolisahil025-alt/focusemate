from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import models


def award_activity(
    db: Session,
    user: models.User,
    *,
    activity_type: str,
    topic: str | None,
    event_key: str,
    xp: int,
    award_xp: bool = True,
) -> tuple[models.LearningActivity, bool]:
    existing = db.query(models.LearningActivity).filter(
        models.LearningActivity.event_key == event_key
    ).first()
    if existing:
        return existing, False

    activity = models.LearningActivity(
        user_id=user.id,
        activity_type=activity_type,
        topic=(topic or "").strip()[:200] or None,
        xp_earned=max(0, int(xp)),
        event_key=event_key,
    )
    db.add(activity)
    if xp > 0 and award_xp:
        user.xp = (user.xp or 0) + int(xp)
        user.level = max(1, (user.xp // 100) + 1)
    db.flush()
    return activity, True


def get_learning_stats(db: Session, user: models.User) -> dict:
    today = datetime.now(timezone.utc).date()
    activity_dates = [
        row[0] for row in db.query(func.date(models.LearningActivity.created_at)).filter(
            models.LearningActivity.user_id == user.id
        ).distinct().all() if row[0] is not None
    ]
    activity_dates.extend(
        row[0] for row in db.query(func.date(models.QuizAttempt.created_at)).filter(
            models.QuizAttempt.user_id == user.id
        ).distinct().all() if row[0] is not None
    )
    def as_date(value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    dates = sorted({as_date(value) for value in activity_dates})

    current_streak = 0
    start = today if today in dates else today - timedelta(days=1) if today - timedelta(days=1) in dates else None
    cursor = start
    while cursor and cursor in dates:
        current_streak += 1
        cursor -= timedelta(days=1)

    best_streak = run = 0
    previous = None
    for active_day in dates:
        run = run + 1 if previous and active_day == previous + timedelta(days=1) else 1
        best_streak = max(best_streak, run)
        previous = active_day

    start_of_today = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    daily_xp = db.query(func.coalesce(func.sum(models.LearningActivity.xp_earned), 0)).filter(
        models.LearningActivity.user_id == user.id,
        models.LearningActivity.created_at >= start_of_today,
    ).scalar() or 0

    attempts = db.query(models.QuizAttempt).filter(models.QuizAttempt.user_id == user.id).all()
    resources_added = db.query(models.CourseResource).filter(models.CourseResource.added_by_id == user.id).count()
    brainstorms = db.query(models.LearningActivity).filter(
        models.LearningActivity.user_id == user.id,
        models.LearningActivity.activity_type == "brainstorm_complete",
    ).count()

    badges = []
    if attempts:
        badges.append({"id": "first_quiz", "name": "First Quiz"})
    if any(attempt.percentage == 100 for attempt in attempts):
        badges.append({"id": "perfect_score", "name": "Perfect Score"})
    if len(attempts) >= 5:
        badges.append({"id": "quiz_explorer", "name": "Quiz Explorer"})
    if len(attempts) >= 10:
        badges.append({"id": "quiz_master", "name": "Quiz Master"})
    if resources_added >= 1:
        badges.append({"id": "resource_collector", "name": "Resource Collector"})
    if brainstorms >= 1:
        badges.append({"id": "brainstorm_starter", "name": "Brainstorm Starter"})
    if current_streak >= 7:
        badges.append({"id": "seven_day_streak", "name": "7-Day Learning Streak"})

    topic_rows = {}
    for attempt in attempts:
        entry = topic_rows.setdefault(attempt.topic, {"topic": attempt.topic, "quizzes": 0, "best_score": 0, "resources_studied": 0, "brainstorms": 0})
        entry["quizzes"] += 1
        entry["best_score"] = max(entry["best_score"], attempt.percentage)
    for activity in db.query(models.LearningActivity).filter(
        models.LearningActivity.user_id == user.id,
        models.LearningActivity.topic.isnot(None),
    ).all():
        entry = topic_rows.setdefault(activity.topic, {"topic": activity.topic, "quizzes": 0, "best_score": 0, "resources_studied": 0, "brainstorms": 0})
        if activity.activity_type == "resource_studied":
            entry["resources_studied"] += 1
        elif activity.activity_type == "brainstorm_complete":
            entry["brainstorms"] += 1

    xp = user.xp or 0
    return {
        "xp": xp,
        "level": user.level or 1,
        "current_level_xp": xp % 100,
        "xp_to_next_level": 100 - (xp % 100),
        "badges": badges,
        "daily_xp": int(daily_xp),
        "daily_xp_target": 30,
        "current_streak": current_streak,
        "best_streak": best_streak,
        "topic_progress": list(topic_rows.values()),
    }
