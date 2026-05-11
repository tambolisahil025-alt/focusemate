from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
import os
import uuid
import shutil

from app.db import models
from app.schemas import schemas
from app.api.deps import get_db, get_current_user
from app.core.config import settings

router = APIRouter(prefix="/users", tags=["users"])

# Ensure the upload directory exists for profile pictures
UPLOAD_DIR = "uploads/avatars"
os.makedirs(UPLOAD_DIR, exist_ok=True)

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
        current_user.avatar = payload.avatar
        
    db.commit()
    db.refresh(current_user)
    return current_user

@router.post("/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Generate a unique filename to avoid overwrites
    file_ext = file.filename.split(".")[-1]
    file_name = f"{uuid.uuid4()}.{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, file_name)
    
    # Save the file locally
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    base_url = settings.api_base_url
    avatar_url = f"{base_url}/static/avatars/{file_name}"
    
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