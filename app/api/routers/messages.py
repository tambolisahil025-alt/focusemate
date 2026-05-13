from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.db import models
from app.schemas import schemas
from app.api.deps import get_db, get_current_user

router = APIRouter(prefix="/messages", tags=["messages"])

class MessageCreate(BaseModel):
    room_id: int
    content: str
    message_type: str = "text"

@router.post("/", response_model=schemas.MessageResponse)
def create_message(
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
    
    new_message = models.Message(
        room_id=payload.room_id,
        sender_id=current_user.id,
        content=payload.content,
        message_type=payload.message_type
    )
    db.add(new_message)
    db.commit()
    db.refresh(new_message)
    
    return {
        "id": new_message.id,
        "room_id": new_message.room_id,
        "sender_id": new_message.sender_id,
        "sender_name": current_user.name,
        "sender_avatar": current_user.avatar,
        "content": new_message.content,
        "message_type": new_message.message_type,
        "created_at": new_message.created_at
    }

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
        models.Message.room_id == room_id
    ).order_by(models.Message.created_at.asc()).offset(offset).limit(limit).all()
    
    result = []
    for msg in messages:
        sender = db.query(models.User).filter(models.User.id == msg.sender_id).first() if msg.sender_id else None
        result.append({
            "id": msg.id,
            "room_id": msg.room_id,
            "sender_id": msg.sender_id,
            "sender_name": sender.name if sender else "System",
            "sender_avatar": sender.avatar if sender else None,
            "content": msg.content,
            "message_type": msg.message_type,
            "created_at": msg.created_at
        })
    
    return {"messages": result}
