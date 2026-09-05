from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.db import models

router = APIRouter(prefix="/courses", tags=["courses"])


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    code: str = Field(min_length=1, max_length=40)


def serialize_course(db: Session, course: models.Course, current_user_id: int) -> dict:
    members = db.query(models.CourseMember).filter(models.CourseMember.course_id == course.id).all()
    users = {
        user.id: user
        for user in db.query(models.User).filter(models.User.id.in_([member.user_id for member in members])).all()
    } if members else {}
    return {
        "id": course.id,
        "name": course.name,
        "description": course.description,
        "code": course.code,
        "owner_id": course.owner_id,
        "instructor": next((user.name for user in users.values() if user.id == course.owner_id), None),
        "member_count": len(members),
        "members": [
            {"id": member.user_id, "name": users[member.user_id].name, "avatar": users[member.user_id].avatar, "role": member.role}
            for member in members if member.user_id in users
        ],
        "is_member": any(member.user_id == current_user_id for member in members),
        "role": next((member.role for member in members if member.user_id == current_user_id), None),
        "created_at": course.created_at,
    }


def get_authorized_course(db: Session, course_id: int, user_id: int) -> models.Course:
    course = db.query(models.Course).filter(models.Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    member = db.query(models.CourseMember).filter(
        models.CourseMember.course_id == course_id,
        models.CourseMember.user_id == user_id,
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="You do not have access to this course")
    return course


@router.get("")
def list_courses(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    courses = db.query(models.Course).join(models.CourseMember).filter(
        models.CourseMember.user_id == current_user.id
    ).order_by(models.Course.created_at.desc()).all()
    return [serialize_course(db, course, current_user.id) for course in courses]


@router.post("")
def create_course(payload: CourseCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    code = payload.code.strip().upper()
    if db.query(models.Course).filter(models.Course.code == code).first():
        raise HTTPException(status_code=409, detail="A course with this code already exists")
    course = models.Course(
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        code=code,
        owner_id=current_user.id,
    )
    db.add(course)
    db.flush()
    db.add(models.CourseMember(course_id=course.id, user_id=current_user.id, role="instructor"))
    db.commit()
    db.refresh(course)
    return serialize_course(db, course, current_user.id)


@router.post("/join")
def join_course_by_code(payload: dict, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    code = str(payload.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Course code is required")
    course = db.query(models.Course).filter(models.Course.code == code).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return join_course(course.id, db, current_user)


@router.get("/{course_id}")
def get_course(course_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    course = get_authorized_course(db, course_id, current_user.id)
    return serialize_course(db, course, current_user.id)


@router.post("/{course_id}/join")
def join_course(course_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    course = db.query(models.Course).filter(models.Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    existing = db.query(models.CourseMember).filter(
        models.CourseMember.course_id == course_id,
        models.CourseMember.user_id == current_user.id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="You already joined this course")
    db.add(models.CourseMember(course_id=course_id, user_id=current_user.id, role="student"))
    db.commit()
    return serialize_course(db, course, current_user.id)


@router.post("/{course_id}/leave")
def leave_course(course_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    get_authorized_course(db, course_id, current_user.id)
    membership = db.query(models.CourseMember).filter(
        models.CourseMember.course_id == course_id,
        models.CourseMember.user_id == current_user.id,
    ).first()
    if membership.role == "instructor":
        raise HTTPException(status_code=400, detail="The course instructor cannot leave the course")
    db.delete(membership)
    db.commit()
    return {"detail": "Successfully left course"}