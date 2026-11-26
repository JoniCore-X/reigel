"""Session-bound privacy requests with human review and no deletion capability."""
from __future__ import annotations

from fastapi import Depends, Request

from .core import DomainError, stamp, text, uid

KINDS = {"access", "correction", "deletion"}
STATUSES = {"pending", "reviewing", "closed"}


def initialize(store):
    # Independent, additive migration: no records are rewritten or removed.
    with store.connect() as db:
        db.executescript("""
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS privacy_schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS privacy_requests(
          id TEXT PRIMARY KEY,
          conversation_id TEXT NOT NULL REFERENCES conversations(id),
          kind TEXT NOT NULL CHECK(kind IN ('access','correction','deletion')),
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','reviewing','closed')),
          details TEXT NOT NULL DEFAULT '', review_note TEXT NOT NULL DEFAULT '',
          identity_verified INTEGER NOT NULL DEFAULT 0 CHECK(identity_verified IN (0,1)),
          reviewed_by TEXT REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS privacy_open_request ON privacy_requests(conversation_id,kind) WHERE status <> 'closed';
        CREATE TABLE IF NOT EXISTS privacy_request_events(
          id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES privacy_requests(id),
          actor_id TEXT REFERENCES users(id), status TEXT NOT NULL, review_note TEXT NOT NULL,
          identity_verified INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS privacy_request_event_time ON privacy_request_events(request_id,created_at);
        INSERT OR IGNORE INTO privacy_schema_versions VALUES(1,strftime('%Y-%m-%dT%H:%M:%f+00:00','now'));
        INSERT OR IGNORE INTO privacy_schema_versions VALUES(2,strftime('%Y-%m-%dT%H:%M:%f+00:00','now'));
        COMMIT;
        """)


def create_session_request(db, session, kind, details, store):
    """Called only inside WebChat's locked, validated-session transaction."""
    if kind not in KINDS:
        raise DomainError("Tipo de solicitud de privacidad no válido.", 422)
    conversation_id = session["conversation_id"]
    existing = db.execute("SELECT * FROM privacy_requests WHERE conversation_id=? AND kind=? AND status<>'closed'", (conversation_id, kind)).fetchone()
    if existing:
        return dict(existing), False
    request_id, timestamp = uid(), stamp()
    db.execute("INSERT INTO privacy_requests(id,conversation_id,kind,details,created_at,updated_at) VALUES(?,?,?,?,?,?)",
               (request_id, conversation_id, kind, text(details, "solicitud", limit=2000), timestamp, timestamp))
    db.execute("INSERT INTO privacy_request_events VALUES(?,?,?,?,?,?,?)",
               (uid(), request_id, None, "pending", "Solicitud registrada desde la sesión del visitante; identidad pendiente de verificación.", 0, timestamp))
    store.audit(db, None, "privacy.request." + kind, request_id)
    return dict(db.execute("SELECT * FROM privacy_requests WHERE id=?", (request_id,)).fetchone()), True


def public_requests(db, conversation_id):
    return [dict(row) for row in db.execute("SELECT id,kind,status,created_at,updated_at FROM privacy_requests WHERE conversation_id=? ORDER BY created_at DESC LIMIT 20", (conversation_id,))]


def list_requests(store, actor):
    clause, args = store._scope(actor, "c")
    with store.connect() as db:
        rows = db.execute(f"""SELECT p.*,c.lead_id,c.advisor_id FROM privacy_requests p
          JOIN conversations c ON c.id=p.conversation_id WHERE {clause}
          ORDER BY p.created_at DESC LIMIT 300""", args)
        return [{**dict(row), "identity_verified": bool(row["identity_verified"])} for row in rows]


def get_request(store, request_id, actor):
    clause, args = store._scope(actor, "c")
    with store.connect() as db:
        row = db.execute(f"""SELECT p.*,c.lead_id,c.advisor_id FROM privacy_requests p
          JOIN conversations c ON c.id=p.conversation_id WHERE p.id=? AND {clause}""", (request_id, *args)).fetchone()
        if not row:
            raise DomainError("Solicitud de privacidad no encontrada.", 404)
        result = {**dict(row), "identity_verified": bool(row["identity_verified"])}
        result["history"] = [{**dict(event), "identity_verified": bool(event["identity_verified"])}
                             for event in db.execute("SELECT * FROM privacy_request_events WHERE request_id=? ORDER BY created_at DESC,rowid DESC LIMIT 100", (request_id,))]
        return result


def review_request(store, request_id, data, actor):
    store.require_admin(actor)
    if not isinstance(data, dict) or set(data) - {"status", "review_note", "identity_verified"}:
        raise DomainError("Campos de revisión no válidos.", 422)
    if not isinstance(data.get("status"), str) or data["status"] not in STATUSES:
        raise DomainError("Estado de solicitud no válido.", 422)
    note = text(data.get("review_note"), "nota de revisión", limit=3000, required=True)
    verified = data.get("identity_verified")
    if verified is not None and type(verified) is not bool:
        raise DomainError("La verificación de identidad debe ser sí o no.", 422)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM privacy_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise DomainError("Solicitud de privacidad no encontrada.", 404)
        if row["status"] == "closed":
            raise DomainError("La revisión está cerrada; conserva su trazabilidad.", 409)
        verified = bool(row["identity_verified"]) if verified is None else verified
        if data["status"] == "closed" and not verified:
            raise DomainError("Verifica la identidad y documenta la decisión antes de cerrar la revisión.", 422)
        db.execute("UPDATE privacy_requests SET status=?,review_note=?,identity_verified=?,reviewed_by=?,updated_at=? WHERE id=?",
                   (data["status"], note, int(verified), actor["id"], stamp(), request_id))
        db.execute("INSERT INTO privacy_request_events VALUES(?,?,?,?,?,?,?)",
                   (uid(), request_id, actor["id"], data["status"], note, int(verified), stamp()))
        store.audit(db, actor, "privacy.review." + data["status"], request_id)
        result = dict(db.execute("SELECT * FROM privacy_requests WHERE id=?", (request_id,)).fetchone())
        result["identity_verified"] = bool(result["identity_verified"])
        return result


def register_routes(app, actor, payload):
    @app.get("/api/privacy/requests")
    async def privacy_requests(user=Depends(actor)):
        return {"requests": list_requests(app.state.store, user), "can_review": user["role"] == "admin"}

    @app.get("/api/privacy/requests/{request_id}")
    async def privacy_detail(request_id: str, user=Depends(actor)):
        return {"request": get_request(app.state.store, request_id, user), "can_review": user["role"] == "admin"}

    @app.patch("/api/privacy/requests/{request_id}")
    async def privacy_review(request_id: str, request: Request, user=Depends(actor)):
        return {"request": review_request(app.state.store, request_id, await payload(request), user),
                "message": "Revisión administrativa guardada. Esta operación no elimina ni exporta datos."}
