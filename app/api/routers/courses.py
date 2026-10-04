from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.db import models
from app.services.learning_activity_service import award_activity
from app.services.storage_service import delete_storage_url, upload_upload_file

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
        "pending_join_request_count": (
            db.query(models.CourseJoinRequest)
            .filter(
                models.CourseJoinRequest.course_id == course.id,
                models.CourseJoinRequest.status == "pending",
            )
            .count()
            if course.owner_id == current_user_id
            else 0
        ),
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
    db.flush()
    db.refresh(course)
    response = serialize_course(db, course, current_user.id)
    db.commit()
    return response


@router.post("/join")
def join_course_by_code(payload: dict, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    code = str(payload.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Course code is required")
    course = db.query(models.Course).filter(models.Course.code == code).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return request_course_join(course, db, current_user)


def request_course_join(course: models.Course, db: Session, current_user: models.User) -> dict:
    membership = db.query(models.CourseMember).filter(
        models.CourseMember.course_id == course.id,
        models.CourseMember.user_id == current_user.id,
    ).first()
    if membership:
        return {"status": "joined", "course_id": course.id, "course_name": course.name}

    existing = db.query(models.CourseJoinRequest).filter(
        models.CourseJoinRequest.course_id == course.id,
        models.CourseJoinRequest.user_id == current_user.id,
        models.CourseJoinRequest.status == "pending",
    ).first()
    if existing:
        return {"status": "pending", "course_id": course.id, "course_name": course.name}

    request = models.CourseJoinRequest(course_id=course.id, user_id=current_user.id)
    db.add(request)
    db.add(models.Notification(
        user_id=course.owner_id,
        notification_type="course_join_request",
        title="Course join request",
        body=f"{current_user.name} requested to join '{course.name}'.",
        actor_id=current_user.id,
        actor_name=current_user.name,
    ))
    db.commit()
    return {"status": "pending", "course_id": course.id, "course_name": course.name}


@router.get("/{course_id}")
def get_course(course_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    course = get_authorized_course(db, course_id, current_user.id)
    return serialize_course(db, course, current_user.id)


@router.post("/{course_id}/join")
def join_course(course_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    course = db.query(models.Course).filter(models.Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return request_course_join(course, db, current_user)


@router.get("/{course_id}/join-requests")
def list_course_join_requests(course_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    course = db.query(models.Course).filter(models.Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the course instructor can review join requests")

    requests = db.query(models.CourseJoinRequest).filter(
        models.CourseJoinRequest.course_id == course_id,
        models.CourseJoinRequest.status == "pending",
    ).order_by(models.CourseJoinRequest.created_at.asc()).all()
    return {
        "requests": [{
            "id": item.id,
            "user_id": item.user_id,
            "name": item.user.name,
            "email": item.user.email,
            "created_at": item.created_at,
        } for item in requests]
    }


@router.post("/{course_id}/join-requests/{request_id}")
def review_course_join_request(
    course_id: int,
    request_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    course = db.query(models.Course).filter(models.Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the course instructor can review join requests")

    join_request = db.query(models.CourseJoinRequest).filter(
        models.CourseJoinRequest.id == request_id,
        models.CourseJoinRequest.course_id == course_id,
        models.CourseJoinRequest.status == "pending",
    ).first()
    if not join_request:
        raise HTTPException(status_code=404, detail="Pending course join request not found")

    action = str(payload.get("action") or "").strip().lower()
    if action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Action must be approve or reject")

    if action == "approve":
        membership = db.query(models.CourseMember).filter(
            models.CourseMember.course_id == course_id,
            models.CourseMember.user_id == join_request.user_id,
        ).first()
        if not membership:
            db.add(models.CourseMember(course_id=course_id, user_id=join_request.user_id, role="student"))
        join_request.status = "approved"
        message = f"Your request to join '{course.name}' was approved."
    else:
        join_request.status = "rejected"
        message = f"Your request to join '{course.name}' was declined."

    join_request.reviewed_at = datetime.now(timezone.utc)
    db.add(models.Notification(
        user_id=join_request.user_id,
        notification_type="course_join_result",
        title="Course join request update",
        body=message,
        actor_id=current_user.id,
        actor_name=current_user.name,
    ))
    db.commit()
    return {"status": join_request.status, "course_id": course_id}


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


@router.delete("/{course_id}")
async def delete_course(course_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    course = db.query(models.Course).filter(models.Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the course instructor can delete this course")

    resources = db.query(models.CourseResource).filter(
        models.CourseResource.course_id == course_id
    ).all()
    try:
        for resource in resources:
            await delete_storage_url(resource.url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to remove course resources from cloud storage") from exc

    db.query(models.QuizAttempt).filter(
        models.QuizAttempt.course_id == course_id
    ).update(
        {
            models.QuizAttempt.course_id: None,
            models.QuizAttempt.resource_ids: [],
        },
        synchronize_session=False,
    )
    db.delete(course)
    db.commit()
    return {"detail": "Course deleted"}


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


@router.post("/{course_id}/resources/upload")
async def upload_course_resource(
    course_id: int,
    topic: str = Form(...),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    get_authorized_course(db, course_id, current_user.id)
    if not topic.strip():
        raise HTTPException(status_code=400, detail="A resource topic is required")
    if file.size is not None and file.size > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Course resource files must be 50 MB or smaller")

    try:
        resource_url = await upload_upload_file(file, f"courses/{course_id}/resources")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to store course resource in cloud storage") from exc

    filename = file.filename or "Course resource"
    content_type = (file.content_type or "").lower()
    resource = models.CourseResource(
        course_id=course_id,
        added_by_id=current_user.id,
        topic=topic.strip(),
        title=filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
        url=resource_url,
        resource_type="study_link" if content_type.startswith(("image/", "video/")) else "notes",
        thumbnail_url=None,
        source="Uploaded file",
        description=description.strip() if description else None,
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
