"""
LLM helper — Google Gemini via google-genai SDK.

Single provider strategy: all LLM traffic (conversation, vision, dream job)
goes through Gemini. Conversation enables `google_search` grounding so BB
can cite real sources when asked about anything outside the local catalog.

Returns (text, sources) where sources is a list of {title, uri} dicts
extracted from `groundingMetadata` — empty list when grounding wasn't used
or wasn't requested.
"""

import logging
import os
from typing import List, Dict, Optional, Tuple

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

Sources = List[Dict[str, str]]


def _client() -> genai.Client:
    api_key = os.getenv('GEMINI_API_KEY', '')
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Get one at https://aistudio.google.com/apikey"
        )
    return genai.Client(api_key=api_key)


def _normalize_model(model: str) -> str:
    """Strip an OpenRouter-style provider prefix ('google/gemini-x' -> 'gemini-x')."""
    if '/' in model:
        return model.split('/', 1)[1]
    return model


def _openai_to_gemini(
    messages: List[Dict[str, str]],
) -> Tuple[Optional[str], List[types.Content]]:
    """
    Convert OpenAI-style [{role, content}] to Gemini's split format:
    a single `system_instruction` string + a list of Content(role=user|model).
    """
    system_parts: list[str] = []
    contents: list[types.Content] = []
    for m in messages:
        role = m.get('role')
        content = m.get('content', '')
        if not content:
            continue
        if role == 'system':
            system_parts.append(content)
        else:
            gemini_role = 'model' if role == 'assistant' else 'user'
            contents.append(
                types.Content(role=gemini_role, parts=[types.Part(text=content)])
            )
    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, contents


def _extract_sources(response) -> Sources:
    """Pull grounding sources out of a Gemini response, if any."""
    try:
        candidates = getattr(response, 'candidates', None) or []
        if not candidates:
            return []
        md = getattr(candidates[0], 'grounding_metadata', None)
        if not md:
            return []
        chunks = getattr(md, 'grounding_chunks', None) or []
        seen_uris: set[str] = set()
        sources: Sources = []
        for c in chunks:
            web = getattr(c, 'web', None)
            if not web:
                continue
            uri = getattr(web, 'uri', None)
            if not uri or uri in seen_uris:
                continue
            seen_uris.add(uri)
            sources.append({
                'title': getattr(web, 'title', None) or uri,
                'uri': uri,
            })
        return sources
    except Exception as e:
        logger.warning(f"Failed to extract grounding sources: {e}")
        return []


async def chat_completion(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 800,
    response_format_json: bool = False,
    with_search: bool = False,
) -> Tuple[str, Sources]:
    """
    Call Gemini and return (text, sources).

    Args:
        messages: OpenAI-style list. 'system' role goes to system_instruction;
                  'assistant' role is mapped to 'model'.
        model: e.g. 'gemini-3.1-flash-lite'. Strips 'google/' prefix if present.
        temperature, max_tokens: standard sampling controls.
        response_format_json: forces JSON output (response_mime_type).
        with_search: enables google_search grounding (paid above free tier).
    """
    model_name = _normalize_model(model or os.getenv('AI_MODEL', 'gemini-2.5-flash'))
    system_instruction, contents = _openai_to_gemini(messages)

    cfg_kwargs: Dict = {
        'temperature': temperature,
        'max_output_tokens': max_tokens,
    }
    if system_instruction:
        cfg_kwargs['system_instruction'] = system_instruction
    if response_format_json:
        cfg_kwargs['response_mime_type'] = 'application/json'
    if with_search:
        cfg_kwargs['tools'] = [types.Tool(google_search=types.GoogleSearch())]

    config = types.GenerateContentConfig(**cfg_kwargs)

    client = _client()
    response = await client.aio.models.generate_content(
        model=model_name,
        contents=contents,
        config=config,
    )
    text = response.text or ''
    sources = _extract_sources(response) if with_search else []
    return text, sources
