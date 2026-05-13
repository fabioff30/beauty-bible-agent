"""
Natural conversation pacing for Telegram replies.

Three pieces working together:
  1. split_response()        — break an LLM output into bubble-sized chunks
  2. keep_typing()           — task that re-sends "typing..." every 4s (Telegram
                               drops the indicator after 5s, so we refresh)
  3. send_chunked()          — send each chunk with a per-chunk typing pulse
                               and human-paced delay between bubbles

Design choices (from research, May 2026):
- Split on the LLM's explicit <split> tag first; fall back to paragraphs,
  then sentences. Explicit tags are far more reliable than regex on LLM output.
- Delay formula: 1.2s baseline + len(chunk)/25 + jitter(±0.4s),
  clamped to [1.0s, 5.0s]. Sub-1s feels bot-spammy; >5s feels stuck.
- Max 5 chunks per response to avoid spam.
"""

import asyncio
import logging
import random
import re

from telegram.constants import ChatAction

logger = logging.getLogger(__name__)

SPLIT_TAG = "<split>"
MAX_CHUNKS = 5
# Only absorb truly tiny stragglers (a lone emoji or 1-2 words). When the LLM
# uses <split>, short bubbles like "Entendi." are intentional — keep them.
MIN_CHUNK_CHARS = 12
SOFT_MAX_CHUNK_CHARS = 220     # try to split anything longer
HARD_MAX_CHUNK_CHARS = 4000    # Telegram message limit is 4096; leave headroom


def split_response(text: str) -> list[str]:
    """Return a list of chunks ready to send as separate messages."""
    text = text.strip()
    if not text:
        return []

    # 1) Explicit tag from the LLM (preferred)
    if SPLIT_TAG in text:
        parts = [p.strip() for p in text.split(SPLIT_TAG)]
        chunks = _coalesce(parts)
    else:
        # 2) Fallback: paragraphs
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if len(paragraphs) > 1:
            chunks = _coalesce(paragraphs)
        elif len(text) > SOFT_MAX_CHUNK_CHARS:
            # 3) Last resort: sentence boundaries
            chunks = _split_by_sentence(text)
        else:
            chunks = [text]

    chunks = [c[:HARD_MAX_CHUNK_CHARS] for c in chunks if c]
    return chunks[:MAX_CHUNKS]


def _coalesce(parts: list[str]) -> list[str]:
    """Merge fragments < MIN_CHUNK_CHARS into the next chunk."""
    out: list[str] = []
    buf = ""
    for p in parts:
        if not p:
            continue
        if buf:
            p = (buf + " " + p).strip()
            buf = ""
        if len(p) < MIN_CHUNK_CHARS:
            buf = p
        else:
            out.append(p)
    if buf:
        if out:
            out[-1] = (out[-1] + " " + buf).strip()
        else:
            out.append(buf)
    return out


def _split_by_sentence(text: str) -> list[str]:
    """Group sentences into ~SOFT_MAX_CHUNK_CHARS chunks."""
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    out: list[str] = []
    cur = ""
    for s in sentences:
        if not s:
            continue
        if len(cur) + len(s) + 1 > SOFT_MAX_CHUNK_CHARS and cur:
            out.append(cur.strip())
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out or [text]


def delay_for(chunk: str) -> float:
    """Human-paced delay before sending this chunk."""
    baseline = 1.2
    per_char = len(chunk) / 25.0
    jitter = random.uniform(-0.3, 0.5)
    return max(1.0, min(baseline + per_char + jitter, 5.0))


async def keep_typing(bot, chat_id: int, stop_event: asyncio.Event) -> None:
    """Re-send the typing indicator every ~4s until stop_event is set."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception as e:
            logger.warning(f"send_chat_action failed: {e}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4.0)
        except asyncio.TimeoutError:
            continue


async def send_chunked(bot, chat_id: int, text: str) -> list[str]:
    """
    Send the response as separate bubbles with typing pulses and pacing.
    Returns the chunks actually sent (useful for persistence).
    """
    chunks = split_response(text)
    sent: list[str] = []
    for i, chunk in enumerate(chunks):
        if i > 0:
            try:
                await bot.send_chat_action(chat_id, ChatAction.TYPING)
            except Exception:
                pass
            await asyncio.sleep(delay_for(chunk))
        await bot.send_message(chat_id=chat_id, text=chunk)
        sent.append(chunk)
    return sent
