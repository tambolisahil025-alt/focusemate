import json
import os
import shutil
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, UploadFile, File, Form, Request
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import SessionLocal
from app.core.config import settings
from app.db import models
from app.api.deps import get_db, get_current_user

router = APIRouter(tags=["websockets"])

UPLOAD_DIR = "uploads/messages"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------------------------------------------------
# Connection Manager
# ---------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        # Maps room_id -> list of active WebSockets
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self.direct_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_id: int):
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
        self.active_connections[room_id].append(websocket)

    def disconnect(self, websocket: WebSocket, room_id: int):
        if room_id in self.active_connections and websocket in self.active_connections[room_id]:
            self.active_connections[room_id].remove(websocket)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

    async def broadcast_to_room(self, room_id: int, message: dict):
        if room_id in self.active_connections:
            stale = []
            for connection in list(self.active_connections[room_id]):
                try:
                    await connection.send_json(message)
                except Exception:
                    stale.append(connection)
            for connection in stale:
                self.disconnect(connection, room_id)

    async def connect_direct(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.direct_connections.setdefault(user_id, []).append(websocket)

    def disconnect_direct(self, websocket: WebSocket, user_id: int):
        if user_id in self.direct_connections and websocket in self.direct_connections[user_id]:
            self.direct_connections[user_id].remove(websocket)
            if not self.direct_connections[user_id]:
                del self.direct_connections[user_id]

    async def broadcast_direct(self, user_ids: List[int], message: dict):
        for user_id in user_ids:
            stale = []
            for connection in list(self.direct_connections.get(user_id, [])):
                try:
                    await connection.send_json(message)
                except Exception:
                    stale.append(connection)
            for connection in stale:
                self.disconnect_direct(connection, user_id)

    async def broadcast_all_direct(self, message: dict):
        stale = []
        for user_id, connections in list(self.direct_connections.items()):
            for connection in list(connections):
                try:
                    await connection.send_json(message)
                except Exception:
                    stale.append((connection, user_id))
        for connection, user_id in stale:
            self.disconnect_direct(connection, user_id)

manager = ConnectionManager()

# ---------------------------------------------------------
# Authentication Helper
# ---------------------------------------------------------
def get_user_from_token(token: str):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            return None
        db = SessionLocal()
        user = db.query(models.User).filter(models.User.id == int(user_id)).first()
        db.close()
        return user
    except JWTError:
        return None

# ---------------------------------------------------------
# WebSocket Routes
# ---------------------------------------------------------
@router.websocket("/ws/rooms/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: int, token: str):
    user = get_user_from_token(token)
    if not user:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, room_id)
    
    # Notify room user joined
    await manager.broadcast_to_room(room_id, {
        "type": "user_joined",
        "user_id": user.id,
        "user_name": user.name
    })

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data.get("type") == "chat_message":
                db = SessionLocal()
                message_type = message_data.get("message_type") or "text"
                new_msg = models.Message(
                    room_id=room_id,
                    sender_id=user.id,
                    content=message_data.get("content"),
                    message_type=message_type
                )
                db.add(new_msg)
                db.commit()
                db.refresh(new_msg)
                
                broadcast_data = {
                    "type": "chat_message",
                    "data": {
                        "id": new_msg.id,
                        "room_id": room_id,
                        "sender_id": user.id,
                        "sender_name": user.name,
                        "sender_avatar": user.avatar,
                        "content": new_msg.content,
                        "message_type": message_type,
                        "created_at": new_msg.created_at.isoformat() if new_msg.created_at else None
                    }
                }
                db.close()
                await manager.broadcast_to_room(room_id, broadcast_data)
                
            elif message_data.get("type") == "typing":
                await manager.broadcast_to_room(room_id, {
                    "type": "typing",
                    "user_id": user.id,
                    "user_name": user.name
                })
                
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
        await manager.broadcast_to_room(room_id, {
            "type": "user_left",
            "user_id": user.id,
            "user_name": user.name
        })

@router.websocket("/ws/direct")
async def direct_message_websocket(websocket: WebSocket, token: str):
    user = get_user_from_token(token)
    if not user:
        await websocket.close(code=1008)
        return

    await manager.connect_direct(websocket, user.id)
    await manager.broadcast_all_direct({
        "type": "presence",
        "user_id": user.id,
        "status": "online"
    })

    try:
        while True:
            payload = json.loads(await websocket.receive_text())
            if payload.get("type") != "direct_message":
                continue

            receiver_id = payload.get("receiver_id")
            content = (payload.get("content") or "").strip()
            if not receiver_id or not content:
                continue

            db = SessionLocal()
            try:
                receiver = db.query(models.User).filter(models.User.id == int(receiver_id)).first()
                if not receiver:
                    continue

                new_msg = models.DirectMessage(
                    sender_id=user.id,
                    receiver_id=receiver.id,
                    content=content,
                    message_type=payload.get("message_type") or "text"
                )
                db.add(new_msg)
                db.commit()
                db.refresh(new_msg)

                notif = models.Notification(
                    user_id=receiver.id,
                    notification_type="direct_message",
                    title=f"New message from {user.name}",
                    body=content[:140],
                    actor_id=user.id,
                    actor_name=user.name
                )
                db.add(notif)
                db.commit()

                await manager.broadcast_direct([user.id, receiver.id], {
                    "type": "direct_message",
                    "data": {
                        "id": new_msg.id,
                        "sender_id": user.id,
                        "receiver_id": receiver.id,
                        "content": new_msg.content,
                        "message_type": new_msg.message_type,
                        "created_at": new_msg.created_at.isoformat() if new_msg.created_at else None,
                        "sender_name": user.name,
                        "sender_avatar": user.avatar
                    }
                })
            finally:
                db.close()
    except WebSocketDisconnect:
        manager.disconnect_direct(websocket, user.id)
        await manager.broadcast_all_direct({
            "type": "presence",
            "user_id": user.id,
            "status": "offline"
        })

# ---------------------------------------------------------
# REST API Routes
# ---------------------------------------------------------
class MessageCreate(BaseModel):
    room_id: int
    content: str
    message_type: str = "text"

# NOTE: operation_id added here to fix Uvicorn duplicate warnings
@router.get("/messages/room/{room_id}", operation_id="fetch_room_messages")
def get_room_messages(
    room_id: int, 
    limit: int = 100, 
    offset: int = 0, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    messages = db.query(models.Message).filter(
        models.Message.room_id == room_id
    ).order_by(models.Message.created_at.desc()).offset(offset).limit(limit).all()
    
    result = []
    for msg in messages:
        sender = db.query(models.User).filter(models.User.id == msg.sender_id).first() if msg.sender_id else None
        result.append({
            "id": msg.id,
            "room_id": msg.room_id,
            "sender_id": msg.sender_id,
            "sender_name": sender.name if sender else "System",
            "sender_avatar": sender.avatar if sender else None,
            "sender_level": sender.level if sender else None,
            "sender_xp": sender.xp if sender else None,
            "content": msg.content,
            "message_type": msg.message_type,
            "created_at": msg.created_at.isoformat() if msg.created_at else None
        })
    return {"messages": result}

# NOTE: operation_id added here to fix Uvicorn duplicate warnings
@router.post("/messages/", operation_id="post_new_message")
def create_message(
    payload: MessageCreate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    new_msg = models.Message(
        room_id=payload.room_id,
        sender_id=current_user.id,
        content=payload.content,
        message_type=payload.message_type
    )
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)
    
    return {
        "id": new_msg.id,
        "room_id": new_msg.room_id,
        "sender_id": current_user.id,
        "sender_name": current_user.name,
        "sender_avatar": current_user.avatar,
        "content": new_msg.content,
        "message_type": new_msg.message_type,
        "created_at": new_msg.created_at.isoformat() if new_msg.created_at else None
    }

@router.post("/messages/attachments/")
async def upload_message_attachment(
    file: UploadFile = File(...),
    room_id: Optional[int] = Form(None),
    receiver_id: Optional[int] = Form(None),
    message_type: str = Form("image"),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    if not room_id and not receiver_id:
        raise HTTPException(status_code=400, detail="room_id or receiver_id is required")

    file_ext = file.filename.split('.')[-1]
    file_name = f"{uuid.uuid4()}.{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, file_name)
    with open(file_path, 'wb') as buffer:
        shutil.copyfileobj(file.file, buffer)

    base_url = str(request.base_url).rstrip('/') if request else ''
    file_url = f"{base_url}/static/messages/{file_name}"
    return {"file_url": file_url, "message_type": message_type}