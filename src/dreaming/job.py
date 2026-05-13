"""
Dream-time consolidation job — runs offline (typically nightly).

For each user with new messages since the last consolidation, the job:
  1) Extracts durable facts from the new messages and upserts them.
  2) Updates the rolling summary covering the user's history.
  3) Cleans up expired low-importance episodes.
  4) Records audit log entries.

This is the practical implementation of "sleep-time compute"
(Lin et al., 2025, arXiv:2504.13171): pay LLM cost once in idle
time so test-time interactions stay snappy and personalized.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.db import storage
from src.llm import chat_completion
from src.dreaming.prompts import (
    EXTRACT_FACTS_SYSTEM,
    SUMMARY_SYSTEM,
    build_extract_user_prompt,
    build_summary_user_prompt,
)

logger = logging.getLogger(__name__)

# Cap how many messages we send to a single LLM call to keep costs bounded.
MAX_MESSAGES_PER_CONSOLIDATION = 80


def _dream_model() -> str:
    """Allow overriding the model for the dream job (cheaper for batch)."""
    return os.getenv('DREAM_MODEL') or os.getenv('AI_MODEL', 'google/gemini-2.5-flash')


def _strip_json_fences(content: str) -> str:
    """Remove ```json fences if the model added them despite the instructions."""
    s = content.strip()
    if s.startswith('```'):
        s = s.split('\n', 1)[1] if '\n' in s else s[3:]
        if s.endswith('```'):
            s = s[:-3]
    if s.lower().startswith('json'):
        s = s[4:]
    return s.strip()


async def extract_facts(new_messages: list[dict]) -> list[dict]:
    """Call the LLM to extract durable facts. Returns [] if nothing extracted."""
    if not new_messages:
        return []

    messages = [
        {"role": "system", "content": EXTRACT_FACTS_SYSTEM},
        {"role": "user", "content": build_extract_user_prompt(new_messages)},
    ]

    raw, _ = await chat_completion(
        messages,
        model=_dream_model(),
        temperature=0.2,
        max_tokens=800,
        response_format_json=True,
    )
    try:
        parsed = json.loads(_strip_json_fences(raw))
        facts = parsed.get('facts', [])
        # Defensive: only keep entries with the expected shape
        return [
            f for f in facts
            if isinstance(f, dict) and f.get('key') and f.get('value')
        ]
    except json.JSONDecodeError as e:
        logger.warning(f"Fact extractor returned non-JSON: {e}; raw[:200]={raw[:200]!r}")
        return []


async def update_summary(previous_summary: Optional[str], new_messages: list[dict]) -> Optional[str]:
    if not new_messages and not previous_summary:
        return None

    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {"role": "user", "content": build_summary_user_prompt(previous_summary, new_messages)},
    ]

    raw, _ = await chat_completion(
        messages,
        model=_dream_model(),
        temperature=0.3,
        max_tokens=900,
        response_format_json=True,
    )
    try:
        parsed = json.loads(_strip_json_fences(raw))
        return parsed.get('summary')
    except json.JSONDecodeError as e:
        logger.warning(f"Summary updater returned non-JSON: {e}; raw[:200]={raw[:200]!r}")
        return None


async def consolidate_user(user_id: int) -> dict:
    """
    Run the full consolidation pipeline for a single user.
    Returns a dict with what was done — useful for logging and tests.
    """
    summary_row = await storage.get_summary(user_id, scope='rolling')
    after_id = summary_row['last_message_id'] if summary_row else 0
    previous_summary = summary_row['summary'] if summary_row else None

    new_messages = await storage.messages_for_user_after_id(user_id, after_id)
    if not new_messages:
        logger.debug(f"User {user_id}: nothing new to consolidate")
        return {'user_id': user_id, 'skipped': True, 'reason': 'no_new_messages'}

    # Cap window — we want recent context, not the entire history
    if len(new_messages) > MAX_MESSAGES_PER_CONSOLIDATION:
        new_messages = new_messages[-MAX_MESSAGES_PER_CONSOLIDATION:]

    facts_written = 0
    summary_written = False

    # 1) Facts
    facts = await extract_facts(new_messages)
    for f in facts:
        try:
            await storage.upsert_fact(
                user_id=user_id,
                key=str(f['key'])[:100],
                value=str(f['value'])[:500],
                confidence=float(f.get('confidence', 0.7)),
            )
            facts_written += 1
        except Exception as e:
            logger.warning(f"User {user_id}: failed to write fact {f}: {e}")

    # 2) Rolling summary
    new_summary = await update_summary(previous_summary, new_messages)
    if new_summary:
        await storage.upsert_summary(
            user_id=user_id,
            scope='rolling',
            summary=new_summary[:4000],
            covers_until=new_messages[-1]['created_at'],
            last_message_id=new_messages[-1]['id'],
        )
        summary_written = True

    await storage.audit(
        user_id=user_id,
        action='consolidation',
        detail=json.dumps({
            'messages_processed': len(new_messages),
            'facts_written': facts_written,
            'summary_written': summary_written,
        }),
    )

    return {
        'user_id': user_id,
        'messages_processed': len(new_messages),
        'facts_written': facts_written,
        'summary_written': summary_written,
    }


async def run_consolidation(lookback_hours: int = 24) -> dict:
    """
    Top-level entry point. Iterates all users active in the last
    `lookback_hours` and consolidates each.
    """
    since_dt = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    since_iso = since_dt.strftime('%Y-%m-%d %H:%M:%S')

    users = await storage.active_users_since(since_iso)
    logger.info(f"Dream job: {len(users)} active users since {since_iso}")

    results = []
    for u in users:
        try:
            results.append(await consolidate_user(u['user_id']))
        except Exception as e:
            logger.exception(f"Consolidation failed for user {u['user_id']}: {e}")
            results.append({'user_id': u['user_id'], 'error': str(e)})

    # Housekeeping: drop expired, low-importance episodes
    expired = await storage.expire_low_value_episodes()

    summary = {
        'users_seen': len(users),
        'expired_episodes': expired,
        'per_user': results,
    }
    await storage.audit(
        user_id=None,
        action='dream_job',
        detail=json.dumps({
            'users_seen': len(users),
            'expired_episodes': expired,
        }),
    )
    logger.info(f"Dream job complete: {summary['users_seen']} users, {expired} expired episodes")
    return summary
