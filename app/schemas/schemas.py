from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    name: str

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    avatar: Optional[str] = None
    bio: Optional[str] = None
    level: int
    xp: int
    location: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    user_data: UserResponse

class RoomBase(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = "others"
    tags: Optional[List[str]] = []
    max_members: int = 50

class RoomCreate(RoomBase):
    pass

class RoomUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    max_members: Optional[int] = None

class RoomResponse(RoomBase):
    id: int
    owner_id: int
    is_live: bool
    meeting_link: Optional[str] = None
    member_count: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class MessageResponse(BaseModel):
    id: int
    room_id: int
    sender_id: Optional[int]
    sender_name: Optional[str]
    sender_avatar: Optional[str]
    content: str
    message_type: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- NEW: DIRECT MESSAGES SCHEMAS ---
class DirectMessageCreate(BaseModel):
    receiver_id: int
    content: str
    message_type: str = "text"

class DirectMessageResponse(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    content: str
    message_type: str
    created_at: datetime
    sender_name: Optional[str] = None
    sender_avatar: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

# --- AI ASSISTANT SCHEMAS ---
class AIMessage(BaseModel):
    """Single message in AI chat"""
    role: str  # 'user' or 'assistant'
    content: str

class AIChatRequest(BaseModel):
    """Request for AI chat endpoint"""
    message: str
    chat_history: Optional[List[AIMessage]] = None
    screen_name: Optional[str] = None
    user_action: Optional[str] = None
    app_context: Optional[Dict[str, Any]] = None

class AIChatResponse(BaseModel):
    """Response from AI chat endpoint"""
    response: str
    messages: List[AIMessage]
    suggestions: Optional[List[str]] = None

class AISuggestionsRequest(BaseModel):
    """Request for AI suggestions"""
    screen_name: str
    user_action: Optional[str] = None
    app_context: Optional[Dict[str, Any]] = None

class AISuggestionsResponse(BaseModel):
    """Response with AI suggestions"""
    suggestions: List[str]

class AIContextRequest(BaseModel):
    """Current app context captured by the AI assistant"""
    screen: Optional[str] = None
    action: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
