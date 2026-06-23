"""
SQLite 数据库模块
存储词汇的基本信息、语义向量、使用频率及置信度评分
"""
import contextlib
import json
import logging
import os
import sqlite3
from datetime import datetime

import numpy as np

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "vocab.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


@contextlib.contextmanager
def db_transaction():
    """数据库事务上下文管理器（自动关闭连接）"""
    db = _conn()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with db_transaction() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS vocab (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL UNIQUE,
                vector BLOB,                    -- 词向量 (numpy → bytes)
                vector_dim INTEGER DEFAULT 0,
                domain_score REAL DEFAULT 0,
                length_score REAL DEFAULT 0,
                uniqueness_score REAL DEFAULT 0,
                quality_score REAL DEFAULT 0,
                frequency INTEGER DEFAULT 1,
                is_verified INTEGER DEFAULT 0,
                source TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vocab_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL,
                action TEXT NOT NULL,          -- 'add' / 'update' / 'spellcheck'
                detail TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_vocab_word ON vocab(word);
            CREATE INDEX IF NOT EXISTS idx_vocab_quality ON vocab(quality_score);
        """)
        db.commit()


def word_exists(word: str) -> bool:
    with db_transaction() as db:
        r = db.execute("SELECT 1 FROM vocab WHERE word = ?", (word.lower(),)).fetchone()
    return r is not None


def save_word(word: str, vector: np.ndarray, quality: dict, source: str = "",
              verified: bool = True, tags: list = None):
    """保存词汇到数据库（原子操作）"""
    now = datetime.utcnow().isoformat()
    vec_bytes = vector.tobytes() if vector is not None else b""
    with db_transaction() as db:
        try:
            db.execute("""
                INSERT INTO vocab (word, vector, vector_dim, domain_score, length_score,
                    uniqueness_score, quality_score, is_verified, source, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(word) DO UPDATE SET
                    vector=excluded.vector, vector_dim=excluded.vector_dim,
                    domain_score=excluded.domain_score, length_score=excluded.length_score,
                    uniqueness_score=excluded.uniqueness_score, quality_score=excluded.quality_score,
                    frequency=frequency+1, updated_at=excluded.updated_at
            """, (
                word.lower(),
                vec_bytes,
                len(vector) if vector is not None else 0,
                quality.get("domain_score", 0),
                quality.get("length_score", 0),
                quality.get("uniqueness_score", 0),
                quality.get("overall", 0),
                1 if verified else 0,
                source,
                json.dumps(tags or []),
                now, now,
            ))
            # 写日志
            db.execute("""
                INSERT INTO vocab_log (word, action, detail, created_at)
                VALUES (?, 'add', ?, ?)
            """, (word.lower(), f"source={source}, quality={quality.get('overall', 0):.3f}", now))
            db.commit()
        except Exception as e:
            logger.error(f"Failed to save word '{word}': {e}")
            raise


def get_word(word: str) -> dict | None:
    with db_transaction() as db:
        r = db.execute("SELECT * FROM vocab WHERE word = ?", (word.lower(),)).fetchone()
    if not r:
        return None
    d = dict(r)
    if d["vector"] and d["vector_dim"] > 0:
        d["vector_array"] = np.frombuffer(d["vector"], dtype=np.float32)
    d["tags"] = json.loads(d["tags"]) if d["tags"] else []
    return d


def get_all_words() -> list[dict]:
    with db_transaction() as db:
        rows = db.execute("SELECT word, quality_score, frequency, is_verified, created_at FROM vocab ORDER BY quality_score DESC").fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with db_transaction() as db:
        total = db.execute("SELECT COUNT(*) FROM vocab").fetchone()[0]
        verified = db.execute("SELECT COUNT(*) FROM vocab WHERE is_verified=1").fetchone()[0]
        avg_q = db.execute("SELECT AVG(quality_score) FROM vocab").fetchone()[0] or 0
        recent = db.execute("SELECT COUNT(*) FROM vocab_log WHERE action='add' AND created_at > datetime('now', '-1 day')").fetchone()[0]
    return {"total": total, "verified": verified, "avg_quality": round(avg_q, 3), "recent_adds": recent}


def get_recent_logs(limit: int = 20) -> list[dict]:
    with db_transaction() as db:
        rows = db.execute("SELECT * FROM vocab_log ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
