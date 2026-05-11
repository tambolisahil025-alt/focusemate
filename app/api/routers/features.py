from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import Dict, Any
from app.db import models
from app.schemas import schemas  # <-- ADDED THIS IMPORT
from app.api.deps import get_db, get_current_user
from pydantic import BaseModel

router = APIRouter(tags=["features"])

# --- ANALYTICS ---
@router.get("/analytics/me")
def get_analytics(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    rooms_joined = db.query(models.RoomMember).filter(models.RoomMember.user_id == current_user.id).count()
    messages_sent = db.query(models.Message).filter(models.Message.sender_id == current_user.id).count()
    resources_added = db.query(models.Resource).filter(models.Resource.added_by_id == current_user.id).count()
    friends_count = db.query(models.Friendship).filter(
        models.Friendship.status == "accepted",
        or_(models.Friendship.sender_id == current_user.id, models.Friendship.receiver_id == current_user.id)
    ).count()
    
    return {
        "rooms_joined": rooms_joined,
        "messages_sent": messages_sent,
        "resources_added": resources_added,
        "friends_count": friends_count
    }

# --- SETTINGS ---
@router.get("/settings/")
def get_settings(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    settings = db.query(models.UserSettings).filter(models.UserSettings.user_id == current_user.id).first()
    if not settings:
        settings = models.UserSettings(user_id=current_user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings

@router.patch("/settings/")
def update_settings(payload: Dict[str, Any], db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    settings = db.query(models.UserSettings).filter(models.UserSettings.user_id == current_user.id).first()
    if not settings:
        settings = models.UserSettings(user_id=current_user.id)
        db.add(settings)
    for key, value in payload.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    db.commit()
    return {"status": "success"}

# --- FRIENDS ---
@router.get("/friends/")
def get_friends(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    friendships = db.query(models.Friendship).filter(
        models.Friendship.status == "accepted",
        or_(models.Friendship.sender_id == current_user.id, models.Friendship.receiver_id == current_user.id)
    ).all()
    
    friends_list = []
    for f in friendships:
        friend_id = f.receiver_id if f.sender_id == current_user.id else f.sender_id
        friend_user = db.query(models.User).filter(models.User.id == friend_id).first()
        if friend_user:
            friends_list.append({"id": friend_user.id, "name": friend_user.name, "email": friend_user.email, "avatar": friend_user.avatar, "level": friend_user.level, "xp": friend_user.xp})
    return {"friends": friends_list}

@router.get("/friends/requests/received")
def get_received_requests(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    requests = db.query(models.Friendship).filter(models.Friendship.receiver_id == current_user.id, models.Friendship.status == "pending").all()
    res = []
    for r in requests:
        sender = db.query(models.User).filter(models.User.id == r.sender_id).first()
        res.append({"id": r.id, "sender_id": sender.id, "sender_name": sender.name, "sender_avatar": sender.avatar, "status": "pending", "created_at": r.created_at})
    return res

@router.get("/friends/requests/sent")
def get_sent_requests(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    requests = db.query(models.Friendship).filter(models.Friendship.sender_id == current_user.id, models.Friendship.status == "pending").all()
    res = []
    for r in requests:
        receiver = db.query(models.User).filter(models.User.id == r.receiver_id).first()
        res.append({"id": r.id, "receiver_id": receiver.id, "receiver_name": receiver.name, "receiver_avatar": receiver.avatar, "status": "pending", "created_at": r.created_at})
    return res

class FriendAction(BaseModel):
    action: str # accept or reject

@router.post("/friends/requests/{request_id}")
def handle_friend_request(request_id: int, payload: FriendAction, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    req = db.query(models.Friendship).filter(models.Friendship.id == request_id, models.Friendship.receiver_id == current_user.id).first()
    if req:
        if payload.action == "accept":
            req.status = "accepted"
        else:
            db.delete(req)
        db.commit()
    return {"status": "success"}

# --- NOTIFICATIONS ---
@router.get("/notifications/")
def get_notifications(unread_only: bool = False, limit: int = 50, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    query = db.query(models.Notification).filter(models.Notification.user_id == current_user.id)
    if unread_only:
        query = query.filter(models.Notification.is_read == False)
    
    notifs = query.order_by(models.Notification.created_at.desc()).limit(limit).all()
    
    if unread_only:
        return {"unread_count": len(notifs)}
    return {"notifications": notifs}

@router.post("/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    db.query(models.Notification).filter(models.Notification.user_id == current_user.id).update({"is_read": True})
    db.commit()
    return {"status": "success"}

# --- INVITATIONS ---
class InvitationCreate(BaseModel):
    room_id: int
    invitee_id: int

class InvitationAction(BaseModel):
    action: str

@router.get("/invitations/")
def get_invitations(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    invites = db.query(models.Invitation).filter(models.Invitation.invitee_id == current_user.id, models.Invitation.status == "pending").all()
    res = []
    for i in invites:
        room = db.query(models.Room).filter(models.Room.id == i.room_id).first()
        inviter = db.query(models.User).filter(models.User.id == i.inviter_id).first()
        res.append({
            "id": i.id, "room_id": i.room_id, "room_title": room.title if room else "Unknown Room",
            "inviter_id": i.inviter_id, "inviter_name": inviter.name if inviter else "Someone", "status": i.status, "created_at": i.created_at
        })
    return {"invitations": res}

@router.post("/invitations/")
def create_invitation(payload: InvitationCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    room = db.query(models.Room).filter(models.Room.id == payload.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    inviter_membership = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == payload.room_id,
        models.RoomMember.user_id == current_user.id
    ).first()
    if not inviter_membership:
        raise HTTPException(status_code=403, detail="Join the room before inviting others")
    if payload.invitee_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot invite yourself")

    invitee = db.query(models.User).filter(models.User.id == payload.invitee_id).first()
    if not invitee:
        raise HTTPException(status_code=404, detail="Invitee not found")

    existing_member = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == payload.room_id,
        models.RoomMember.user_id == payload.invitee_id
    ).first()
    if existing_member:
        raise HTTPException(status_code=400, detail="User is already a room member")

    existing_invite = db.query(models.Invitation).filter(
        models.Invitation.room_id == payload.room_id,
        models.Invitation.invitee_id == payload.invitee_id,
        models.Invitation.status == "pending"
    ).first()
    if existing_invite:
        raise HTTPException(status_code=400, detail="Invitation already sent")

    invitation = models.Invitation(
        room_id=payload.room_id,
        inviter_id=current_user.id,
        invitee_id=payload.invitee_id,
        status="pending"
    )
    db.add(invitation)
    db.flush()

    notification = models.Notification(
        user_id=payload.invitee_id,
        notification_type="room_invite",
        title="Room Invitation",
        body=f"{current_user.name} invited you to join '{room.title}'.",
        actor_id=current_user.id,
        actor_name=current_user.name,
        room_id=room.id
    )
    db.add(notification)
    db.commit()
    db.refresh(invitation)

    return {"detail": "Invitation sent successfully", "invitation_id": invitation.id}

@router.post("/invitations/{invitation_id}")
def handle_invitation(invitation_id: int, payload: InvitationAction, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    invitation = db.query(models.Invitation).filter(
        models.Invitation.id == invitation_id,
        models.Invitation.invitee_id == current_user.id
    ).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.status != "pending":
        return {"status": invitation.status, "room_id": invitation.room_id}

    action = payload.action.lower()
    if action not in ["accept", "reject", "decline"]:
        raise HTTPException(status_code=400, detail="Action must be accept or reject")

    if action == "accept":
        room = db.query(models.Room).filter(models.Room.id == invitation.room_id).first()
        if not room:
            invitation.status = "rejected"
            db.commit()
            raise HTTPException(status_code=404, detail="Room no longer exists")

        existing_member = db.query(models.RoomMember).filter(
            models.RoomMember.room_id == invitation.room_id,
            models.RoomMember.user_id == current_user.id
        ).first()
        if not existing_member:
            member_count = db.query(models.RoomMember).filter(models.RoomMember.room_id == invitation.room_id).count()
            if member_count >= room.max_members:
                raise HTTPException(status_code=400, detail="Room is full")
            db.add(models.RoomMember(room_id=invitation.room_id, user_id=current_user.id, role="member"))
        invitation.status = "accepted"
    else:
        invitation.status = "rejected"

    db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.notification_type == "room_invite",
        models.Notification.room_id == invitation.room_id,
        models.Notification.actor_id == invitation.inviter_id
    ).update({"is_read": True}, synchronize_session=False)

    db.commit()
    return {"status": invitation.status, "room_id": invitation.room_id}

# --- SUPPORT TICKETS ---
@router.get("/support/tickets")
def get_tickets(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    tickets = db.query(models.Ticket).filter(models.Ticket.user_id == current_user.id).order_by(models.Ticket.created_at.desc()).all()
    return {"tickets": tickets}

class TicketCreate(BaseModel):
    subject: str
    description: str
    category: str

@router.post("/support/tickets")
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    new_ticket = models.Ticket(user_id=current_user.id, subject=payload.subject, description=payload.description, category=payload.category)
    db.add(new_ticket)
    db.commit()
    return {"status": "success"}

class FriendRequestCreate(BaseModel):
    receiver_id: int

@router.post("/friends/request")
def send_friend_request(
    payload: FriendRequestCreate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    if payload.receiver_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot send a friend request to yourself")
        
    receiver = db.query(models.User).filter(models.User.id == payload.receiver_id).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Check if they are already friends or if a request is already pending
    existing = db.query(models.Friendship).filter(
        or_(
            and_(models.Friendship.sender_id == current_user.id, models.Friendship.receiver_id == payload.receiver_id),
            and_(models.Friendship.sender_id == payload.receiver_id, models.Friendship.receiver_id == current_user.id)
        )
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Friend request or friendship already exists")
        
    # Create the friend request
    new_req = models.Friendship(
        sender_id=current_user.id, 
        receiver_id=payload.receiver_id, 
        status="pending"
    )
    db.add(new_req)
    
    # Send a notification to the receiver!
    notif = models.Notification(
        user_id=payload.receiver_id,
        notification_type="friend_request",
        title="New Friend Request",
        body=f"{current_user.name} sent you a friend request.",
        actor_id=current_user.id,
        actor_name=current_user.name
    )
    db.add(notif)
    
    db.commit()
    return {"detail": "Friend request sent successfully!"}

@router.delete("/friends/{friend_id}")
def remove_friend(friend_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    friendship = db.query(models.Friendship).filter(
        models.Friendship.status == "accepted",
        or_(
            and_(models.Friendship.sender_id == current_user.id, models.Friendship.receiver_id == friend_id),
            and_(models.Friendship.sender_id == friend_id, models.Friendship.receiver_id == current_user.id)
        )
    ).first()
    if not friendship:
        raise HTTPException(status_code=404, detail="Friendship not found")

    db.delete(friendship)
    db.commit()
    return {"detail": "Friend removed successfully"}

# 1. Define the input model for the read request
class NotificationRead(BaseModel):
    notification_ids: list[int]

# 2. Add the route to handle marking specific notifications as read
@router.post("/notifications/read")
def mark_notifications_as_read(
    payload: NotificationRead, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    # Only update notifications that belong to the current user
    db.query(models.Notification).filter(
        models.Notification.id.in_(payload.notification_ids),
        models.Notification.user_id == current_user.id
    ).update({"is_read": True}, synchronize_session=False)
    
    db.commit()
    return {"status": "success"}

# --- NEW: DIRECT MESSAGES ---

@router.post("/messages/direct", response_model=schemas.DirectMessageResponse)
def send_direct_message(
    message: schemas.DirectMessageCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    receiver = db.query(models.User).filter(models.User.id == message.receiver_id).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Recipient not found")

    new_msg = models.DirectMessage(
        sender_id=current_user.id,
        receiver_id=message.receiver_id,
        content=message.content,
        message_type=message.message_type
    )
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)

    notif = models.Notification(
        user_id=message.receiver_id,
        notification_type="direct_message",
        title=f"New message from {current_user.name}",
        body=message.content[:140],
        actor_id=current_user.id,
        actor_name=current_user.name
    )
    db.add(notif)
    db.commit()

    return {
        **new_msg.__dict__,
        "sender_name": current_user.name,
        "sender_avatar": current_user.avatar
    }

@router.get("/messages/direct/{recipient_id}")
def get_direct_messages(
    recipient_id: int,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    messages = db.query(models.DirectMessage).filter(
        or_(
            and_(models.DirectMessage.sender_id == current_user.id, models.DirectMessage.receiver_id == recipient_id),
            and_(models.DirectMessage.sender_id == recipient_id, models.DirectMessage.receiver_id == current_user.id)
        )
    ).order_by(models.DirectMessage.created_at.desc()).offset(offset).limit(limit).all()

    response = []
    for msg in messages:
        if msg.sender_id == current_user.id:
            sender_name = current_user.name
            sender_avatar = current_user.avatar
        else:
            sender = db.query(models.User).filter(models.User.id == msg.sender_id).first()
            sender_name = sender.name if sender else "Unknown User"
            sender_avatar = sender.avatar if sender else None

        response.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "receiver_id": msg.receiver_id,
            "content": msg.content,
            "message_type": msg.message_type,
            "created_at": msg.created_at,
            "sender_name": sender_name,
            "sender_avatar": sender_avatar
        })
        
    return {"messages": response}
