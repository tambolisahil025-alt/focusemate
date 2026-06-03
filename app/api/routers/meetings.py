from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
from uuid import uuid4

from app.api.deps import get_db, get_current_user
from app.db import models
from app.services import jitsi_service
from app.core.config import settings

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.post("/")
def create_meeting(payload: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    room_id = int(payload.get('room_id')) if payload.get('room_id') is not None else None
    auto_accept = bool(payload.get('auto_accept', False))
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if room.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only room owner can create meetings")

    # create meeting record
    jitsi_room_name = f"FocuseMate-{room_id}-{str(uuid4())[:8]}"
    meeting = models.Meeting(room_id=room_id, host_id=current_user.id, jitsi_room=jitsi_room_name, auto_accept=bool(auto_accept))
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    # create host participant entry
    host_participant = models.MeetingParticipant(meeting_id=meeting.id, user_id=current_user.id, role="host", status="approved", joined_at=datetime.utcnow())
    db.add(host_participant)
    db.commit()

    manage_token = jitsi_service.create_manage_token(meeting.id, current_user.id)

    return {"meeting_id": meeting.id, "jitsi_room": meeting.jitsi_room, "manage_token": manage_token}


@router.post("/{meeting_id}/invitations")
def generate_invitation(meeting_id: int, payload: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    single_use = bool(payload.get('single_use', True))
    expires_in = payload.get('expires_in')
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only host can generate invitations")

    raw_token = jitsi_service.generate_invite_token(db, meeting_id, current_user.id, single_use=bool(single_use), expires_in=expires_in)
    frontend = settings.FRONTEND_APP_URL or "myapp://"
    invite_url = f"{frontend}/join?invite={raw_token}"
    return {"invite_url": invite_url, "expires_in": expires_in or settings.MEETING_INVITE_TTL_SEC}


@router.post("/join-with-invite")
def join_with_invite(payload: dict = Body(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    invite_token = payload.get('invite_token')
    inv = jitsi_service.validate_and_consume_invite(db, invite_token)
    if not inv:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")
    meeting = db.query(models.Meeting).filter(models.Meeting.id == inv.meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # if auto_accept, create participant and return jitsi token
    if meeting.auto_accept:
        participant = models.MeetingParticipant(meeting_id=meeting.id, user_id=current_user.id, role="participant", status="approved", joined_at=datetime.utcnow())
        db.add(participant)
        db.commit()
        db.refresh(participant)
        jitsi_token = jitsi_service.create_jitsi_jwt(current_user, meeting, moderator=False)
        return {"jitsi_token": jitsi_token, "jitsi_room": meeting.jitsi_room}

    # otherwise create pending participant and notify host via notification
    pending = models.MeetingParticipant(meeting_id=meeting.id, user_id=current_user.id, role="participant", status="pending")
    db.add(pending)
    db.add(models.Notification(user_id=meeting.host_id, notification_type="meeting", title="Join Request", body=f"{current_user.name} requested to join your meeting", actor_id=current_user.id, actor_name=current_user.name, room_id=meeting.room_id))
    db.commit()
    return {"status": "pending", "message": "Join request submitted"}


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
    db.add(models.Notification(user_id=participant.user_id, notification_type="meeting", title="Join Approved", body=f"Your join request was approved for meeting {meeting.id}", actor_id=current_user.id, actor_name=current_user.name, room_id=meeting.room_id))
    db.commit()

    user = db.query(models.User).filter(models.User.id == participant.user_id).first()
    jitsi_token = jitsi_service.create_jitsi_jwt(user, meeting, moderator=False)
    return {"jitsi_token": jitsi_token, "jitsi_room": meeting.jitsi_room}


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
    db.add(models.Notification(user_id=participant.user_id, notification_type="meeting", title="Join Rejected", body=f"Your join request was rejected for meeting {meeting.id}", actor_id=current_user.id, actor_name=current_user.name, room_id=meeting.room_id))
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
    db.add(models.Notification(user_id=participant.user_id, notification_type="meeting", title="Removed from Meeting", body=f"You were removed from meeting {meeting.id}", actor_id=current_user.id, actor_name=current_user.name, room_id=meeting.room_id))
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
