"""Owner-scoped conversations for the full-screen /ia workspace.

Tables are additive and independent from the staff Conversations inbox. An
authenticated user owns conversations by user id; an anonymous visitor owns
them through a hashed, HttpOnly cookie and a seven-day sliding retention.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from datetime import UTC, datetime, timedelta

from .core import DomainError, stamp, text, uid

VISITOR_DAYS = 7
MAX_CONVERSATIONS = 100
MAX_MESSAGES = 200
DEFAULT_TITLE = "Nueva conversación"
MESSAGE_STATES = {"complete", "streaming", "stopped", "error", "rejected"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_conversations (
 id TEXT PRIMARY KEY,
 owner_kind TEXT NOT NULL CHECK(owner_kind IN ('user','visitor')),
 owner_id TEXT NOT NULL,
 title TEXT NOT NULL DEFAULT 'Nueva conversación',
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_conversations_owner ON ai_conversations(owner_kind,owner_id,updated_at);
CREATE TABLE IF NOT EXISTS ai_messages (
 id TEXT PRIMARY KEY,
 conversation_id TEXT NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK(role IN ('user','assistant')),
 content TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('complete','streaming','stopped','error','rejected')),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_messages_conversation ON ai_messages(conversation_id,created_at);
CREATE TABLE IF NOT EXISTS ai_visitors (
 token_hash TEXT PRIMARY KEY,
 expires_at TEXT NOT NULL,
 created_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL
);
"""


# /ia has no consent step, so contact data is hidden before it is stored, as
# /chat does for messages written before consent. The model then receives the
# stored text, so what is kept is exactly what the model sees. Phone numbers:
# 7 to 15 digits with common separators, starting and ending on a digit (or an
# opening parenthesis) so surrounding punctuation survives.
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_PHONE = re.compile(r"(?<!\w)\+?\(?\d(?:[\s().-]*\d){6,14}(?!\w)")
MAX_INCOMING = 4000


def hide_contacts(value: str) -> str:
    hidden = _EMAIL.sub("[correo omitido]", value)
    hidden = _PHONE.sub("[teléfono omitido]", hidden)
    # A marker can be longer than what it replaces; the model accepts at most
    # MAX_INCOMING characters, so the stored text never exceeds it.
    return hidden[:MAX_INCOMING]


def _summary(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "message_count": row["message_count"] if "message_count" in row.keys() else None,
        "preview": row["preview"] if "preview" in row.keys() else "",
    }


