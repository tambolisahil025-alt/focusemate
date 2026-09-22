from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import or_
from app.db import models
from app.schemas import schemas
from app.api.deps import get_db, get_current_user
from app.api.routers.ws import manager
from app.services.storage_service import delete_storage_url
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["messages"])

class MessageCreate(BaseModel):
    client_message_id: Optional[str] = None
    room_id: int
    content: str
    message_type: str = "text"
    reply_to: Optional[int] = None

def message_payload(message: models.Message, sender: Optional[models.User] = None):
    content = message.content
    reply_to = None
    if message.message_type == "reply":
        try:
            import json
            parsed = json.loads(message.content)
            reply_to = parsed.get("reply_to")
            content = parsed.get("text", message.content)
        except (TypeError, ValueError):
            pass
    return {
        "client_message_id": getattr(message, "_client_message_id", None),
        "id": message.id,
        "room_id": message.room_id,
        "sender_id": message.sender_id,
        "sender_name": sender.name if sender else "System",
        "sender_avatar": sender.avatar if sender else None,
        "content": content,
        "message_type": message.message_type,
        "is_edited": message.is_edited,
        "reply_to": reply_to,
        "created_at": message.created_at,
    }

@router.post("/", response_model=schemas.MessageResponse)
async def create_message(
    payload: MessageCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Create a new message in a room"""
    room = db.query(models.Room).filter(models.Room.id == payload.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    # Check if user is a member of the room
    membership = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == payload.room_id,
        models.RoomMember.user_id == current_user.id
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="You are not a member of this room")
    
    # If this is a reply, encode reply metadata into the content as JSON string
    content_to_store = payload.content
    if payload.reply_to:
        import json
        try:
            content_to_store = json.dumps({"reply_to": int(payload.reply_to), "text": payload.content})
            payload.message_type = "reply"
        except Exception:
            pass

    new_message = models.Message(
        room_id=payload.room_id,
        sender_id=current_user.id,
        content=content_to_store,
        message_type=payload.message_type,
    )
    db.add(new_message)
    db.commit()
    db.refresh(new_message)
    
    response = {
        "client_message_id": payload.client_message_id,
        "id": new_message.id,
        "room_id": new_message.room_id,
        "sender_id": new_message.sender_id,
        "sender_name": current_user.name,
        "sender_avatar": current_user.avatar,
        "content": payload.content,
        "message_type": new_message.message_type,
        "is_edited": new_message.is_edited,
        "reply_to": payload.reply_to,
        "created_at": new_message.created_at
    }
    broadcast_response = {**response, "created_at": response["created_at"].isoformat() if response["created_at"] else None}
    try:
        await manager.broadcast_to_room(payload.room_id, {"type": "chat_message", "data": broadcast_response})
    except Exception:
        logger.exception("Unable to broadcast room message %s", new_message.id)
    return response

@router.put("/{message_id}", response_model=schemas.MessageResponse)
async def update_message(message_id: int, payload: schemas.MessageUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    msg = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own messages")
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Message content cannot be empty")
    msg.content = content
    msg.message_type = "text"
    msg.is_edited = True
    db.commit()
    db.refresh(msg)
    data = message_payload(msg, current_user)
    await manager.broadcast_to_room(msg.room_id, {"type": "message_edited", "action": "message_edited", "message": data})
    return data

@router.delete("/direct/{message_id}")
async def delete_direct_message(message_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    msg = db.query(models.DirectMessage).filter(models.DirectMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")
    sender_id = msg.sender_id
    receiver_id = msg.receiver_id
    await delete_storage_url(msg.content)
    db.delete(msg)
    db.commit()
    await manager.broadcast_direct([sender_id, receiver_id], {
        "type": "direct_message_deleted",
        "message_id": message_id,
    })
    return {"detail": "Message deleted"}

@router.delete("/{message_id}")
async def delete_message(message_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    msg = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")
    room_id = msg.room_id
    await delete_storage_url(msg.content)
    db.delete(msg)
    db.commit()
    await manager.broadcast_to_room(room_id, {"type": "message_deleted", "action": "message_deleted", "message_id": message_id})
    return {"detail": "Message deleted"}

@router.post("/direct", response_model=schemas.DirectMessageResponse)
async def create_direct_message(
    payload: schemas.DirectMessageCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if payload.receiver_id == current_user.id:
        raise HTTPException(status_code=422, detail="You cannot send a direct message to yourself")
    receiver = db.query(models.User).filter(models.User.id == payload.receiver_id).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Recipient not found")

    content_to_store = payload.content
    message_type = payload.message_type
    if payload.reply_to:
        import json
        content_to_store = json.dumps({"reply_to": int(payload.reply_to), "text": payload.content})
        message_type = "reply"

    new_message = models.DirectMessage(
        sender_id=current_user.id,
        receiver_id=payload.receiver_id,
        content=content_to_store,
        message_type=message_type,
    )
    db.add(new_message)
    db.commit()
    db.refresh(new_message)

    response = {
        "client_message_id": payload.client_message_id,
        "id": new_message.id,
        "sender_id": new_message.sender_id,
        "receiver_id": new_message.receiver_id,
        "content": payload.content,
        "message_type": new_message.message_type,
        "created_at": new_message.created_at,
        "sender_name": current_user.name,
        "sender_avatar": current_user.avatar,
        "reply_to": payload.reply_to,
    }
    db.add(models.Notification(
        user_id=payload.receiver_id,
        notification_type="direct_message",
        title=f"New message from {current_user.name}",
        body=payload.content[:140],
        actor_id=current_user.id,
        actor_name=current_user.name,
    ))
    db.commit()
    await manager.broadcast_direct(
        [current_user.id, payload.receiver_id],
        {
            "type": "direct_message",
            "data": {**response, "created_at": response["created_at"].isoformat() if response["created_at"] else None,
                      },
        },
    )
    return response

@router.get("/direct/{recipient_id}")
def get_direct_messages(
    recipient_id: int,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    recipient = db.query(models.User).filter(models.User.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    messages = db.query(models.DirectMessage, models.User).join(
        models.User, models.DirectMessage.sender_id == models.User.id
    ).filter(
        or_(
            (models.DirectMessage.sender_id == current_user.id) & (models.DirectMessage.receiver_id == recipient_id),
            (models.DirectMessage.sender_id == recipient_id) & (models.DirectMessage.receiver_id == current_user.id),
        ),
    ).order_by(models.DirectMessage.created_at.desc()).offset(offset).limit(limit).all()

    result = []
    for message, sender in reversed(messages):
        content = message.content
        reply_to = None
        if message.message_type == "reply":
            try:
                import json
                parsed = json.loads(message.content)
                reply_to = parsed.get("reply_to") if isinstance(parsed, dict) else None
                content = parsed.get("text", message.content) if isinstance(parsed, dict) else message.content
            except (TypeError, ValueError):
                pass
        result.append({
            "id": message.id,
            "sender_id": message.sender_id,
            "receiver_id": message.receiver_id,
            "content": content,
            "message_type": message.message_type,
                "created_at": message.created_at,
            "sender_name": sender.name if sender else None,
            "sender_avatar": sender.avatar if sender else None,
            "reply_to": reply_to,
        })
    return {"messages": result, "limit": limit, "offset": offset}

@router.get("/room/{room_id}")
def get_room_messages(
    room_id: int,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Fetch messages from a room"""
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    # Check if user is a member of the room
    membership = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == room_id,
        models.RoomMember.user_id == current_user.id
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="You are not a member of this room")
    
    messages = db.query(models.Message).filter(
        models.Message.room_id == room_id,
    ).order_by(models.Message.created_at.desc()).offset(offset).limit(limit).all()
    messages = list(reversed(messages))
    
    result = []
    for msg in messages:
        sender = db.query(models.User).filter(models.User.id == msg.sender_id).first() if msg.sender_id else None
        content = msg.content
        reply_to = None
        # If stored as a reply JSON blob, attempt to decode
        if msg.message_type == 'reply':
            try:
                import json
                parsed = json.loads(msg.content)
                reply_to = parsed.get('reply_to')
                content = parsed.get('text') if isinstance(parsed, dict) else msg.content
            except Exception:
                content = msg.content

        result.append({
            "id": msg.id,
            "room_id": msg.room_id,
            "sender_id": msg.sender_id,
            "sender_name": sender.name if sender else "System",
            "sender_avatar": sender.avatar if sender else None,
            "content": content,
            "message_type": msg.message_type,
            "is_edited": msg.is_edited,
            "reply_to": reply_to,
            "created_at": msg.created_at
        })
    
    return {"messages": result}
