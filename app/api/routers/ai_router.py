"""
AI Assistant API Routes for FocuseMate
Provides AI chat, suggestions, and context-aware help
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.schemas import schemas
from app.api.deps import get_db, get_optional_current_user
from app.db import models
from app.services.groq_service import get_groq_service
import logging
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai-assistant"])


def _ai_error_response(error: Exception) -> HTTPException:
    message = str(error)
    if "GROQ_API_KEY" in message:
        return HTTPException(status_code=503, detail="AI service is not configured")
    if "timeout" in message.lower():
        return HTTPException(status_code=504, detail="AI service timed out")
    return HTTPException(status_code=502, detail="AI service is temporarily unavailable")


@router.post("/chat", response_model=schemas.AIChatResponse)
async def ai_chat(
    request: schemas.AIChatRequest,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    """
    Chat with AI assistant
    
    Args:
        request: Chat request with message and history
        db: Database session
        current_user: Current authenticated user
    
    Returns:
        AI response with chat history
    """
    try:
        groq_service = await get_groq_service()
        
        # Build message history
        messages = []
        if request.chat_history:
            messages = [
                {"role": msg.role, "content": msg.content}
                for msg in request.chat_history
            ]
        
        # Add current message
        messages.append({
            "role": "user",
            "content": request.message
        })
        
        # Build system context
        user_context = (
            f"User: {current_user.name} (Level {current_user.level})"
            if current_user
            else "User: Guest"
        )

        system_prompt = f"""You are FocuseMate AI Assistant, a helpful guide for a collaborative study platform.
You help users:
- Navigate the app
- Understand features
- Complete tasks
- Answer questions about studying and collaboration

{user_context}"""
        
        if request.screen_name:
            system_prompt += f"\nCurrent Screen: {request.screen_name}"
        if request.user_action:
            system_prompt += f"\nUser Action: {request.user_action}"
        if request.app_context:
            system_prompt += f"\nApp Context: {request.app_context}"
        
        system_prompt += "\n\nBe concise, friendly, and helpful. Keep responses under 200 words."
        
        # Get AI response
        ai_response = await groq_service.chat(
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=500,
            temperature=0.7
        )
        
        # Add AI response to messages
        messages.append({
            "role": "assistant",
            "content": ai_response
        })
        
        # Get suggestions based on response
        suggestions = None
        if request.screen_name:
            try:
                suggestions = await groq_service.get_context_suggestions(
                    screen_name=request.screen_name,
                    user_action=request.user_action,
                    app_context=request.app_context
                )
            except Exception as e:
                logger.warning(f"Failed to get suggestions: {str(e)}")
        
        # Convert messages to response format
        response_messages = [
            schemas.AIMessage(role=msg["role"], content=msg["content"])
            for msg in messages
        ]
        
        return schemas.AIChatResponse(
            response=ai_response,
            messages=response_messages,
            suggestions=suggestions
        )
    
    except Exception as e:
        logger.error(f"AI chat error: {str(e)}")
        raise _ai_error_response(e)


@router.post("/suggestions", response_model=schemas.AISuggestionsResponse)
async def get_ai_suggestions(
    request: schemas.AISuggestionsRequest,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    """
    Get AI suggestions for current screen/action
    
    Args:
        request: Suggestions request with context
        db: Database session
        current_user: Current authenticated user
    
    Returns:
        List of suggestions
    """
    try:
        groq_service = await get_groq_service()
        
        suggestions = await groq_service.get_context_suggestions(
            screen_name=request.screen_name,
            user_action=request.user_action,
            app_context=request.app_context
        )
        
        return schemas.AISuggestionsResponse(suggestions=suggestions)
    
    except Exception as e:
        logger.error(f"AI suggestions error: {str(e)}")
        raise _ai_error_response(e)


@router.get("/help")
async def get_screen_help(
    screen: str,
    feature: str = None,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    """
    Get contextual help for a screen
    
    Args:
        screen: Screen name
        feature: Optional feature name
        db: Database session
        current_user: Current authenticated user
    
    Returns:
        Help text
    """
    try:
        groq_service = await get_groq_service()
        
        help_text = await groq_service.get_screen_help(
            screen_name=screen,
            feature=feature
        )
        
        return {"help": help_text, "screen": screen}
    
    except Exception as e:
        logger.error(f"AI help error: {str(e)}")
        raise _ai_error_response(e)


@router.post("/context")
async def save_app_context(
    context_data: schemas.AIContextRequest,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    """
    Save app context for AI assistant (for future personalization)
    
    Args:
        context_data: Context information
        db: Database session
        current_user: Current authenticated user
    
    Returns:
        Status response
    """
    try:
        # This endpoint can be extended to store user interaction patterns
        # for better personalization in the future
        
        user_label = current_user.id if current_user else "guest"
        logger.info(f"Context saved for user {user_label}: {context_data.model_dump(exclude_none=True)}")
        
        return {
            "status": "success",
            "message": "Context saved"
        }
    
    except Exception as e:
        logger.error(f"Context save error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error saving context: {str(e)}"
        )
