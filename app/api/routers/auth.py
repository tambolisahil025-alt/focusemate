from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.db import models
from app.schemas import schemas
from app.api.deps import get_db
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token
from app.core.config import settings
from jose import JWTError, jwt
from pydantic import BaseModel
from typing import Optional
router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=schemas.UserResponse)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_pwd = get_password_hash(user.password)
    new_user = models.User(email=user.email, name=user.name, hashed_password=hashed_pwd)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.post("/token", response_model=schemas.Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer", "user_data": user}

class RefreshPayload(BaseModel):
    refresh_token: str

@router.post("/refresh", response_model=schemas.Token)
def refresh_access_token(payload: RefreshPayload, db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate refresh token",
    )
    try:
        token_payload = jwt.decode(payload.refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = token_payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if not user:
        raise credentials_exception

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer", "user_data": user}

class SocialAuthPayload(BaseModel):
    access_token: str
    id_token: Optional[str] = None
    profile: dict

@router.post("/google", response_model=schemas.Token)
def google_auth(payload: SocialAuthPayload, db: Session = Depends(get_db)):
    profile = payload.profile
    email = profile.get("email")
    name = profile.get("name")
    avatar = profile.get("picture")

    if not email:
        raise HTTPException(status_code=400, detail="Google account must have an email")

    # 1. Check if user exists
    user = db.query(models.User).filter(models.User.email == email).first()

    if not user:
        # 2. Create user if they don't exist
        user = models.User(
            email=email,
            name=name,
            avatar=avatar,
            provider="google"
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # 3. Generate FocuseMate tokens for the session
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token, 
        "refresh_token": refresh_token, 
        "token_type": "bearer", 
        "user_data": user
    }

@router.post("/facebook", response_model=schemas.Token)
def facebook_auth(payload: SocialAuthPayload, db: Session = Depends(get_db)):
    profile = payload.profile or {}
    email = profile.get("email")
    facebook_id = str(profile.get("id") or "")
    if not email and facebook_id:
        email = f"facebook_{facebook_id}@focusemate.local"
    if not email:
        raise HTTPException(status_code=400, detail="Facebook profile must include an email or id")

    name = profile.get("name") or profile.get("first_name") or "Facebook User"
    picture = profile.get("picture")
    avatar = picture.get("data", {}).get("url") if isinstance(picture, dict) else picture

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        user = models.User(email=email, name=name, avatar=avatar, provider="facebook")
        db.add(user)
        db.commit()
        db.refresh(user)

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user_data": user,
    }
