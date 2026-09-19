from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from app.db import models
from app.schemas import schemas
from app.api.deps import get_db, get_current_user
from app.services.storage_service import upload_upload_file

router = APIRouter(prefix="/users", tags=["users"])


class UserUpdate(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    avatar: Optional[str] = None

@router.get("/me", response_model=schemas.UserResponse)
def read_user_me(current_user: models.User = Depends(get_current_user)):
    return current_user

@router.patch("/me", response_model=schemas.UserResponse)
def update_user_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if payload.name is not None:
        current_user.name = payload.name
    if payload.bio is not None:
        current_user.bio = payload.bio
    if payload.avatar is not None:
        current_user.avatar = payload.avatar or None
        
    db.commit()
    db.refresh(current_user)
    return current_user

@router.post("/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Profile photo must be an image")

    try:
        avatar_url = await upload_upload_file(file, f"avatars/{current_user.id}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to store profile photo in cloud storage") from exc
    
    current_user.avatar = avatar_url
    db.commit()
    db.refresh(current_user)
    
    return {"avatar_url": avatar_url}

@router.get("/search")
def search_users(
    q: str, 
    limit: int = 20, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    # Case-insensitive search on the user's name
    users = db.query(models.User).filter(
        models.User.name.ilike(f"%{q}%"),
        models.User.id != current_user.id
    ).limit(limit).all()
    
    # Return formatted to match frontend expectation: { "users": [...] }
    return {"users": [schemas.UserResponse.model_validate(u).model_dump() for u in users]}
