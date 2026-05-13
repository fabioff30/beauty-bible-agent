"""
SQLite (SQLCipher) connection management.
Single file, encrypted at rest. WAL mode for concurrent reads.
"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _data_dir() -> Path:
    """Resolve the data directory from env or project default."""
    env_dir = os.getenv('DATA_DIR')
    if env_dir:
        return Path(env_dir)
    return Path(__file__).resolve().parent.parent.parent / 'data'


def db_path() -> Path:
    """Absolute path to the encrypted SQLite file."""
    return _data_dir() / 'beauty_bible.db'


def _get_passphrase() -> str:
    """Read SQLCipher passphrase from env; fail loudly if missing in non-debug."""
    pw = os.getenv('SQLCIPHER_KEY')
    if not pw:
        if os.getenv('DEBUG', '').lower() == 'true':
            logger.warning("SQLCIPHER_KEY not set — falling back to dev passphrase. DO NOT USE IN PRODUCTION.")
            return 'dev-only-not-secure'
        raise RuntimeError(
            "SQLCIPHER_KEY environment variable is required. "
            "Generate a 32+ char random string and set it in your .env."
        )
    return pw


def connect():
    """
    Open an encrypted SQLite connection (sync).
    Use this for migrations and short-lived scripts.
    Async paths get a connection via storage layer with aiosqlite.
    """
    try:
        from sqlcipher3 import dbapi2 as sqlcipher
    except ImportError as e:
        raise RuntimeError(
            "sqlcipher3-binary not installed. Run: pip install sqlcipher3-binary"
        ) from e

    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlcipher.connect(str(path))
    # SQLCipher key MUST be the first thing applied
    key = _get_passphrase().replace("'", "''")
    conn.executescript(f"PRAGMA key = '{key}';")
    # Concurrency + durability tuning
    conn.executescript("""
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous  = NORMAL;
        PRAGMA foreign_keys = ON;
        PRAGMA busy_timeout = 5000;
    """)
    return conn


def init_db() -> None:
    """Apply schema.sql idempotently. Called on bot startup."""
    schema_file = Path(__file__).parent / 'schema.sql'
    sql = schema_file.read_text(encoding='utf-8')

    conn = connect()
    try:
        conn.executescript(sql)
        conn.commit()
        version = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
        logger.info(f"DB initialized at {db_path()} — schema v{version[0] if version else '?'}")
    finally:
        conn.close()
