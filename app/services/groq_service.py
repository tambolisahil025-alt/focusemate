"""
GROQ AI Service for FocuseMate
Provides secure AI chat integration using GROQ API
"""

import asyncio
import json
from typing import Optional, Dict, Any, List
import httpx
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class GroqService:
    """Service for interacting with GROQ AI API"""
    
    BASE_URL = "https://api.groq.com/openai/v1"
    MODEL = "llama3-70b-8192"
    DEFAULT_TIMEOUT = 30.0
    MAX_RETRIES = 3
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize GROQ service with API key"""
        self.api_key = api_key or settings.GROQ_API_KEY
        if not self.api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    async def _make_request(
        self,
        endpoint: str,
        method: str = "POST",
        data: Optional[Dict[str, Any]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_count: int = 0,
    ) -> Dict[str, Any]:
        """Make async HTTP request to GROQ API with retry logic"""
        url = f"{self.BASE_URL}{endpoint}"
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method.upper() == "POST":
                    response = await client.post(url, json=data, headers=self.headers)
                elif method.upper() == "GET":
                    response = await client.get(url, headers=self.headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                response.raise_for_status()
                return response.json()
        
        except httpx.TimeoutException as e:
            logger.error(f"GROQ API timeout: {str(e)}")
            if retry_count < self.MAX_RETRIES:
                await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                return await self._make_request(endpoint, method, data, timeout, retry_count + 1)
            raise Exception(f"GROQ API timeout after {self.MAX_RETRIES} retries")
        
        except httpx.HTTPStatusError as e:
            logger.error(f"GROQ API error: {e.response.status_code} - {e.response.text}")
            if e.response.status_code == 429 and retry_count < self.MAX_RETRIES:  # Rate limit
                await asyncio.sleep(2 ** (retry_count + 1))
                return await self._make_request(endpoint, method, data, timeout, retry_count + 1)
            raise Exception(f"GROQ API error: {e.response.status_code}")

        except httpx.RequestError as e:
            logger.error(f"GROQ network error: {str(e)}")
            if retry_count < self.MAX_RETRIES:
                await asyncio.sleep(2 ** retry_count)
                return await self._make_request(endpoint, method, data, timeout, retry_count + 1)
            raise Exception("GROQ API network error")
        
        except Exception as e:
            logger.error(f"GROQ service error: {str(e)}")
            raise
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Send a chat message to GROQ and get AI response
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Creativity level (0-2)
            max_tokens: Max response length
            system_prompt: Optional system context
        
        Returns:
            AI response text
        """
        # Add system prompt if provided
        formatted_messages = [
            {
                "role": message.get("role") if message.get("role") in {"user", "assistant"} else "user",
                "content": str(message.get("content", ""))[:4000],
            }
            for message in messages
            if message.get("content")
        ]
        if system_prompt:
            formatted_messages.insert(0, {
                "role": "system",
                "content": system_prompt
            })
        
        payload = {
            "model": self.MODEL,
            "messages": formatted_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        response = await self._make_request("/chat/completions", data=payload)
        
        # Extract response text
        if "choices" in response and len(response["choices"]) > 0:
            return response["choices"][0]["message"]["content"]
        
        raise Exception("Invalid GROQ response format")
    
    async def get_context_suggestions(
        self,
        screen_name: str,
        user_action: Optional[str] = None,
        app_context: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Get AI suggestions based on current app context
        
        Args:
            screen_name: Current screen/page name
            user_action: Current user action
            app_context: Additional app context
        
        Returns:
            List of suggested actions/messages
        """
        context_str = f"Screen: {screen_name}"
        if user_action:
            context_str += f", Action: {user_action}"
        if app_context:
            context_str += f", Context: {json.dumps(app_context, default=str)}"
        
        system_prompt = """You are a helpful in-app assistant for FocuseMate, a collaborative study platform. 
        Provide 2-3 brief, actionable suggestions for the user based on the current screen and action.
        Format as a JSON array of strings. Keep suggestions short (max 60 chars each)."""
        
        messages = [{
            "role": "user",
            "content": f"Current app context: {context_str}. What should I suggest?"
        }]
        
        try:
            response = await self.chat(
                messages=messages,
                system_prompt=system_prompt,
                max_tokens=500,
                temperature=0.5
            )
            
            # Parse JSON suggestions
            suggestions = json.loads(response)
            return suggestions if isinstance(suggestions, list) else [response]
        except Exception as e:
            logger.warning(f"Failed to parse suggestions: {str(e)}")
            return ["How can I help you today?"]
    
    async def get_screen_help(
        self,
        screen_name: str,
        feature: Optional[str] = None,
    ) -> str:
        """
        Get contextual help for a specific screen
        
        Args:
            screen_name: Screen name
            feature: Optional specific feature
        
        Returns:
            Help text
        """
        system_prompt = """You are a helpful guide for FocuseMate. Provide brief, friendly help text 
        for the given screen. Keep response under 200 chars."""
        
        content = f"Help for screen: {screen_name}"
        if feature:
            content += f", Feature: {feature}"
        
        messages = [{
            "role": "user",
            "content": content
        }]
        
        return await self.chat(
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=300,
            temperature=0.5
        )


# Global GROQ service instance
_groq_service: Optional[GroqService] = None


async def get_groq_service() -> GroqService:
    """Get or create global GROQ service instance"""
    global _groq_service
    if _groq_service is None:
        _groq_service = GroqService()
    return _groq_service
