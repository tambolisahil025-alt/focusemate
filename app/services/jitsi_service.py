from datetime import datetime, timedelta
import hmac
import hashlib
import uuid
from typing import Optional

from jose import jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models


def hash_token(raw_token: str) -> str:
    secret = settings.SECRET_KEY or "default_secret"
    return hmac.new(secret.encode(), raw_token.encode(), hashlib.sha256).hexdigest()


def generate_invite_token(db: Session, meeting_id: int, inviter_id: int, single_use: bool = True, expires_in: Optional[int] = None) -> str:
    raw = str(uuid.uuid4())
    token_hash = hash_token(raw)
    ttl = expires_in or settings.MEETING_INVITE_TTL_SEC
    expires_at = datetime.utcnow() + timedelta(seconds=ttl)

    inv = models.MeetingInvitation(meeting_id=meeting_id, inviter_id=inviter_id, token_hash=token_hash, expires_at=expires_at, single_use=single_use)
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return raw


def validate_and_consume_invite(db: Session, raw_token: str) -> Optional[models.MeetingInvitation]:
    token_hash = hash_token(raw_token)
    inv = db.query(models.MeetingInvitation).filter(models.MeetingInvitation.token_hash == token_hash).first()
    if not inv:
        return None
    if inv.used:
        return None
    if inv.expires_at and inv.expires_at < datetime.utcnow():
        return None
    # consume if single use
    if inv.single_use:
        inv.used = True
        db.add(inv)
        db.commit()
    return inv


def create_jitsi_jwt(user: models.User, meeting: models.Meeting, moderator: bool = False) -> str:
    if not settings.JITSI_APP_ID or not settings.JITSI_APP_SECRET:
        raise RuntimeError("Jitsi configuration missing")

    now = datetime.utcnow()
    exp = now + timedelta(seconds=settings.JITSI_TOKEN_TTL_SEC)

    payload = {
        "aud": settings.JITSI_APP_ID,
        "iss": settings.JITSI_ISSUER or settings.JITSI_APP_ID,
        "sub": settings.JITSI_APP_ID,
        "exp": int(exp.timestamp()),
        "room": meeting.jitsi_room,
        "context": {
            "user": {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
            },
            "features": {
                "moderator": bool(moderator)
            }
        }
    }

    token = jwt.encode(payload, settings.JITSI_APP_SECRET, algorithm=settings.JITSI_ALGORITHM)
    return token


def create_manage_token(meeting_id: int, user_id: int, expires_seconds: int = 86400) -> str:
    now = datetime.utcnow()
    exp = now + timedelta(seconds=expires_seconds)
    payload = {"meeting_id": meeting_id, "user_id": user_id, "role": "host", "exp": int(exp.timestamp())}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token
