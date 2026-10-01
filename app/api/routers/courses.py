from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.db import models
from app.services.learning_activity_service import award_activity

router = APIRouter(prefix="/courses", tags=["courses"])


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    code: str = Field(min_length=1, max_length=40)


class CourseResourceCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=8, max_length=2048)
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Enter a valid public HTTP or HTTPS resource URL")
        return value.strip()


def infer_resource_metadata(url: str, title: str | None = None) -> dict:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    is_youtube = host in {"youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com"} or host.endswith(".youtube.com")
    query = parse_qs(parsed.query)
    video_id = query.get("v", [None])[0]
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0] or None
    elif not video_id and "/shorts/" in parsed.path:
        video_id = parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]

    if is_youtube and query.get("list"):
        resource_type = "youtube_playlist"
        default_title = "YouTube lecture playlist"
    elif is_youtube and video_id:
        resource_type = "youtube_video"
        default_title = "YouTube lecture"
    elif parsed.path.lower().endswith(".pdf") or any(term in parsed.path.lower() for term in ("notes", "lecture", "document")):
        resource_type = "notes"
        default_title = "Study notes"
    elif any(term in parsed.path.lower() for term in ("article", "blog", "guide")):
        resource_type = "article"
        default_title = "Study article"
    else:
        resource_type = "study_link"
        default_title = "Study link"

    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if resource_type == "youtube_video" and video_id else None
    return {
        "resource_type": resource_type,
        "title": (title or "").strip() or default_title,
        "source": host,
        "thumbnail_url": thumbnail_url,
    }


def serialize_course_resource(resource: models.CourseResource) -> dict:
    return {
        "id": resource.id,
        "course_id": resource.course_id,
        "topic": resource.topic,
        "title": resource.title,
        "url": resource.url,
        "link": resource.url,
        "resource_type": resource.resource_type,
        "thumbnail_url": resource.thumbnail_url,
        "source": resource.source,
        "description": resource.description,
        "added_by_id": resource.added_by_id,
        "created_at": resource.created_at,
    }


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


@router.get("/{course_id}/resources")
def list_course_resources(
    course_id: int,
    topic: str | None = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    get_authorized_course(db, course_id, current_user.id)
    query = db.query(models.CourseResource).filter(models.CourseResource.course_id == course_id)
    if topic and topic.strip():
        query = query.filter(models.CourseResource.topic.ilike(topic.strip()))
    resources = query.order_by(models.CourseResource.created_at.desc()).all()
    return [serialize_course_resource(resource) for resource in resources]


@router.post("/{course_id}/resources")
def add_course_resource(
    course_id: int,
    payload: CourseResourceCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    get_authorized_course(db, course_id, current_user.id)
    metadata = infer_resource_metadata(payload.url, payload.title)
    resource = models.CourseResource(
        course_id=course_id,
        added_by_id=current_user.id,
        topic=payload.topic.strip(),
        url=payload.url,
        title=metadata["title"],
        resource_type=metadata["resource_type"],
        thumbnail_url=metadata["thumbnail_url"],
        source=metadata["source"],
        description=payload.description.strip() if payload.description else None,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return serialize_course_resource(resource)


@router.delete("/{course_id}/resources/{resource_id}")
def delete_course_resource(
    course_id: int,
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    get_authorized_course(db, course_id, current_user.id)
    resource = db.query(models.CourseResource).filter(
        models.CourseResource.id == resource_id,
        models.CourseResource.course_id == course_id,
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Course resource not found")
    membership = db.query(models.CourseMember).filter(
        models.CourseMember.course_id == course_id,
        models.CourseMember.user_id == current_user.id,
    ).first()
    if resource.added_by_id != current_user.id and membership.role != "instructor":
        raise HTTPException(status_code=403, detail="Only the person who added this resource or the instructor can remove it")
    db.delete(resource)
    db.commit()
    return {"detail": "Resource removed"}


@router.post("/{course_id}/resources/{resource_id}/studied")
def mark_course_resource_studied(
    course_id: int,
    resource_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    get_authorized_course(db, course_id, current_user.id)
    resource = db.query(models.CourseResource).filter(
        models.CourseResource.id == resource_id,
        models.CourseResource.course_id == course_id,
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Course resource not found")
    day_key = datetime.now(timezone.utc).date().isoformat()
    activity, created = award_activity(
        db, current_user, activity_type="resource_studied", topic=resource.topic,
        event_key=f"resource:{current_user.id}:{resource.id}:{day_key}", xp=5,
    )
    db.commit()
    return {"xp_earned": activity.xp_earned if created else 0, "detail": "Study activity recorded"}
