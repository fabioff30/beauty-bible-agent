"""
LLM call helper — OpenAI-compatible chat completion.
Used by both the conversational BB agent and the dream-time consolidation job.

Provider routing:
    AI_PROVIDER=openrouter  -> https://openrouter.ai/api/v1/chat/completions  (default)
    AI_PROVIDER=openai      -> https://api.openai.com/v1/chat/completions

Note: Gemini models are reached via OpenRouter (model = "google/gemini-*").
We do not depend on the Google SDK directly.
"""

import logging
import os
from typing import List, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


async def chat_completion(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 800,
    response_format_json: bool = False,
) -> str:
    """
    Call the configured LLM provider with OpenAI-style messages.
    Returns the assistant text response.
    """
    provider = os.getenv('AI_PROVIDER', 'openrouter')
    model = model or os.getenv('AI_MODEL', 'google/gemini-2.5-flash')

    if provider == 'openai':
        api_url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}",
            "Content-Type": "application/json",
        }
    else:
        # Default: OpenRouter
        api_url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
            "HTTP-Referer": "https://beautybible.app",
            "X-Title": "Beauty Bible",
            "Content-Type": "application/json",
        }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9,
    }
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content']