class AIWorkspace:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript(SCHEMA)
        self._last_purge = 0.0

    @staticmethod
    def user_owner(user) -> dict:
        return {"kind": "user", "id": user["id"]}

    @staticmethod
    def _hash(token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token):
            return None
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def visitor(self, token):
        """Return the owner hash for a live visitor cookie, or None."""
        key = self._hash(token)
        if not key:
            return None
        with self.store.connect() as db:
            row = db.execute("SELECT expires_at FROM ai_visitors WHERE token_hash=?", (key,)).fetchone()
        return key if row and row["expires_at"] > stamp() else None

    def ensure_visitor(self, token=None):
        """Return (owner hash, new cookie token or None)."""
        key = self._hash(token)
        current = datetime.now(UTC)
        expiry = (current + timedelta(days=VISITOR_DAYS)).isoformat()
        with self.store.connect() as db:
            if key:
                row = db.execute("SELECT expires_at FROM ai_visitors WHERE token_hash=?", (key,)).fetchone()
                if row and row["expires_at"] > stamp():
                    db.execute(
                        "UPDATE ai_visitors SET last_seen_at=?,expires_at=? WHERE token_hash=?",
                        (stamp(), expiry, key),
                    )
                    return key, None
            new_token = secrets.token_urlsafe(32)
            key = self._hash(new_token)
            now = stamp()
            db.execute(
                "INSERT INTO ai_visitors(token_hash,expires_at,created_at,last_seen_at) VALUES(?,?,?,?)",
                (key, expiry, now, now),
            )
            return key, new_token

    def touch_visitor(self, token):
        """Slide a live visitor's retention to seven days from now.

        Returns False for an unknown or already expired token: retention never
        revives a visitor whose conversations may already be purged.
        """
        key = self._hash(token)
        if not key:
            return False
        now = stamp()
        expiry = (datetime.now(UTC) + timedelta(days=VISITOR_DAYS)).isoformat()
        with self.store.connect() as db:
            updated = db.execute(
                "UPDATE ai_visitors SET last_seen_at=?,expires_at=? WHERE token_hash=? AND expires_at>?",
                (now, expiry, key, now),
            ).rowcount
        return updated == 1

    def purge_expired_visitors(self):
        """Remove anonymous conversations after their retention window."""
        if time.monotonic() - self._last_purge < 3600:
            return
        self._last_purge = time.monotonic()
        now = stamp()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            expired = [
                row["token_hash"]
                for row in db.execute("SELECT token_hash FROM ai_visitors WHERE expires_at<=?", (now,)).fetchall()
            ]
            for key in expired:
                db.execute(
                    "DELETE FROM ai_conversations WHERE owner_kind='visitor' AND owner_id=?",
                    (key,),
                )
                db.execute("DELETE FROM ai_visitors WHERE token_hash=?", (key,))

    def _conversation(self, db, owner, conversation_id):
        current = text(conversation_id, "conversación", limit=64, required=True)
        row = db.execute(
            "SELECT * FROM ai_conversations WHERE id=? AND owner_kind=? AND owner_id=?",
            (current, owner["kind"], owner["id"]),
        ).fetchone()
        if not row:
            raise DomainError("Conversación no encontrada.", 404)
        return row

    @staticmethod
    def _message(row) -> dict:
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "content": row["content"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

    def list(self, owner, query=None):
        """Owner's active conversations, newest first. ``query`` matches the
        title or any stored message (contact data is already hidden there)."""
        search = " ".join(str(query or "").split())[:80]
        clause, params = "", []
        if search:
            pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            clause = (
                " AND (c.title LIKE ? ESCAPE '\\' OR EXISTS(SELECT 1 FROM ai_messages s"
                " WHERE s.conversation_id=c.id AND s.content LIKE ? ESCAPE '\\'))"
            )
            params = [pattern, pattern]
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT c.*,
                    (SELECT count(*) FROM ai_messages m WHERE m.conversation_id=c.id) AS message_count,
                    COALESCE((SELECT substr(m.content,1,140) FROM ai_messages m
                        WHERE m.conversation_id=c.id ORDER BY m.rowid DESC LIMIT 1),'') AS preview
                FROM ai_conversations c
                WHERE c.owner_kind=? AND c.owner_id=? AND c.status='active'""" + clause + """
                ORDER BY c.updated_at DESC,c.rowid DESC LIMIT ?""",
                (owner["kind"], owner["id"], *params, MAX_CONVERSATIONS),
            ).fetchall()
        return [_summary(row) for row in rows]

    def rename(self, owner, conversation_id, value):
        title = " ".join(hide_contacts(text(value, "título", limit=80, required=True)).split())[:80]
        if not title:
            raise DomainError("Escribe un título para la conversación.", 422)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            conversation = self._conversation(db, owner, conversation_id)
            db.execute(
                "UPDATE ai_conversations SET title=?,updated_at=? WHERE id=?",
                (title, stamp(), conversation["id"]),
            )
            updated = self._conversation(db, owner, conversation["id"])
        return _summary(updated)

    def delete(self, owner, conversation_id):
        """Permanently delete one of the owner's conversations and its messages.

        Refused while a reply is still being generated, so the stream never
        writes into a conversation that no longer exists.
        """
        cutoff = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            conversation = self._conversation(db, owner, conversation_id)
            busy = db.execute(
                "SELECT 1 FROM ai_messages WHERE conversation_id=? AND status='streaming' AND created_at>?",
                (conversation["id"], cutoff),
            ).fetchone()
            if busy:
                raise DomainError("Espera a que termine la respuesta para eliminar la conversación.", 409)
            db.execute("DELETE FROM ai_messages WHERE conversation_id=?", (conversation["id"],))
            db.execute("DELETE FROM ai_conversations WHERE id=?", (conversation["id"],))
        return {"deleted": conversation["id"]}

    def create(self, owner):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            empty = db.execute(
                """SELECT c.id FROM ai_conversations c
                WHERE c.owner_kind=? AND c.owner_id=? AND c.status='active'
                AND NOT EXISTS(SELECT 1 FROM ai_messages m WHERE m.conversation_id=c.id)
                ORDER BY c.updated_at DESC,c.rowid DESC LIMIT 1""",
                (owner["kind"], owner["id"]),
            ).fetchone()
            if empty:
                row = self._conversation(db, owner, empty["id"])
            else:
                conversation_id = uid()
                now = stamp()
                db.execute(
                    "INSERT INTO ai_conversations VALUES(?,?,?,?,?,?,?)",
                    (conversation_id, owner["kind"], owner["id"], DEFAULT_TITLE, "active", now, now),
                )
                row = self._conversation(db, owner, conversation_id)
        return _summary(row)

    def detail(self, owner, conversation_id):
        with self.store.connect() as db:
            conversation = self._conversation(db, owner, conversation_id)
            # A dropped connection or a crashed worker leaves a placeholder in
            # 'streaming'; only an active request may legitimately hold it.
            stale = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
            db.execute(
                "UPDATE ai_messages SET status='stopped' WHERE conversation_id=? AND status='streaming' AND created_at<?",
                (conversation["id"], stale),
            )
            rows = db.execute(
                """SELECT * FROM (
                    SELECT rowid AS seq,* FROM ai_messages WHERE conversation_id=?
                    ORDER BY created_at DESC,rowid DESC LIMIT ?
                ) ORDER BY created_at ASC,seq ASC""",
                (conversation["id"], MAX_MESSAGES),
            ).fetchall()
            count = db.execute(
                "SELECT count(*) FROM ai_messages WHERE conversation_id=?",
                (conversation["id"],),
            ).fetchone()[0]
        return {
            "conversation": _summary(conversation) | {"message_count": count},
            "messages": [self._message(row) for row in rows],
        }

    def begin_turn(self, owner, conversation_id, value):
        """Store the visitor's message and the reply placeholder in one transaction.

        The limit counts both rows, so a conversation never exceeds
        MAX_MESSAGES and concurrent requests (several tabs) cannot overrun it:
        BEGIN IMMEDIATE serializes the count and both inserts.
        Returns (conversation summary, user message, assistant placeholder).
        """
        return self._insert_turn(owner, conversation_id, value, with_reply=True)

    def append_user(self, owner, conversation_id, value):
        """Store a user message without a reply slot. The HTTP route uses begin_turn."""
        conversation, message, _ = self._insert_turn(owner, conversation_id, value, with_reply=False)
        return conversation, message

    def _insert_turn(self, owner, conversation_id, value, with_reply):
        incoming = hide_contacts(text(value, "mensaje", limit=MAX_INCOMING, required=True))
        needed = 2 if with_reply else 1
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            conversation = self._conversation(db, owner, conversation_id)
            count = db.execute(
                "SELECT count(*) FROM ai_messages WHERE conversation_id=?", (conversation["id"],)
            ).fetchone()[0]
            if count + needed > MAX_MESSAGES:
                raise DomainError(
                    "Esta conversación alcanzó el límite de mensajes. Inicia una nueva conversación.",
                    409,
                )
            message_id = uid()
            now = stamp()
            db.execute(
                "INSERT INTO ai_messages VALUES(?,?,?,?,?,?)",
                (message_id, conversation["id"], "user", incoming, "complete", now),
            )
            reply = None
            if with_reply:
                reply_id = uid()
                db.execute(
                    "INSERT INTO ai_messages VALUES(?,?,?,?,?,?)",
                    (reply_id, conversation["id"], "assistant", "", "streaming", now),
                )
                reply = db.execute("SELECT * FROM ai_messages WHERE id=?", (reply_id,)).fetchone()
            title = conversation["title"]
            if title in {DEFAULT_TITLE, ""}:
                title = " ".join(incoming.split())[:80] or DEFAULT_TITLE
            db.execute(
                "UPDATE ai_conversations SET title=?,updated_at=? WHERE id=?",
                (title, now, conversation["id"]),
            )
            message = db.execute("SELECT * FROM ai_messages WHERE id=?", (message_id,)).fetchone()
            updated = self._conversation(db, owner, conversation["id"])
        return _summary(updated), self._message(message), self._message(reply) if reply else None

    def prepare_regeneration(self, owner, conversation_id, assistant_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            conversation = self._conversation(db, owner, conversation_id)
            latest = db.execute(
                """SELECT rowid AS seq,* FROM ai_messages WHERE conversation_id=? AND role='assistant'
                ORDER BY rowid DESC LIMIT 1""",
                (conversation["id"],),
            ).fetchone()
            if not latest or latest["id"] != text(assistant_id, "respuesta", limit=64, required=True):
                raise DomainError("Solo puedes regenerar la última respuesta.", 409)
            prompt = db.execute(
                """SELECT rowid AS seq,* FROM ai_messages WHERE conversation_id=? AND role='user'
                AND rowid<? ORDER BY rowid DESC LIMIT 1""",
                (conversation["id"], latest["seq"]),
            ).fetchone()
            if not prompt:
                raise DomainError("No hay un mensaje del visitante para regenerar.", 409)
            rows = db.execute(
                """SELECT role,content FROM ai_messages WHERE conversation_id=? AND rowid<?
                AND status IN ('complete','stopped','error') AND content<>''
                ORDER BY rowid DESC LIMIT 20""",
                (conversation["id"], prompt["seq"]),
            ).fetchall()
            db.execute("UPDATE ai_messages SET status='streaming' WHERE id=?", (latest["id"],))
            db.execute("UPDATE ai_conversations SET updated_at=? WHERE id=?", (stamp(), conversation["id"]))
        return (
            _summary(conversation) | {"message_count": None},
            self._message(latest),
            prompt["content"],
            [dict(row) for row in reversed(rows)],
        )

    def history(self, conversation_id, exclude_id=None, limit=20):
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT role,content FROM ai_messages WHERE conversation_id=? AND id<>?
                AND status IN ('complete','stopped','error') AND content<>''
                ORDER BY rowid DESC LIMIT ?""",
                (conversation_id, exclude_id or "", limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def finish_assistant(self, message_id, content, status):
        if status not in MESSAGE_STATES - {"streaming"}:
            raise ValueError("Estado de mensaje no válido.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM ai_messages WHERE id=?", (message_id,)).fetchone()
            if not row:
                raise DomainError("La respuesta ya no existe.", 404)
            value = str(content or "")[:8000]
            db.execute("UPDATE ai_messages SET content=?,status=? WHERE id=?", (value, status, message_id))
            db.execute(
                "UPDATE ai_conversations SET updated_at=? WHERE id=?",
                (stamp(), row["conversation_id"]),
            )
            updated = db.execute("SELECT * FROM ai_messages WHERE id=?", (message_id,)).fetchone()
        return self._message(updated)

    def discard_assistant(self, message_id):
        """Remove only an empty placeholder; a partial answer is retained."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM ai_messages WHERE id=? AND role='assistant' AND content='' AND status='streaming'",
                (message_id,),
            )

    def conversation_summary(self, owner, conversation_id):
        with self.store.connect() as db:
            conversation = self._conversation(db, owner, conversation_id)
            count = db.execute(
                "SELECT count(*) FROM ai_messages WHERE conversation_id=?",
                (conversation["id"],),
            ).fetchone()[0]
        return _summary(conversation) | {"message_count": count}
