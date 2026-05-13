"""
LLM call helper — provider-agnostic chat completion.
Used by both the conversational BB agent and the dream-time consolidation job.

Provider routing:
    AI_PROVIDER=openrouter  -> https://openrouter.ai/api/v1/chat/completions
    AI_PROVIDER=openai      -> https://api.openai.com/v1/chat/completions
    AI_PROVIDER=gemini      -> google.generativeai SDK
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

    if provider == 'gemini':
        return await _call_gemini(messages, model)

    if provider == 'openrouter':
        api_url = "https://openrouter.ai/api/v1/chat/completions"
        api_key = os.getenv('OPENROUTER_API_KEY', '')
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://beautybible.app",
            "X-Title": "Beauty Bible",
            "Content-Type": "application/json",
        }
    elif provider == 'openai':
        api_url = "https://api.openai.com/v1/chat/completions"
        api_key = os.getenv('OPENAI_API_KEY', '')
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    else:
        raise ValueError(f"Unknown AI_PROVIDER: {provider}")

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


async def _call_gemini(messages: List[Dict[str, str]], model: str) -> str:
    """Direct Google Gemini SDK path."""
    import google.generativeai as genai

    genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
    gemini_model = genai.GenerativeModel(model)

    prompt = ""
    for msg in messages:
        if msg['role'] == 'system':
            prompt += f"INSTRUÇÕES: {msg['content']}\n\n"
        elif msg['role'] == 'user':
            prompt += f"Usuária: {msg['content']}\n"
        elif msg['role'] == 'assistant':
            prompt += f"Assistente: {msg['content']}\n"

    response = gemini_model.generate_content(prompt)
    return response.text
