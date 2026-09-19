from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4
import time

from app.api.deps import get_db, get_current_user
from app.db import models
from app.core.config import settings

try:
    from agora_token_builder import RtcTokenBuilder, Role_Publisher
except ImportError:  # pragma: no cover
    RtcTokenBuilder = None
    Role_Publisher = None

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _room(db: Session, room_id: int):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


def _room_membership(db: Session, room_id: int, user_id: int):
    return (
        db.query(models.RoomMember)
        .filter(
            models.RoomMember.room_id == room_id,
            models.RoomMember.user_id == user_id,
        )
        .first()
    )


def _is_room_manager(room, membership, user_id: int) -> bool:
    return room.owner_id == user_id or (membership is not None and membership.role in {"owner", "admin"})


def _meeting_response(meeting):
    return {
        "meeting_id": meeting.id,
        "meeting_code": meeting.meeting_code,
        "status": meeting.status,
        "host_id": meeting.host_id,
        "room_id": meeting.room_id,
        "channel_name": f"focusemate_{meeting.id}_{meeting.meeting_code}",
    }


def _ensure_agora_configured():
    if not settings.AGORA_APP_ID or not settings.AGORA_APP_CERTIFICATE:
        raise HTTPException(
            status_code=503,
            detail="Agora is not configured on the server. Set AGORA_APP_ID and AGORA_APP_CERTIFICATE in Render environment variables.",
        )
    if RtcTokenBuilder is None or Role_Publisher is None:
        raise HTTPException(
            status_code=500,
            detail="Agora token package is not installed on the backend.",
        )


