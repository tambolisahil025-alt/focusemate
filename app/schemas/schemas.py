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
    reply_to: Optional[int] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- NEW: DIRECT MESSAGES SCHEMAS ---
class DirectMessageCreate(BaseModel):
    receiver_id: int
    content: str
    message_type: str = "text"
    reply_to: Optional[int] = None

class DirectMessageResponse(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    content: str
    message_type: str
    created_at: datetime
    sender_name: Optional[str] = None
    sender_avatar: Optional[str] = None
    reply_to: Optional[int] = None
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

class QuizGenerateRequest(BaseModel):
    topic: str
    subject: Optional[str] = None
    difficulty: str = "medium"
    question_count: int = 10

class QuizQuestion(BaseModel):
    question: str
    options: List[str]
    correct_answer: str
    explanation: str
    difficulty: str
    topic: str

class QuizGenerateResponse(BaseModel):
    topic: str
    subject: Optional[str] = None
    difficulty: str
    questions: List[QuizQuestion]

class QuizCompleteRequest(BaseModel):
    topic: str
    subject: Optional[str] = None
    difficulty: str
    question_count: int
    correct_answers: int

class QuizAttemptResponse(BaseModel):
    id: int
    topic: str
    subject: Optional[str] = None
    difficulty: str
    question_count: int
    correct_answers: int
    score: int
    percentage: int
    xp_earned: int
    created_at: datetime
    user_xp: Optional[int] = None
    user_level: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)

class GamificationResponse(BaseModel):
    xp: int
    level: int
    current_level_xp: int
    xp_to_next_level: int
    badges: List[Dict[str, str]]
