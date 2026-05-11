from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from app.db import models
from app.schemas import schemas
from app.api.deps import get_db, get_current_user
import uuid
from pydantic import BaseModel
from typing import Optional
router = APIRouter(prefix="/rooms", tags=["rooms"])

@router.post("/", response_model=schemas.RoomResponse)
def create_room(room: schemas.RoomCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    new_room = models.Room(**room.model_dump(), owner_id=current_user.id)
    db.add(new_room)
    db.commit()
    db.refresh(new_room)
    
    # Add owner as admin member
    member = models.RoomMember(room_id=new_room.id, user_id=current_user.id, role="owner")
    db.add(member)
    db.commit()
    
    setattr(new_room, 'member_count', 1)
    return new_room

@router.get("/my", response_model=List[schemas.RoomResponse])
def get_my_rooms(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    rooms = db.query(models.Room, func.count(models.RoomMember.id).label("member_count"))\
        .join(models.RoomMember, models.Room.id == models.RoomMember.room_id)\
        .filter(models.RoomMember.user_id == current_user.id)\
        .group_by(models.Room.id).all()
    
    result = []
    for room, count in rooms:
        setattr(room, 'member_count', count)
        result.append(room)
    return result

@router.post("/{room_id}/join")
def join_room(room_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
        
    existing = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == room_id, 
        models.RoomMember.user_id == current_user.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already a member")
        
    member = models.RoomMember(room_id=room_id, user_id=current_user.id, role="member")
    db.add(member)
    db.commit()
    return {"detail": "Successfully joined"}

@router.post("/{room_id}/leave")
def leave_room(room_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    membership = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == room_id,
        models.RoomMember.user_id == current_user.id
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="You are not a member of this room")
    if membership.role == "owner":
        raise HTTPException(status_code=400, detail="Room owner cannot leave. Delete the room instead.")

    db.delete(membership)
    db.commit()
    return {"detail": "Successfully left"}

@router.patch("/{room_id}", response_model=schemas.RoomResponse)
def update_room(room_id: int, payload: schemas.RoomUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if room.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the room owner can update this room")

    updates = payload.model_dump(exclude_unset=True)
    if "title" in updates:
        if not isinstance(updates["title"], str) or not updates["title"].strip():
            raise HTTPException(status_code=400, detail="Room title is required")
    if "max_members" in updates and (updates["max_members"] is None or updates["max_members"] < 1):
        raise HTTPException(status_code=400, detail="Max members must be at least 1")

    for key, value in updates.items():
        if key == "title" and isinstance(value, str):
            value = value.strip()
        setattr(room, key, value)

    db.commit()
    db.refresh(room)
    member_count = db.query(models.RoomMember).filter(models.RoomMember.room_id == room_id).count()
    setattr(room, 'member_count', member_count)
    return room

@router.delete("/{room_id}")
def delete_room(room_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if room.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the room owner can delete this room")

    db.query(models.Invitation).filter(models.Invitation.room_id == room_id).delete(synchronize_session=False)
    db.delete(room)
    db.commit()
    return {"detail": "Room deleted successfully"}
# --- ADD THESE TO THE BOTTOM OF rooms.py ---

@router.get("/")
def get_all_rooms(db: Session = Depends(get_db)):
    rooms = db.query(models.Room).all()
    result = []
    for room in rooms:
        member_count = db.query(models.RoomMember).filter(models.RoomMember.room_id == room.id).count()
        setattr(room, 'member_count', member_count)
        result.append(room)
    return result

@router.get("/{room_id}")
def get_room(room_id: int, db: Session = Depends(get_db)):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    member_count = db.query(models.RoomMember).filter(models.RoomMember.room_id == room_id).count()
    setattr(room, 'member_count', member_count)
    return room

@router.get("/{room_id}/members/")
def get_room_members(room_id: int, db: Session = Depends(get_db)):
    members = db.query(models.RoomMember).filter(models.RoomMember.room_id == room_id).all()
    result = []
    for m in members:
        user = db.query(models.User).filter(models.User.id == m.user_id).first()
        if user:
            result.append({
                "id": m.id,
                "user_id": user.id,
                "name": user.name,
                "avatar": user.avatar,
                "role": m.role,
                "joined_at": m.joined_at,
                "level": user.level,
                "xp": user.xp
            })
    return result

@router.get("/{room_id}/resources/")
def get_room_resources(room_id: int, db: Session = Depends(get_db)):
    resources = db.query(models.Resource).filter(models.Resource.room_id == room_id).all()
    return resources
# --- ADD THIS TO THE BOTTOM OF rooms.py ---

@router.post("/{room_id}/meeting")
def create_room_meeting(room_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    membership = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == room_id,
        models.RoomMember.user_id == current_user.id
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Join the room before creating a meeting")
        
    # Generate a unique video meeting link (using Jitsi for free, instant web calls)
    # You can swap this with your Agora RTC link/token logic later!
    unique_meeting_id = f"FocuseMate-{room_id}-{uuid.uuid4().hex[:8]}"
    meeting_link = f"https://meet.jit.si/{unique_meeting_id}"
    
    room.meeting_link = meeting_link
    room.is_live = True  # Lights up the "LIVE" badge in your app!
    
    db.commit()
    db.refresh(room)
    
    return {"meeting_link": meeting_link}
# --- ADD THESE TO THE BOTTOM OF rooms.py ---

# 1. Define what the incoming resource data looks like
class ResourceCreate(BaseModel):
    title: str
    description: Optional[str] = None
    resource_type: str = "link"
    link: Optional[str] = None

class RoomMemberRoleUpdate(BaseModel):
    role: str

# 2. Handle the POST request to add a new resource
@router.post("/{room_id}/resources/")
def add_room_resource(
    room_id: int, 
    payload: ResourceCreate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    room = db.query(models.Room).filter(models.Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
        
    new_resource = models.Resource(
        room_id=room_id,
        added_by_id=current_user.id,
        title=payload.title,
        description=payload.description,
        resource_type=payload.resource_type,
        link=payload.link
    )
    db.add(new_resource)
    db.commit()
    db.refresh(new_resource)
    
    return new_resource

# 3. Handle the DELETE request so you can remove resources later
@router.delete("/{room_id}/resources/{resource_id}")
def delete_room_resource(
    room_id: int, 
    resource_id: int, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    resource = db.query(models.Resource).filter(
        models.Resource.id == resource_id, 
        models.Resource.room_id == room_id
    ).first()
    
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
        
    # Security check: Only let the creator or a room admin delete it
    if resource.added_by_id != current_user.id:
        room_member = db.query(models.RoomMember).filter(
            models.RoomMember.room_id == room_id,
            models.RoomMember.user_id == current_user.id
        ).first()
        
        if not room_member or room_member.role not in ["admin", "owner"]:
            raise HTTPException(status_code=403, detail="Not authorized to delete this resource")

    db.delete(resource)
    db.commit()
    return {"detail": "Resource deleted successfully"}

@router.patch("/{room_id}/members/{user_id}")
def update_room_member_role(
    room_id: int,
    user_id: int,
    payload: RoomMemberRoleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if payload.role not in ["admin", "member"]:
        raise HTTPException(status_code=400, detail="Role must be admin or member")

    current_member = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == room_id,
        models.RoomMember.user_id == current_user.id
    ).first()
    if not current_member or current_member.role != "owner":
        raise HTTPException(status_code=403, detail="Only the room owner can change roles")

    member = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == room_id,
        models.RoomMember.user_id == user_id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Room member not found")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot change the room owner's role")

    member.role = payload.role
    db.commit()
    return {"detail": "Member role updated successfully"}

@router.delete("/{room_id}/members/{user_id}")
def remove_room_member(
    room_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    current_member = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == room_id,
        models.RoomMember.user_id == current_user.id
    ).first()
    if not current_member or current_member.role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Only room admins can remove members")

    member = db.query(models.RoomMember).filter(
        models.RoomMember.room_id == room_id,
        models.RoomMember.user_id == user_id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Room member not found")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove the room owner")
    if current_member.role == "admin" and member.role == "admin":
        raise HTTPException(status_code=403, detail="Admins cannot remove other admins")

    db.delete(member)
    db.commit()
    return {"detail": "Member removed successfully"}
