from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 1. ADD 'features' TO THIS IMPORT
from app.api.routers import auth, rooms, ws, users, features, messages, ai_router, meetings, courses, quiz

from app.core.config import settings
from app.db.database import engine
from app.db.models import Base
import os
    
# Create database tables

app = FastAPI(title=settings.PROJECT_NAME)


@app.on_event("startup")
def create_missing_tables() -> None:
    Base.metadata.create_all(bind=engine)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads/avatars", exist_ok=True)
app.mount("/static", StaticFiles(directory="uploads"), name="static")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(rooms.router)
app.include_router(messages.router)
app.include_router(ws.router)
app.include_router(ai_router.router)

# meetings router
app.include_router(meetings.router)
app.include_router(courses.router)

# 2. ADD THIS LINE
app.include_router(features.router) 
app.include_router(quiz.router)

@app.get("/")
def root():
    return {"message": "Welcome to StudySpace API"}