@router.post("/")
def create_meeting(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        room_id = int(payload.get("room_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="room_id is required")

    room = _room(db, room_id)
    membership = _room_membership(db, room_id, current_user.id)

    if not _is_room_manager(room, membership, current_user.id):
        raise HTTPException(status_code=403, detail="Only the room owner or admin can create meetings")

    # Reuse an active meeting rather than creating a duplicate every time.
    existing = (
        db.query(models.Meeting)
        .filter(
            models.Meeting.room_id == room_id,
            models.Meeting.status.in_(["lobby", "live"]),
        )
        .order_by(models.Meeting.id.desc())
        .first()
    )

    if existing:
        participant = (
            db.query(models.MeetingParticipant)
            .filter(
                models.MeetingParticipant.meeting_id == existing.id,
                models.MeetingParticipant.user_id == current_user.id,
            )
            .first()
        )
        if not participant:
            participant = models.MeetingParticipant(
                meeting_id=existing.id,
                user_id=current_user.id,
                role="host" if existing.host_id == current_user.id else "participant",
                status="approved",
                joined_at=datetime.utcnow(),
            )
            db.add(participant)
        else:
            participant.status = "approved"
            participant.joined_at = participant.joined_at or datetime.utcnow()

        room.is_live = True
        db.add(room)
        db.commit()
        db.refresh(existing)
        return _meeting_response(existing)

    meeting_code = f"{uuid4().hex[:8].upper()}-{uuid4().hex[:4].upper()}"

    meeting = models.Meeting(
        room_id=room_id,
        host_id=current_user.id,
        meeting_code=meeting_code,
        auto_accept=True,
        status="live",
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    host_participant = models.MeetingParticipant(
        meeting_id=meeting.id,
        user_id=current_user.id,
        role="host",
        status="approved",
        joined_at=datetime.utcnow(),
    )
    db.add(host_participant)

    room.is_live = True
    db.add(room)
    db.commit()
    db.refresh(meeting)

    return _meeting_response(meeting)


@router.get("/room/{room_id}/active")
def get_active_room_meeting(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    room = _room(db, room_id)
    membership = _room_membership(db, room_id, current_user.id)

    if room.owner_id != current_user.id and membership is None:
        raise HTTPException(status_code=403, detail="You are not a member of this room")

    meeting = (
        db.query(models.Meeting)
        .filter(
            models.Meeting.room_id == room_id,
            models.Meeting.status.in_(["lobby", "live"]),
        )
        .order_by(models.Meeting.id.desc())
        .first()
    )

    return _meeting_response(meeting) if meeting else {"meeting": None}


@router.post("/{meeting_id}/join")
def join_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if meeting.status == "ended":
        raise HTTPException(status_code=410, detail="This meeting has ended")

    room = _room(db, meeting.room_id)
    membership = _room_membership(db, room.id, current_user.id)

    if room.owner_id != current_user.id and membership is None:
        raise HTTPException(status_code=403, detail="You must be a member of the room to join this meeting")

    participant = (
        db.query(models.MeetingParticipant)
        .filter(
            models.MeetingParticipant.meeting_id == meeting_id,
            models.MeetingParticipant.user_id == current_user.id,
        )
        .first()
    )

    if participant and participant.banned:
        raise HTTPException(status_code=403, detail="You have been removed from this meeting")

    if not participant:
        participant = models.MeetingParticipant(
            meeting_id=meeting_id,
            user_id=current_user.id,
            role="host" if meeting.host_id == current_user.id else "participant",
            status="approved",
            joined_at=datetime.utcnow(),
        )
        db.add(participant)
    else:
        participant.status = "approved"
        participant.left_at = None
        participant.joined_at = participant.joined_at or datetime.utcnow()

    meeting.status = "live"
    room.is_live = True
    db.add(meeting)
    db.add(room)
    db.commit()

    return _meeting_response(meeting)


@router.get("/{meeting_id}/agora-token")
def get_agora_token(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_agora_configured()

    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if meeting.status == "ended":
        raise HTTPException(status_code=410, detail="This meeting has ended")

    room = _room(db, meeting.room_id)
    membership = _room_membership(db, room.id, current_user.id)

    participant = (
        db.query(models.MeetingParticipant)
        .filter(
            models.MeetingParticipant.meeting_id == meeting_id,
            models.MeetingParticipant.user_id == current_user.id,
        )
        .first()
    )

    if room.owner_id != current_user.id and membership is None:
        raise HTTPException(status_code=403, detail="You are not a member of this room")

    if not participant or participant.status != "approved" or participant.banned:
        raise HTTPException(status_code=403, detail="Join the meeting before requesting an Agora token")

    channel_name = f"focusemate_{meeting.id}_{meeting.meeting_code}"
    uid = int(current_user.id)
    expires_at = int(time.time()) + int(settings.AGORA_TOKEN_TTL_SEC)

    token = RtcTokenBuilder.buildTokenWithUid(
        settings.AGORA_APP_ID,
        settings.AGORA_APP_CERTIFICATE,
        channel_name,
        uid,
        Role_Publisher,
        expires_at,
    )

    return {
        "token": token,
        "app_id": settings.AGORA_APP_ID,
        "channel_name": channel_name,
        "uid": uid,
        "expires_at": expires_at,
        "meeting_id": meeting.id,
        "meeting_code": meeting.meeting_code,
        "host_id": meeting.host_id,
    }


@router.post("/{meeting_id}/invitations")
def generate_invitation(
    meeting_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    single_use = bool(payload.get("single_use", True))
    expires_in = payload.get("expires_in")

    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only host can generate invitations")

    raw_token = uuid4().hex
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in or settings.MEETING_INVITE_TTL_SEC)

    db.add(
        models.MeetingInvitation(
            meeting_id=meeting.id,
            inviter_id=current_user.id,
            token_hash=raw_token,
            expires_at=expires_at,
            single_use=single_use,
        )
    )
    db.commit()

    invite_url = f"myapp://meeting/{meeting.meeting_code}?invite={raw_token}"
    return {
        "invite_url": invite_url,
        "expires_in": expires_in or settings.MEETING_INVITE_TTL_SEC,
    }


@router.post("/join-with-invite")
def join_with_invite(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    invite_token = payload.get("invite_token")

    inv = (
        db.query(models.MeetingInvitation)
        .filter(
            models.MeetingInvitation.token_hash == invite_token,
            models.MeetingInvitation.used == False,
        )
        .first()
    )

    if not inv:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    if inv.expires_at and inv.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    meeting = db.query(models.Meeting).filter(models.Meeting.id == inv.meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if meeting.status == "ended":
        raise HTTPException(status_code=410, detail="This meeting has ended")

    if inv.single_use:
        inv.used = True

    participant = (
        db.query(models.MeetingParticipant)
        .filter(
            models.MeetingParticipant.meeting_id == meeting.id,
            models.MeetingParticipant.user_id == current_user.id,
        )
        .first()
    )

    status = "approved" if meeting.auto_accept else "pending"

    if meeting.auto_accept:
        if participant is None:
            participant = models.MeetingParticipant(
                meeting_id=meeting.id,
                user_id=current_user.id,
                role="participant",
                status="approved",
                joined_at=datetime.utcnow(),
            )
            db.add(participant)
        else:
            participant.status = "approved"
            participant.joined_at = participant.joined_at or datetime.utcnow()
    else:
        if participant is None:
            participant = models.MeetingParticipant(
                meeting_id=meeting.id,
                user_id=current_user.id,
                role="participant",
                status="pending",
            )
            db.add(participant)

        db.add(
            models.Notification(
                user_id=meeting.host_id,
                notification_type="meeting",
                title="Join Request",
                body=f"{current_user.name} requested to join your meeting",
                actor_id=current_user.id,
                actor_name=current_user.name,
                room_id=meeting.room_id,
            )
        )

    db.commit()

    if status == "approved":
        return {
            "status": "approved",
            "meeting_id": meeting.id,
            "meeting_code": meeting.meeting_code,
            "host_id": meeting.host_id,
        }

    return {"status": "pending", "message": "Join request submitted"}


@router.post("/{meeting_id}/approve")
def approve_join(
    meeting_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    participant_id = int(payload.get("participant_id")) if payload.get("participant_id") is not None else None
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only host can approve join requests")

    participant = (
        db.query(models.MeetingParticipant)
        .filter(
            models.MeetingParticipant.id == participant_id,
            models.MeetingParticipant.meeting_id == meeting_id,
        )
        .first()
    )
    if not participant or participant.status != "pending":
        raise HTTPException(status_code=404, detail="Pending participant not found")

    participant.status = "approved"
    participant.joined_at = datetime.utcnow()

    db.add(
        models.Notification(
            user_id=participant.user_id,
            notification_type="meeting",
            title="Join Approved",
            body=f"Your join request was approved for meeting {meeting.id}",
            actor_id=current_user.id,
            actor_name=current_user.name,
            room_id=meeting.room_id,
        )
    )
    db.commit()

    return {
        "status": "approved",
        "meeting_id": meeting.id,
        "meeting_code": meeting.meeting_code,
        "host_id": meeting.host_id,
    }


@router.post("/{meeting_id}/reject")
def reject_join(
    meeting_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    participant_id = int(payload.get("participant_id")) if payload.get("participant_id") is not None else None
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only host can reject join requests")

    participant = (
        db.query(models.MeetingParticipant)
        .filter(
            models.MeetingParticipant.id == participant_id,
            models.MeetingParticipant.meeting_id == meeting_id,
        )
        .first()
    )
    if not participant or participant.status != "pending":
        raise HTTPException(status_code=404, detail="Pending participant not found")

    participant.status = "rejected"
    db.add(
        models.Notification(
            user_id=participant.user_id,
            notification_type="meeting",
            title="Join Rejected",
            body=f"Your join request was rejected for meeting {meeting.id}",
            actor_id=current_user.id,
            actor_name=current_user.name,
            room_id=meeting.room_id,
        )
    )
    db.commit()
    return {"status": "rejected"}


@router.post("/{meeting_id}/kick")
def kick_participant(
    meeting_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    participant_id = int(payload.get("participant_id")) if payload.get("participant_id") is not None else None
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only host can kick participants")

    participant = (
        db.query(models.MeetingParticipant)
        .filter(
            models.MeetingParticipant.id == participant_id,
            models.MeetingParticipant.meeting_id == meeting_id,
        )
        .first()
    )
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")

    participant.banned = True
    participant.left_at = datetime.utcnow()

    db.add(
        models.Notification(
            user_id=participant.user_id,
            notification_type="meeting",
            title="Removed from Meeting",
            body=f"You were removed from meeting {meeting.id}",
            actor_id=current_user.id,
            actor_name=current_user.name,
            room_id=meeting.room_id,
        )
    )
    db.commit()
    return {"status": "kicked"}


@router.post("/{meeting_id}/end")
def end_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
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
        db.add(room)

    db.query(models.MeetingInvitation).filter(
        models.MeetingInvitation.meeting_id == meeting_id,
        models.MeetingInvitation.used == False,
    ).update({models.MeetingInvitation.used: True})

    db.query(models.MeetingParticipant).filter(
        models.MeetingParticipant.meeting_id == meeting_id,
        models.MeetingParticipant.left_at.is_(None),
    ).update({models.MeetingParticipant.left_at: datetime.utcnow()})

    db.add(meeting)
    db.commit()

    return {"status": "ended"}


@router.post("/{meeting_id}/transfer_host")
def transfer_host(
    meeting_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    new_host_user_id = int(payload.get("new_host_user_id")) if payload.get("new_host_user_id") is not None else None
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only current host can transfer host role")

    member = (
        db.query(models.MeetingParticipant)
        .filter(
            models.MeetingParticipant.meeting_id == meeting_id,
            models.MeetingParticipant.user_id == new_host_user_id,
            models.MeetingParticipant.status == "approved",
            models.MeetingParticipant.banned == False,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="User is not an approved participant")

    old_host_part = (
        db.query(models.MeetingParticipant)
        .filter(
            models.MeetingParticipant.meeting_id == meeting_id,
            models.MeetingParticipant.user_id == current_user.id,
        )
        .first()
    )
    if old_host_part:
        old_host_part.role = "participant"
        db.add(old_host_part)

    member.role = "host"
    meeting.host_id = new_host_user_id
    db.add(member)
    db.add(meeting)
    db.commit()

    return {"status": "host_transferred", "new_host": new_host_user_id}


@router.get("/{meeting_id}")
def get_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    room = _room(db, meeting.room_id)
    membership = _room_membership(db, room.id, current_user.id)

    if room.owner_id != current_user.id and membership is None:
        raise HTTPException(status_code=403, detail="You are not a member of this room")

    return _meeting_response(meeting)
