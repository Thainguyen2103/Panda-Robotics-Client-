"""Small SQLite store for completed text turns; raw audio is never persisted."""
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from config import settings

_lock = threading.RLock()
_db_path = settings.PRIVATE_DATA_ROOT / "conversations.sqlite3"


@contextmanager
def _connect():
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(_db_path, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def initialize():
    with _lock, _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'local',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
            turn_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            language TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(conversation_id, turn_id, role)
        );
        CREATE INDEX IF NOT EXISTS messages_by_conversation ON messages(conversation_id, message_id);
        CREATE TABLE IF NOT EXISTS learning_progress (
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
            item_id TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(conversation_id, item_id)
        );
        CREATE TABLE IF NOT EXISTS memory_summaries (
            conversation_id TEXT PRIMARY KEY REFERENCES conversations(conversation_id) ON DELETE CASCADE,
            summary TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)


def save_turn(conversation_id, turn_id, question, answer, language=None):
    initialize()
    now = datetime.now(timezone.utc).isoformat()
    with _lock, _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO conversations(conversation_id,created_at,updated_at) VALUES(?,?,?) "
                   "ON CONFLICT(conversation_id) DO UPDATE SET updated_at=excluded.updated_at",
                   (conversation_id, now, now))
        db.executemany(
            "INSERT INTO messages(conversation_id,turn_id,role,content,language,status,created_at) "
            "VALUES(?,?,?,?,?,'completed',?) ON CONFLICT(conversation_id,turn_id,role) "
            "DO UPDATE SET content=excluded.content,language=excluded.language,status='completed'",
            [(conversation_id, str(turn_id), 'user', question, language, now),
             (conversation_id, str(turn_id), 'assistant', answer, language, now)],
        )
        # Bound retention per conversation to 500 messages (250 complete turns).
        db.execute("DELETE FROM messages WHERE conversation_id=? AND message_id NOT IN "
                   "(SELECT message_id FROM messages WHERE conversation_id=? ORDER BY message_id DESC LIMIT 500)",
                   (conversation_id, conversation_id))


def recent_turns(conversation_id, limit=3):
    initialize()
    with _lock, _connect() as db:
        rows = db.execute("SELECT turn_id,role,content FROM messages WHERE conversation_id=? "
                          "ORDER BY message_id DESC LIMIT ?", (conversation_id, limit * 2)).fetchall()
    return [{"role": role, "content": content} for _, role, content in reversed(rows)]


def search(conversation_id, query, limit=3):
    """Simple lexical retrieval, constrained to the requested conversation."""
    terms = [term.strip(".,?!:;()[]{}\"'`").casefold() for term in query.split()]
    stop_words = {"the", "and", "for", "là", "của", "một", "này", "đó", "what", "how"}
    terms = [term for term in terms if len(term) > 2 and term not in stop_words][:8]
    if not terms:
        return []
    initialize()
    with _lock, _connect() as db:
        rows = db.execute("SELECT turn_id,role,content FROM messages WHERE conversation_id=? "
                          "ORDER BY message_id DESC LIMIT 500", (conversation_id,)).fetchall()
    scores = {}
    for turn_id, role, content in rows:
        matches = [term for term in terms if term in content.casefold()]
        score = sum(content.casefold().count(term) for term in matches)
        if len(matches) >= min(2, len(terms)):
            scores[turn_id] = max(scores.get(turn_id, 0), score)
    best_ids = [turn_id for turn_id, _ in
                sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]]
    grouped = {turn_id: [] for turn_id in best_ids}
    for turn_id, role, content in rows:
        if turn_id in grouped:
            grouped[turn_id].append((role, content))
    return [{"role": role, "content": content}
            for turn_id in best_ids for role, content in reversed(grouped[turn_id])]


def delete_conversation(conversation_id):
    initialize()
    with _lock, _connect() as db:
        db.execute("DELETE FROM conversations WHERE conversation_id=?", (conversation_id,))
