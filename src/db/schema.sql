-- Beauty Bible — SQLite schema
-- All user-owned tables are namespaced by user_id (Telegram chat id).
-- FTS5 virtual tables provide cheap text search before we bring in vectors.

PRAGMA foreign_keys = ON;

-- ============================================================
-- USERS
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    user_id        INTEGER PRIMARY KEY,        -- Telegram user/chat id
    telegram_username TEXT,
    first_name     TEXT,
    locale         TEXT NOT NULL DEFAULT 'pt-BR',
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
    consent_lgpd_at TEXT,                       -- when the user accepted terms
    deleted_at     TEXT                         -- soft-delete tombstone
);

-- ============================================================
-- PROFILES — semantic, slow-changing, one row per user
-- ============================================================
CREATE TABLE IF NOT EXISTS profiles (
    user_id            INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    fitzpatrick        TEXT,                    -- I..VI
    skin_tone_name     TEXT,                    -- "Média Clara"
    skin_type          TEXT,                    -- oleosa|seca|mista|normal|sensível
    undertone          TEXT,                    -- quente|frio|neutro|oliva
    concerns_json      TEXT NOT NULL DEFAULT '[]',
    preferences_json   TEXT NOT NULL DEFAULT '{}',  -- budget, vegan, fragrance-free, etc
    confidence         TEXT,                    -- alta|média|baixa
    last_photo_hash    TEXT,                    -- sha256 of the last analyzed photo (no PII)
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- FACTS — atomic semantic memory ("alergic to fragrance", "budget R$200")
-- One row per (user, key). UPSERT on conflict.
-- ============================================================
CREATE TABLE IF NOT EXISTS facts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    key                TEXT NOT NULL,
    value              TEXT NOT NULL,
    confidence         REAL NOT NULL DEFAULT 0.8, -- 0..1
    source_episode_id  INTEGER REFERENCES episodes(id) ON DELETE SET NULL,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, key)
);
CREATE INDEX IF NOT EXISTS idx_facts_user ON facts(user_id);

-- ============================================================
-- EPISODES — episodic memory: what happened, with timestamps
-- ============================================================
CREATE TABLE IF NOT EXISTS episodes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kind               TEXT NOT NULL,           -- 'skin_analysis' | 'conversation' | 'recommendation' | 'feedback'
    summary            TEXT NOT NULL,
    payload_json       TEXT,                    -- structured details (analysis result, products, etc)
    importance         REAL NOT NULL DEFAULT 0.5, -- 0..1, drives retention
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at         TEXT                     -- NULL = never expires
);
CREATE INDEX IF NOT EXISTS idx_episodes_user_ts ON episodes(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_kind ON episodes(user_id, kind);

-- FTS5 mirror of episodes.summary for "lembra quando…" queries
CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    summary,
    content='episodes',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, summary) VALUES (new.id, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary) VALUES('delete', old.id, old.summary);
END;
CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary) VALUES('delete', old.id, old.summary);
    INSERT INTO episodes_fts(rowid, summary) VALUES (new.id, new.summary);
END;

-- ============================================================
-- MESSAGES — rolling conversation buffer (PII-redacted)
-- ============================================================
CREATE TABLE IF NOT EXISTS messages (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role               TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content_redacted   TEXT NOT NULL,
    tokens_estimate    INTEGER,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_user_ts ON messages(user_id, created_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content_redacted,
    content='messages',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content_redacted) VALUES (new.id, new.content_redacted);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content_redacted) VALUES('delete', old.id, old.content_redacted);
END;

-- ============================================================
-- CONVERSATION SUMMARIES — rolling summaries written by sleep-time agent
-- One row per (user, scope) — replaced on update.
-- ============================================================
CREATE TABLE IF NOT EXISTS summaries (
    user_id            INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scope              TEXT NOT NULL,           -- 'rolling' | 'weekly' | 'monthly'
    summary            TEXT NOT NULL,
    covers_until       TEXT NOT NULL,           -- last message ts covered (display only)
    last_message_id    INTEGER NOT NULL DEFAULT 0,  -- monotonic watermark — tie-proof
    updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, scope)
);

-- ============================================================
-- PURCHASES & FEEDBACK — closes the recommendation loop
-- ============================================================
CREATE TABLE IF NOT EXISTS purchases (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    product_id         TEXT NOT NULL,           -- matches products.json id
    context            TEXT,                    -- 'recommended' | 'self' | 'gift'
    feedback           TEXT,                    -- 'loved' | 'ok' | 'rejected' | NULL
    feedback_note      TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_purchases_user ON purchases(user_id, created_at DESC);

-- ============================================================
-- AUDIT LOG — LGPD-compliant operations log (no PII)
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER,                 -- can be NULL for system events
    action             TEXT NOT NULL,           -- 'delete_user_data' | 'consent' | 'data_export'
    detail             TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at DESC);

-- ============================================================
-- SCHEMA VERSION — for future migrations
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('version', '1');
