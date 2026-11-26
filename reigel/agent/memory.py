"""Memoria del agente sobre cada cliente: creencias con procedencia y vencimiento.

El encargo pedía que el agente pudiera modificar su memoria interna a voluntad. Un
registro que se sobrescribe deriva: acumula afirmaciones sin fuente que alimentan
las siguientes y acaban en una promesa falsa a una persona real. Aquí el agente
escribe todo lo que observa, sin pedir permiso, y lo que está acotado es **qué
creencia puede usar al hablar con un cliente**.

Cuatro reglas, y todo lo demás sale de ellas:

1. **Nada se sobrescribe.** Una revisión inserta una fila nueva y marca la anterior
   como sustituida. La historia queda completa y se puede auditar.
2. **Toda creencia declara de dónde viene.** Lo que dijo la persona, lo que escribió
   el equipo, un dato del propio registro, una fuente verificada o una deducción del
   modelo. La procedencia decide si puede usarse al hablar.
3. **Una deducción del modelo nunca se usa con un cliente hasta que alguien la
   aprueba.** Es la diferencia entre recordar y suponer.
4. **Todo vence.** Cada procedencia trae su plazo: lo que alguien dijo hace ocho
   meses dejó de ser un hecho. Una creencia vencida se sigue leyendo en el historial,
   pero no se usa.

`speaking_context` es la única puerta por la que la memoria llega a un texto dirigido
a un cliente, y solo deja pasar lo vigente, no sustituido y usable.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

# Procedencias. `usable` dice si sirve para hablar con un cliente sin aprobación.
SOURCES = {
    "lead_said": {"usable": True, "ttl_days": 180, "label": "La persona lo dijo"},
    "team_entered": {"usable": True, "ttl_days": 365, "label": "El equipo lo registró"},
    "record": {"usable": True, "ttl_days": 90, "label": "Dato del propio registro"},
    "verified": {"usable": True, "ttl_days": 30, "label": "Fuente verificada"},
    "inferred": {"usable": False, "ttl_days": 30, "label": "Deducción del modelo"},
}
# Asuntos sobre los que el agente puede recordar algo. Uno por creencia vigente:
# una creencia nueva sobre el mismo asunto sustituye a la anterior.
SUBJECTS = {
    "vivienda": "Tipo de vivienda",
    "consumo": "Consumo o factura",
    "motivo": "Qué busca resolver",
    "objecion": "Objeción expresada",
    "decisor": "Quién decide",
    "plazo": "Cuándo quiere resolverlo",
    "contacto": "Cómo prefiere que le hablen",
    "historial": "Qué se le ha hecho antes",
    "otro": "Otro dato del seguimiento",
}
CLAIM_LIMIT = 400
STATES = ("active", "retracted", "superseded", "expired")


def _core():
    from .. import core
    return core


def _error(message, status=422):
    raise _core().DomainError(message, status)


def _moment(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def state_of(row, now):
    if row["retracted_at"]:
        return "retracted"
    if row["superseded_by"]:
        return "superseded"
    expires = _moment(row["expires_at"])
    return "expired" if expires and expires <= now else "active"


def usable(row, now):
    """Una creencia solo se usa al hablar si está vigente y su procedencia lo permite
    (o alguien la aprobó expresamente)."""
    if state_of(row, now) != "active":
        return False
    return bool(SOURCES.get(row["source_kind"], {}).get("usable") or row["approved_at"])


def view(row, now=None):
    now = now or datetime.now(UTC)
    source = SOURCES.get(row["source_kind"], {})
    return {
        "id": row["id"], "lead_id": row["lead_id"], "subject": row["subject"],
        "subject_label": SUBJECTS.get(row["subject"], row["subject"]),
        "claim": row["claim"], "source_kind": row["source_kind"],
        "source_label": source.get("label", row["source_kind"]),
        "source_ref": row["source_ref"], "confidence": row["confidence"],
        "observed_at": row["observed_at"], "expires_at": row["expires_at"],
        "superseded_by": row["superseded_by"], "supersedes": row["supersedes"],
        "approved_at": row["approved_at"], "approved_by": row["approved_by"],
        "retracted_at": row["retracted_at"], "retracted_reason": row["retracted_reason"],
        "state": state_of(row, now), "usable": usable(row, now),
    }


FIELDS = {"subject", "claim", "source_kind", "source_ref", "confidence"}


def _validate(data):
    core = _core()
    if not isinstance(data, dict) or set(data) - FIELDS:
        _error("La creencia requiere un asunto, una afirmación y su procedencia.")
    subject = core.text(data.get("subject"), "asunto", limit=40, required=True)
    if subject not in SUBJECTS:
        _error("Asunto no reconocido para la memoria del agente.")
    claim = core.text(data.get("claim"), "afirmación", limit=CLAIM_LIMIT, required=True)
    source_kind = core.text(data.get("source_kind"), "procedencia", limit=40, required=True)
    if source_kind not in SOURCES:
        _error("Procedencia no reconocida.")
    confidence = data.get("confidence", 1.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        _error("La confianza debe ser un número entre cero y uno.")
    if not 0 < confidence <= 1:
        _error("La confianza debe ser un número entre cero y uno.")
    return subject, claim, source_kind, confidence, core.text(data.get("source_ref"), "origen", limit=100)


# Una creencia retirada no se enlaza con la nueva: se retiró, no se corrigió.
CURRENT = ("SELECT * FROM agent_beliefs WHERE lead_id=? AND subject=? AND superseded_by IS NULL"
           " AND retracted_at IS NULL ORDER BY observed_at DESC LIMIT 1")
HISTORY = "SELECT * FROM agent_beliefs WHERE lead_id=? ORDER BY observed_at DESC,rowid DESC"
ONE = "SELECT * FROM agent_beliefs WHERE id=?"


def record(store, lead_id, data, actor=None, *, now=None):
    """Guarda una creencia. Si ya había otra vigente sobre el mismo asunto, la sustituye
    sin borrarla: queda enlazada desde la nueva y legible en el historial."""
    core = _core()
    now = now or datetime.now(UTC)
    subject, claim, source_kind, confidence, source_ref = _validate(data)
    belief_id = core.uid()
    expires = (now + timedelta(days=SOURCES[source_kind]["ttl_days"])).isoformat()
    with store.connect() as db:
        store._lead(db, lead_id, actor)
        previous = db.execute(CURRENT, (lead_id, subject)).fetchone()
        db.execute(
            "INSERT INTO agent_beliefs(id,lead_id,subject,claim,source_kind,source_ref,confidence,"
            "observed_at,expires_at,supersedes,superseded_by,approved_by,approved_at,"
            "retracted_at,retracted_reason,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,'',?)",
            (belief_id, lead_id, subject, claim, source_kind, source_ref, confidence,
             now.isoformat(), expires, previous["id"] if previous else None, core.stamp()),
        )
        if previous:
            db.execute("UPDATE agent_beliefs SET superseded_by=? WHERE id=?", (belief_id, previous["id"]))
        store.audit(db, actor, "agent.memory.record", belief_id)
        return view(db.execute(ONE, (belief_id,)).fetchone(), now)


def history(store, lead_id, actor, *, now=None):
    """Todo lo que el agente ha creído sobre este registro, lo vigente y lo sustituido."""
    now = now or datetime.now(UTC)
    with store.connect() as db:
        store._lead(db, lead_id, actor)
        rows = [view(row, now) for row in db.execute(HISTORY, (lead_id,))]
    return {
        "beliefs": rows,
        "usable": [row for row in rows if row["usable"]],
        "subjects": SUBJECTS,
        "sources": {name: spec["label"] for name, spec in SOURCES.items()},
        "notice": ("Una deducción del modelo no se usa al hablar con un cliente hasta que"
                   " alguien la aprueba. Nada se borra: lo antiguo queda sustituido."),
    }


def speaking_context(store, lead_id, *, now=None, limit=12):
    """La única puerta por la que la memoria llega a un texto dirigido a un cliente.

    Devuelve solo creencias vigentes, no sustituidas y usables. Sin actor: la llama el
    propio sistema al preparar una respuesta, después de que el acceso ya se autorizó.
    """
    now = now or datetime.now(UTC)
    with store.connect() as db:
        rows = [view(row, now) for row in db.execute(HISTORY, (lead_id,))]
    allowed = [row for row in rows if row["usable"]]
    allowed.sort(key=lambda row: (-row["confidence"], row["observed_at"]))
    return allowed[:limit]


def approve(store, belief_id, actor, *, now=None):
    """Una persona autoriza usar una deducción del modelo al hablar con el cliente."""
    core = _core()
    now = now or datetime.now(UTC)
    with store.connect() as db:
        row = db.execute(ONE, (belief_id,)).fetchone()
        if not row:
            _error("Esa creencia no existe.", 404)
        store._lead(db, row["lead_id"], actor)
        if state_of(row, now) != "active":
            _error("Solo se aprueba una creencia vigente.", 409)
        db.execute("UPDATE agent_beliefs SET approved_by=?,approved_at=? WHERE id=?",
                   (actor["id"], now.isoformat(), belief_id))
        store.audit(db, actor, "agent.memory.approve", belief_id)
        return view(db.execute(ONE, (belief_id,)).fetchone(), now)


def retract(store, belief_id, data, actor, *, now=None):
    """Retirar una creencia: deja de usarse y de contar como vigente, y no se borra.

    No es una solicitud de eliminación de datos: eso vive en `privacy.py`, con revisión
    humana, y tampoco borra registros.
    """
    core = _core()
    now = now or datetime.now(UTC)
    reason = core.text((data or {}).get("reason"), "motivo", limit=200, required=True)
    with store.connect() as db:
        row = db.execute(ONE, (belief_id,)).fetchone()
        if not row:
            _error("Esa creencia no existe.", 404)
        store._lead(db, row["lead_id"], actor)
        if state_of(row, now) != "active":
            _error("Solo se retira una creencia vigente.", 409)
        db.execute("UPDATE agent_beliefs SET retracted_at=?,retracted_reason=? WHERE id=?",
                   (now.isoformat(), reason, belief_id))
        store.audit(db, actor, "agent.memory.retract", belief_id)
        return view(db.execute(ONE, (belief_id,)).fetchone(), now)
