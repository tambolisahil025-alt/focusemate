from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 1. ADD 'features' TO THIS IMPORT
from app.api.routers import auth, rooms, ws, users, features, messages, ai_router 

from app.core.config import settings
import os
from sqlalchemy import inspect, text

from app.db.database import engine
from app.db import models
models.Base.metadata.create_all(bind=engine)

def ensure_compatible_schema():
    inspector = inspect(engine)
    if "notifications" in inspector.get_table_names():
        notification_columns = {col["name"] for col in inspector.get_columns("notifications")}
        if "actor_id" not in notification_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE notifications ADD COLUMN actor_id INTEGER"))
        if "room_id" not in notification_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE notifications ADD COLUMN room_id INTEGER"))

ensure_compatible_schema()

app = FastAPI(title=settings.PROJECT_NAME)

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

# 2. ADD THIS LINE
app.include_router(features.router) 

@app.get("/")
def root():
    return {"message": "Welcome to FocuseMate API"}
