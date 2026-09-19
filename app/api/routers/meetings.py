from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import time
import logging
from typing import Optional
from uuid import uuid4

from app.api.deps import get_db, get_current_user
from app.db import models
from app.core.config import settings
from app.core.security import verify_password, get_password_hash
from app.schemas import schemas
from agora_token_builder import RtcTokenBuilder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["meetings"])

def ensure_meeting_schema(db: Session):
    """Make the two additive meeting columns available on older Render databases.

    The Alembic migration remains the authoritative schema change; this small
    compatibility guard prevents an older deployment that skipped the latest
    migration from failing every Meeting ORM query with PostgreSQL F405.
    """
    try:
        bind = db.get_bind()
        inspector = __import__("sqlalchemy").inspect(bind)
        columns = {c["name"] for c in inspector.get_columns("meetings")}
        from sqlalchemy import text as sql_text
        if "topic" not in columns:
            bind.execute(sql_text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS topic VARCHAR(120)"))
        if "password_hash" not in columns:
            bind.execute(sql_text("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)"))
    except Exception:
        db.rollback()
        logger.exception("Unable to reconcile meeting schema")
        raise

def meeting_summary(meeting: models.Meeting):
    return {
        "meeting_id": meeting.id,
        "id": meeting.id,
        "room_id": meeting.room_id,
        "meeting_code": meeting.meeting_code,
        "topic": meeting.topic,
        "has_password": bool(meeting.password_hash),
        "status": meeting.status,
        "host_id": meeting.host_id,
        "auto_accept": meeting.auto_accept,
        "created_at": meeting.created_at,
        "ended_at": meeting.ended_at,
    }

def require_approved_participant(db: Session, meeting_id: int, user_id: int):
    participant = db.query(models.MeetingParticipant).filter(
        models.MeetingParticipant.meeting_id == meeting_id,
        models.MeetingParticipant.user_id == user_id,
    ).first()
    if not participant or participant.status != "approved" or participant.banned:
        raise HTTPException(status_code=403, detail="You are not an approved participant in this meeting")
    return participant


@router.post("/")
def create_meeting(payload: schemas.RoomMeetingCreate | dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    ensure_meeting_schema(db)
    payload_data = payload.model_dump() if hasattr(payload, "model_dump") else payload
    room_id = int(payload_data.get("room_id")) if payload_data.get("room_id") is not None else None
    auto_accept = bool(payload_data.get("auto_accept", False))
    meeting_code = str(payload_data.get("meeting_id") or payload_data.get("meeting_code") or "").strip().upper()
    topic = str(payload_data.get("topic") or "FocusMate Meeting").strip()[:120]
    password = str(payload_data.get("password") or "")
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    membership = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == room_id,
        models.RoomMember.user_id == current_user.id,
    ).first()
    if room.owner_id != current_user.id and (not membership or membership.role not in {"owner", "admin"}):
        raise HTTPException(status_code=403, detail="Only a room owner or admin can create meetings")
    existing = db.query(models.Meeting).filter(
        models.Meeting.room_id == room_id,
        models.Meeting.status != "ended",
    ).order_by(models.Meeting.id.desc()).first()
    if existing:
        return meeting_summary(existing)
    if not meeting_code:
        meeting_code = f"{uuid4().hex[:8].upper()}-{uuid4().hex[:3].upper()}"
    if db.query(models.Meeting).filter(models.Meeting.meeting_code == meeting_code).first():
        raise HTTPException(status_code=409, detail="That Meeting ID is already in use. Choose another ID.")
    if len(meeting_code) < 3 or len(meeting_code) > 32:
        raise HTTPException(status_code=422, detail="Meeting ID must be 3-32 characters.")
    if not password:
        raise HTTPException(status_code=422, detail="A meeting password is required.")
    if not topic:
        raise HTTPException(status_code=422, detail="Meeting topic is required.")
    meeting = models.Meeting(
        room_id=room_id,
        host_id=current_user.id,
        meeting_code=meeting_code,
        topic=topic,
        password_hash=get_password_hash(password),
        auto_accept=auto_accept,
        status="live",
    )
    db.add(meeting)
    db.flush()
    db.add(models.MeetingParticipant(
        meeting_id=meeting.id, user_id=current_user.id, role="host", status="approved", joined_at=datetime.utcnow()
    ))
    room.is_live = True
    db.commit()
    db.refresh(meeting)
    return meeting_summary(meeting)


@router.get("/room/{room_id}/active")
def get_active_room_meeting(room_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    ensure_meeting_schema(db)
    membership = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == room_id,
        models.RoomMember.user_id == current_user.id,
    ).first()
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if not membership and room.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this room")
    meeting = db.query(models.Meeting).filter(
        models.Meeting.room_id == room_id,
        models.Meeting.status != "ended",
    ).order_by(models.Meeting.id.desc()).first()
    return {"meeting": meeting_summary(meeting) if meeting else None}

@router.get("/{meeting_id}")
def get_meeting(meeting_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    ensure_meeting_schema(db)
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    require_approved_participant(db, meeting_id, current_user.id)
    return meeting_summary(meeting)

@router.post("/{meeting_id}/join")
def join_meeting(meeting_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    ensure_meeting_schema(db)
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.status == "ended":
        raise HTTPException(status_code=409, detail="This meeting has ended")

    room = db.query(models.Room).filter(models.Room.id == meeting.room_id).first()
    membership = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == meeting.room_id,
        models.RoomMember.user_id == current_user.id,
    ).first()
    if not membership and current_user.id != meeting.host_id:
        raise HTTPException(status_code=403, detail="You must be a room member to join this meeting")

    participant = db.query(models.MeetingParticipant).filter(
        models.MeetingParticipant.meeting_id == meeting_id,
        models.MeetingParticipant.user_id == current_user.id,
    ).first()
    if participant and participant.banned:
        raise HTTPException(status_code=403, detail="You have been removed from this meeting")
    if not participant:
        participant = models.MeetingParticipant(
            meeting_id=meeting.id, user_id=current_user.id, role="host" if current_user.id == meeting.host_id else "participant",
            status="approved", joined_at=datetime.utcnow(),
        )
        db.add(participant)
    else:
        participant.status = "approved"
        participant.joined_at = participant.joined_at or datetime.utcnow()
        participant.left_at = None
    if room:
        room.is_live = True
    meeting.status = "live"
    db.commit()
    return meeting_summary(meeting)

@router.get("/{meeting_id}/agora-token")
def get_agora_token(meeting_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    ensure_meeting_schema(db)
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.status == "ended":
        raise HTTPException(status_code=409, detail="This meeting has ended")
    require_approved_participant(db, meeting_id, current_user.id)

    if not settings.AGORA_APP_ID or not settings.AGORA_APP_CERTIFICATE:
        raise HTTPException(
            status_code=503,
            detail="Video meetings are not configured on the server. Set AGORA_APP_ID and AGORA_APP_CERTIFICATE.",
        )

    channel_name = f"focusmate_meeting_{meeting.id}"
    expires_at = int(time.time()) + max(60, int(settings.AGORA_TOKEN_TTL_SEC))
    try:
        token = RtcTokenBuilder.buildTokenWithUid(
            settings.AGORA_APP_ID,
            settings.AGORA_APP_CERTIFICATE,
            channel_name,
            int(current_user.id),
            1,  # Role_Publisher; users can publish camera/microphone streams.
            expires_at,
        )
    except Exception as exc:
        logger.exception("Agora token generation failed for meeting %s", meeting_id)
        raise HTTPException(status_code=500, detail="Unable to create the video meeting token") from exc

    return {
        "app_id": settings.AGORA_APP_ID,
        "channel_name": channel_name,
        "token": token,
        "uid": int(current_user.id),
        "expires_at": expires_at,
    }

@router.post("/{meeting_id}/invitations")
def generate_invitation(meeting_id: int, payload: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    ensure_meeting_schema(db)
    single_use = bool(payload.get('single_use', False))
    expires_in = payload.get('expires_in')
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only host can generate invitations")

    raw_token = uuid4().hex
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in or 86400)
    db.add(models.MeetingInvitation(
        meeting_id=meeting.id,
        inviter_id=current_user.id,
        token_hash=raw_token,
        expires_at=expires_at,
        single_use=single_use,
    ))
    db.commit()
    invite_url = f"myapp://meeting/{meeting.meeting_code}?invite={raw_token}"
    return {"invite_url": invite_url, "invite_token": raw_token, "meeting_id": meeting.id, "meeting_code": meeting.meeting_code, "topic": meeting.topic, "expires_in": expires_in or settings.MEETING_INVITE_TTL_SEC}


@router.post("/join-with-invite")
def join_with_invite(payload: schemas.MeetingJoinWithInvite, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    ensure_meeting_schema(db)
    invite_token = payload.invite_token
    inv = db.query(models.MeetingInvitation).filter(
        models.MeetingInvitation.token_hash == invite_token,
        models.MeetingInvitation.used == False,
    ).first()
    if not inv:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")
    if inv.expires_at and inv.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")
    meeting = db.query(models.Meeting).filter(models.Meeting.id == inv.meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.status == "ended":
        raise HTTPException(status_code=409, detail="This meeting has ended")
    if meeting.password_hash and not verify_password(payload.password or "", meeting.password_hash):
        raise HTTPException(status_code=403, detail="Incorrect meeting password")

    existing = db.query(models.MeetingParticipant).filter(
        models.MeetingParticipant.meeting_id == meeting.id,
        models.MeetingParticipant.user_id == current_user.id,
    ).first()
    if existing and existing.banned:
        raise HTTPException(status_code=403, detail="You have been removed from this meeting")
    if existing and existing.status == "approved":
        return {"status": "approved", "meeting_id": meeting.id, "meeting_code": meeting.meeting_code, "host_id": meeting.host_id, "topic": meeting.topic}
    if existing and existing.status == "pending":
        return {"status": "pending", "meeting_id": meeting.id, "meeting_code": meeting.meeting_code, "message": "Join request already submitted", "topic": meeting.topic}

    if inv.single_use:
        inv.used = True
    if meeting.auto_accept:
        participant = existing or models.MeetingParticipant(meeting_id=meeting.id, user_id=current_user.id, role="participant")
        participant.status = "approved"
        participant.joined_at = datetime.utcnow()
        participant.left_at = None
        db.add(participant)
        db.commit()
        return {"status": "approved", "meeting_id": meeting.id, "meeting_code": meeting.meeting_code, "host_id": meeting.host_id, "topic": meeting.topic}

    pending = existing or models.MeetingParticipant(meeting_id=meeting.id, user_id=current_user.id, role="participant")
    pending.status = "pending"
    pending.joined_at = None
    pending.left_at = None
    db.add(pending)
    db.add(models.Notification(
        user_id=meeting.host_id,
        notification_type="meeting_request",
        title="Meeting join request",
        body=f"{current_user.name} requested to join '{meeting.topic or meeting.meeting_code}'",
        actor_id=current_user.id,
        actor_name=current_user.name,
        room_id=meeting.room_id,
    ))
    db.commit()
    return {"status": "pending", "meeting_id": meeting.id, "meeting_code": meeting.meeting_code, "message": "Join request submitted", "topic": meeting.topic}

@router.get("/{meeting_id}/requests")
def get_meeting_requests(meeting_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    ensure_meeting_schema(db)
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the meeting host can view join requests")
    rows = db.query(models.MeetingParticipant).filter(
        models.MeetingParticipant.meeting_id == meeting_id,
        models.MeetingParticipant.status == "pending",
    ).order_by(models.MeetingParticipant.id.asc()).all()
    result = []
    for row in rows:
        u = db.query(models.User).filter(models.User.id == row.user_id).first()
        if u:
            result.append({
                "id": row.id,
                "participant_id": row.id,
                "user_id": u.id,
                "user_name": u.name,
                "user_avatar": u.avatar,
                "email": u.email,
                "created_at": row.joined_at or meeting.created_at,
            })
    return {"requests": result}


@router.post("/{meeting_id}/approve")
def approve_join(meeting_id: int, payload: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    participant_id = int(payload.get('participant_id')) if payload.get('participant_id') is not None else None
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only host can approve join requests")

    participant = db.query(models.MeetingParticipant).filter(models.MeetingParticipant.id == participant_id, models.MeetingParticipant.meeting_id == meeting_id).first()
    if not participant or participant.status != "pending":
        raise HTTPException(status_code=404, detail="Pending participant not found")

    participant.status = "approved"
    participant.joined_at = datetime.utcnow()
    db.add(participant)
    db.add(models.Notification(user_id=participant.user_id, notification_type="meeting_approved", title="Join Approved", body=f"Your join request was approved for meeting {meeting.id}", actor_id=current_user.id, actor_name=current_user.name, room_id=meeting.room_id))
    db.commit()

    user = db.query(models.User).filter(models.User.id == participant.user_id).first()
    return {"status": "approved", "meeting_id": meeting.id, "meeting_code": meeting.meeting_code, "host_id": meeting.host_id}


@router.post("/{meeting_id}/reject")
def reject_join(meeting_id: int, payload: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    participant_id = int(payload.get('participant_id')) if payload.get('participant_id') is not None else None
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only host can reject join requests")

    participant = db.query(models.MeetingParticipant).filter(models.MeetingParticipant.id == participant_id, models.MeetingParticipant.meeting_id == meeting_id).first()
    if not participant or participant.status != "pending":
        raise HTTPException(status_code=404, detail="Pending participant not found")

    participant.status = "rejected"
    db.add(participant)
    db.add(models.Notification(user_id=participant.user_id, notification_type="meeting_rejected", title="Join Rejected", body=f"Your join request was rejected for meeting {meeting.id}", actor_id=current_user.id, actor_name=current_user.name, room_id=meeting.room_id))
    db.commit()
    return {"status": "rejected"}


@router.post("/{meeting_id}/kick")
def kick_participant(meeting_id: int, payload: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    participant_id = int(payload.get('participant_id')) if payload.get('participant_id') is not None else None
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only host can kick participants")

    participant = db.query(models.MeetingParticipant).filter(models.MeetingParticipant.id == participant_id, models.MeetingParticipant.meeting_id == meeting_id).first()
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")

    participant.banned = True
    db.add(participant)
    db.add(models.Notification(user_id=participant.user_id, notification_type="meeting_removed", title="Removed from Meeting", body=f"You were removed from meeting {meeting.id}", actor_id=current_user.id, actor_name=current_user.name, room_id=meeting.room_id))
    db.commit()
    return {"status": "kicked"}


@router.post("/{meeting_id}/end")
def end_meeting(meeting_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only host can end the meeting")

    meeting.status = "ended"
    meeting.ended_at = datetime.utcnow()
    room = db.query(models.Room).filter(models.Room.id == meeting.room_id).first()
    if room:
        room.is_live = False
    # invalidate invites
    db.query(models.MeetingInvitation).filter(models.MeetingInvitation.meeting_id == meeting_id, models.MeetingInvitation.used == False).update({models.MeetingInvitation.used: True})
    db.add(meeting)
    db.commit()
    return {"status": "ended"}


@router.post("/{meeting_id}/transfer_host")
def transfer_host(meeting_id: int, payload: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    new_host_user_id = int(payload.get('new_host_user_id')) if payload.get('new_host_user_id') is not None else None
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only current host can transfer host role")

    member = db.query(models.MeetingParticipant).filter(models.MeetingParticipant.meeting_id == meeting_id, models.MeetingParticipant.user_id == new_host_user_id, models.MeetingParticipant.status == "approved").first()
    if not member:
        raise HTTPException(status_code=404, detail="User is not an approved participant")

    # update roles
    old_host_part = db.query(models.MeetingParticipant).filter(models.MeetingParticipant.meeting_id == meeting_id, models.MeetingParticipant.user_id == current_user.id).first()
    if old_host_part:
        old_host_part.role = "participant"
        db.add(old_host_part)

    member.role = "host"
    meeting.host_id = new_host_user_id
    db.add(member)
    db.add(meeting)
    db.commit()
    return {"status": "host_transferred", "new_host": new_host_user_id}
