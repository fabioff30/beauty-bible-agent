"""
Storage layer — async API over SQLCipher (sync driver wrapped via asyncio.to_thread).

aiosqlite does not support SQLCipher natively, and the bot's traffic is low enough
that a single connection guarded by an asyncio.Lock outperforms pool complexity.
"""

import asyncio
import json
import logging
from typing import Any, Optional

from .connection import connect

logger = logging.getLogger(__name__)

_conn = None
_write_lock = asyncio.Lock()


def _get_conn():
    global _conn
    if _conn is None:
        _conn = connect()
        _conn.row_factory = _row_to_dict
    return _conn


def _row_to_dict(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


# ---------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------
def _exec_sync(sql: str, params: tuple = ()) -> int:
    conn = _get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def _fetchone_sync(sql: str, params: tuple = ()) -> Optional[dict]:
    conn = _get_conn()
    cur = conn.execute(sql, params)
    return cur.fetchone()


def _fetchall_sync(sql: str, params: tuple = ()) -> list[dict]:
    conn = _get_conn()
    cur = conn.execute(sql, params)
    return cur.fetchall()


async def _exec(sql: str, params: tuple = ()) -> int:
    async with _write_lock:
        return await asyncio.to_thread(_exec_sync, sql, params)


async def _fetchone(sql: str, params: tuple = ()) -> Optional[dict]:
    return await asyncio.to_thread(_fetchone_sync, sql, params)


async def _fetchall(sql: str, params: tuple = ()) -> list[dict]:
    return await asyncio.to_thread(_fetchall_sync, sql, params)


# ---------------------------------------------------------------
# USERS
# ---------------------------------------------------------------
async def ensure_user(user_id: int, username: Optional[str], first_name: Optional[str]) -> None:
    await _exec(
        """
        INSERT INTO users(user_id, telegram_username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            telegram_username = excluded.telegram_username,
            first_name        = excluded.first_name,
            last_seen_at      = datetime('now'),
            deleted_at        = NULL
        """,
        (user_id, username, first_name),
    )


async def mark_seen(user_id: int) -> None:
    await _exec("UPDATE users SET last_seen_at = datetime('now') WHERE user_id = ?", (user_id,))


async def record_consent(user_id: int) -> None:
    await _exec(
        "UPDATE users SET consent_lgpd_at = datetime('now') WHERE user_id = ? AND consent_lgpd_at IS NULL",
        (user_id,),
    )


# ---------------------------------------------------------------
# PROFILE (skin analysis)
# ---------------------------------------------------------------
async def get_profile(user_id: int) -> Optional[dict]:
    row = await _fetchone("SELECT * FROM profiles WHERE user_id = ?", (user_id,))
    if not row:
        return None
    row['concerns'] = json.loads(row.get('concerns_json') or '[]')
    row['preferences'] = json.loads(row.get('preferences_json') or '{}')
    return row


async def upsert_profile(user_id: int, analysis: dict, photo_hash: Optional[str] = None) -> None:
    """Persist a SkinAnalyzer result. Replaces the live profile snapshot."""
    concerns_json = json.dumps(analysis.get('concerns', []), ensure_ascii=False)
    await _exec(
        """
        INSERT INTO profiles (
            user_id, fitzpatrick, skin_tone_name, skin_type, undertone,
            concerns_json, confidence, last_photo_hash, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET
            fitzpatrick      = excluded.fitzpatrick,
            skin_tone_name   = excluded.skin_tone_name,
            skin_type        = excluded.skin_type,
            undertone        = excluded.undertone,
            concerns_json    = excluded.concerns_json,
            confidence       = excluded.confidence,
            last_photo_hash  = COALESCE(excluded.last_photo_hash, profiles.last_photo_hash),
            updated_at       = datetime('now')
        """,
        (
            user_id,
            analysis.get('skin_tone_fitzpatrick'),
            analysis.get('skin_tone'),
            analysis.get('skin_type'),
            analysis.get('undertone'),
            concerns_json,
            analysis.get('confidence'),
            photo_hash,
        ),
    )


async def update_preferences(user_id: int, preferences: dict) -> None:
    """Merge-update the preferences JSON blob."""
    current = await get_profile(user_id)
    merged = {**(current.get('preferences') if current else {}), **preferences}
    await _exec(
        "UPDATE profiles SET preferences_json = ?, updated_at = datetime('now') WHERE user_id = ?",
        (json.dumps(merged, ensure_ascii=False), user_id),
    )


# ---------------------------------------------------------------
# MESSAGES (rolling buffer)
# ---------------------------------------------------------------
async def append_message(
    user_id: int,
    role: str,
    content_redacted: str,
    tokens_estimate: Optional[int] = None,
) -> int:
    return await _exec(
        """
        INSERT INTO messages (user_id, role, content_redacted, tokens_estimate)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, role, content_redacted, tokens_estimate),
    )


async def recent_messages(user_id: int, limit: int = 10) -> list[dict]:
    """Return latest N messages oldest-first (ready for chat prompt)."""
    rows = await _fetchall(
        """
        SELECT id, role, content_redacted, created_at
        FROM messages
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    return list(reversed(rows))


# ---------------------------------------------------------------
# FACTS (semantic memory)
# ---------------------------------------------------------------
async def upsert_fact(
    user_id: int,
    key: str,
    value: str,
    confidence: float = 0.8,
    source_episode_id: Optional[int] = None,
) -> None:
    await _exec(
        """
        INSERT INTO facts (user_id, key, value, confidence, source_episode_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, key) DO UPDATE SET
            value             = excluded.value,
            confidence        = excluded.confidence,
            source_episode_id = excluded.source_episode_id,
            updated_at        = datetime('now')
        """,
        (user_id, key, value, confidence, source_episode_id),
    )


async def list_facts(user_id: int) -> list[dict]:
    return await _fetchall(
        "SELECT key, value, confidence, updated_at FROM facts WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    )


# ---------------------------------------------------------------
# EPISODES (episodic memory)
# ---------------------------------------------------------------
async def append_episode(
    user_id: int,
    kind: str,
    summary: str,
    payload: Optional[dict] = None,
    importance: float = 0.5,
    expires_at: Optional[str] = None,
) -> int:
    return await _exec(
        """
        INSERT INTO episodes (user_id, kind, summary, payload_json, importance, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            kind,
            summary,
            json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            importance,
            expires_at,
        ),
    )


async def recent_episodes(user_id: int, kind: Optional[str] = None, limit: int = 5) -> list[dict]:
    if kind:
        return await _fetchall(
            "SELECT * FROM episodes WHERE user_id = ? AND kind = ? ORDER BY id DESC LIMIT ?",
            (user_id, kind, limit),
        )
    return await _fetchall(
        "SELECT * FROM episodes WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )


# ---------------------------------------------------------------
# SUMMARIES (rolling, weekly)
# ---------------------------------------------------------------
async def get_summary(user_id: int, scope: str = 'rolling') -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM summaries WHERE user_id = ? AND scope = ?",
        (user_id, scope),
    )


async def upsert_summary(
    user_id: int,
    scope: str,
    summary: str,
    covers_until: str,
    last_message_id: int = 0,
) -> None:
    await _exec(
        """
        INSERT INTO summaries (user_id, scope, summary, covers_until, last_message_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, scope) DO UPDATE SET
            summary         = excluded.summary,
            covers_until    = excluded.covers_until,
            last_message_id = excluded.last_message_id,
            updated_at      = datetime('now')
        """,
        (user_id, scope, summary, covers_until, last_message_id),
    )


# ---------------------------------------------------------------
# PURCHASES & FEEDBACK
# ---------------------------------------------------------------
async def record_purchase(
    user_id: int,
    product_id: str,
    context: Optional[str] = None,
    feedback: Optional[str] = None,
    feedback_note: Optional[str] = None,
) -> int:
    return await _exec(
        """
        INSERT INTO purchases (user_id, product_id, context, feedback, feedback_note)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, product_id, context, feedback, feedback_note),
    )


# ---------------------------------------------------------------
# AUDIT LOG
# ---------------------------------------------------------------
async def audit(user_id: Optional[int], action: str, detail: Optional[str] = None) -> None:
    await _exec(
        "INSERT INTO audit_log (user_id, action, detail) VALUES (?, ?, ?)",
        (user_id, action, detail),
    )


# ---------------------------------------------------------------
# Consolidation queries (used by the dream/sleep-time job)
# ---------------------------------------------------------------
async def active_users_since(since_iso: str) -> list[dict]:
    """
    Return users with at least one message after `since_iso`.
    Excludes tombstoned users.
    """
    return await _fetchall(
        """
        SELECT DISTINCT u.user_id, u.first_name, u.telegram_username
        FROM users u
        JOIN messages m ON m.user_id = u.user_id
        WHERE m.created_at > ? AND u.deleted_at IS NULL
        """,
        (since_iso,),
    )


async def messages_for_user_after_id(user_id: int, after_id: int = 0) -> list[dict]:
    """
    Messages with id > after_id, oldest-first.
    Using id (not created_at) avoids same-second tie issues.
    """
    return await _fetchall(
        """
        SELECT id, role, content_redacted, created_at
        FROM messages
        WHERE user_id = ? AND id > ?
        ORDER BY id ASC
        """,
        (user_id, after_id),
    )


async def latest_message_ts(user_id: int) -> Optional[str]:
    row = await _fetchone(
        "SELECT created_at FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    return row['created_at'] if row else None


async def expire_low_value_episodes() -> int:
    """
    Delete expired low-importance episodes. Returns count.
    Episodes with expires_at set and < now() AND importance < 0.4 are removed.
    """
    async with _write_lock:
        return await asyncio.to_thread(_expire_episodes_sync)


def _expire_episodes_sync() -> int:
    conn = _get_conn()
    cur = conn.execute(
        """
        DELETE FROM episodes
        WHERE expires_at IS NOT NULL
          AND expires_at < datetime('now')
          AND importance < 0.4
        """
    )
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------
# LGPD — right to be forgotten
# ---------------------------------------------------------------
async def delete_user_data(user_id: int) -> dict[str, int]:
    """
    Hard delete every row owned by this user (cascades + explicit per safety).
    Returns counts so we can show the user what was removed.
    """
    async with _write_lock:
        return await asyncio.to_thread(_delete_user_data_sync, user_id)


def _delete_user_data_sync(user_id: int) -> dict[str, int]:
    conn = _get_conn()
    counts = {}
    for table in (
        'messages',
        'episodes',
        'facts',
        'summaries',
        'purchases',
        'profiles',
    ):
        cur = conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        counts[table] = cur.rowcount
    # Tombstone the user row instead of hard delete (keeps audit traceable)
    conn.execute(
        "UPDATE users SET deleted_at = datetime('now'), telegram_username = NULL, first_name = NULL WHERE user_id = ?",
        (user_id,),
    )
    conn.execute(
        "INSERT INTO audit_log (user_id, action, detail) VALUES (?, 'delete_user_data', ?)",
        (user_id, json.dumps(counts)),
    )
    conn.commit()
    return counts
