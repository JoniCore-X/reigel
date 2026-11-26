"""Informe de necesidad: lo que el agente entrega al equipo cuando no puede responder.

Cuando el chat se queda sin respuesta —porque no hay evidencia verificada, porque
la respuesta no pasó los validadores, porque el modelo no contestó o porque la
persona pidió hablar con alguien—, la conversación pasa a atención humana. Un
aviso diría «hay alguien esperando». Un informe dice **qué necesita esa persona**,
qué se sabe ya de ella, qué falta por preguntar y por qué el agente se detuvo.

El informe se arma con reglas, no con el modelo. Eso es deliberado: hace falta
justo cuando el modelo falló o cuando su respuesta fue rechazada, así que no
puede depender de él. Tampoco inventa: cada línea sale de la pregunta de la
persona, de lo que ella misma contestó y del motivo del escalado.

El texto de la pregunta se guarda ya enmascarado (`learning.redact`): sin correos,
teléfonos, direcciones ni números largos.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

REASONS = {
    "no_knowledge": {"label": "Sin evidencia verificada que citar", "urgency": "normal"},
    "fallback": {"label": "El motor no supo clasificar la pregunta", "urgency": "normal"},
    "blocked_by_policy": {"label": "La respuesta no pasó los validadores", "urgency": "high"},
    "model_unavailable": {"label": "El modelo local no respondió", "urgency": "low"},
    "human_requested": {"label": "La persona pidió atención humana", "urgency": "high"},
}
# Qué necesita la persona, deducido del tema comercial que detecta `learning.topic_of`.
TOPIC_NEEDS = {
    "apagon": "Le preocupan las interrupciones del servicio.",
    "bateria": "Pregunta por baterías y respaldo.",
    "factura": "Su duda gira sobre la factura eléctrica.",
    "techo": "Su duda gira sobre el techo y dónde irían los equipos.",
    "placas": "Pregunta por los equipos.",
    "inversor": "Pregunta por el inversor.",
    "medicion": "Pregunta por la medición o el contador.",
    "contrato": "Pregunta por el contrato o las condiciones.",
    "mantenimiento": "Pregunta por el mantenimiento.",
    "instalacion": "Pregunta por cómo sería la instalación.",
    "comparar": "Está comparando opciones.",
    "general": "Tiene una duda que el motor no supo clasificar.",
}
# Datos de calificación que el chat recoge, en el orden en que los pregunta.
PROFILE_FIELDS = (
    ("municipality", "Municipio"),
    ("priority", "Qué busca resolver"),
    ("bill_amount", "Importe de la factura"),
    ("backup_loads", "Qué quiere respaldar"),
)
STATES = ("open", "claimed", "resolved")
ROUTES = ("chat", "ia", "channel")


def _core():
    from .. import core
    return core


def _error(message, status=422):
    raise _core().DomainError(message, status)


def _profile_signals(profile):
    """Lo que la persona ya contestó y lo que falta. Nada se deduce ni se completa."""
    profile = profile if isinstance(profile, dict) else {}
    known, missing = [], []
    for key, label in PROFILE_FIELDS:
        value = profile.get(key)
        if value in (None, "", []):
            missing.append(label)
            continue
        if key == "bill_amount":
            period = profile.get("bill_period")
            shown = f"{value}{' al mes' if period == 'monthly' else ''}"
        elif isinstance(value, (list, tuple)):
            shown = ", ".join(str(item) for item in value)
        else:
            shown = str(value)
        known.append({"label": label, "value": shown[:120]})
    return known, missing


def build(reason, question, *, topic=None, profile=None, route="chat", asked_next_step=False):
    """Arma el informe con reglas. Devuelve el diccionario que se guarda."""
    from ..learning import redact, topic_of

    if reason not in REASONS:
        _error("Motivo de escalado no reconocido.")
    if route not in ROUTES:
        _error("Origen no reconocido.")
    masked = redact(question)
    if not masked:
        _error("El informe necesita la pregunta de la persona.")
    detected = topic or topic_of(question)
    need = TOPIC_NEEDS.get(detected, TOPIC_NEEDS["general"])
    if reason == "human_requested":
        # Quien pide hablar con alguien no «tiene una duda sin clasificar»: pidió una
        # persona. Si además se le detecta un tema, se añade; si no, no se inventa.
        need = "Pidió hablar con una persona del equipo."
        if detected != "general":
            need += " " + TOPIC_NEEDS[detected]
    known, missing = _profile_signals(profile)
    urgency = REASONS[reason]["urgency"]
    if asked_next_step and urgency != "high":
        # Pidió el siguiente paso: la conversación estaba lista para avanzar.
        urgency = "high"
    return {
        "reason": reason, "route": route, "topic": detected,
        "question": masked,
        "need": need,
        "urgency": urgency,
        "known": known, "missing": missing,
        "asked_next_step": bool(asked_next_step),
    }


OPEN_FOR_CONVERSATION = ("SELECT * FROM agent_need_reports WHERE conversation_id=? AND topic=?"
                         " AND status<>'resolved' ORDER BY created_at DESC LIMIT 1")
ONE = "SELECT * FROM agent_need_reports WHERE id=?"
LISTED_ALL = ("SELECT n.*,c.channel,c.advisor_id,l.name lead_name FROM agent_need_reports n"
              " LEFT JOIN conversations c ON c.id=n.conversation_id"
              " LEFT JOIN leads l ON l.id=n.lead_id"
              " WHERE n.status<>'resolved' ORDER BY n.created_at DESC LIMIT ?")
LISTED_MINE = ("SELECT n.*,c.channel,c.advisor_id,l.name lead_name FROM agent_need_reports n"
               " LEFT JOIN conversations c ON c.id=n.conversation_id"
               " LEFT JOIN leads l ON l.id=n.lead_id"
               " WHERE n.status<>'resolved' AND (c.advisor_id IS NULL OR c.advisor_id=?"
               " OR n.owner_id=?) ORDER BY n.created_at DESC LIMIT ?")


def view(row):
    return {
        "id": row["id"], "conversation_id": row["conversation_id"], "lead_id": row["lead_id"],
        "lead_name": row["lead_name"] if "lead_name" in row.keys() else None,
        "channel": row["channel"] if "channel" in row.keys() else None,
        "route": row["route"], "reason": row["reason"],
        "reason_label": REASONS.get(row["reason"], {}).get("label", row["reason"]),
        "topic": row["topic"], "need": row["need"], "question": row["question"],
        "urgency": row["urgency"], "status": row["status"], "repeats": row["repeats"],
        "known": json.loads(row["known_json"] or "[]"), "missing": json.loads(row["missing_json"] or "[]"),
        "owner_id": row["owner_id"], "claimed_at": row["claimed_at"],
        "resolved_at": row["resolved_at"], "resolution": row["resolution"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def record(store, conversation_id, report, *, lead_id=None, now=None):
    """Guarda el informe. Si ya hay uno abierto por el mismo tema en esa conversación,
    no crea otro: cuenta la repetición y lo sube de urgencia."""
    core = _core()
    now = now or datetime.now(UTC)
    with store.connect() as db:
        existing = db.execute(OPEN_FOR_CONVERSATION, (conversation_id, report["topic"])).fetchone()
        if existing:
            db.execute("UPDATE agent_need_reports SET repeats=repeats+1,urgency='high',"
                       "question=?,updated_at=? WHERE id=?",
                       (report["question"], now.isoformat(), existing["id"]))
            db.execute("UPDATE agent_need_reports SET reason=? WHERE id=? AND status='open'",
                       (report["reason"], existing["id"]))
            return view(db.execute(ONE, (existing["id"],)).fetchone())
        report_id = core.uid()
        db.execute(
            "INSERT INTO agent_need_reports(id,conversation_id,lead_id,route,reason,topic,need,question,"
            "urgency,known_json,missing_json,asked_next_step,status,repeats,owner_id,claimed_at,"
            "resolved_at,resolution,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'open',1,NULL,NULL,NULL,'',?,?)",
            (report_id, conversation_id, lead_id, report["route"], report["reason"], report["topic"],
             report["need"], report["question"], report["urgency"],
             json.dumps(report["known"], ensure_ascii=False), json.dumps(report["missing"], ensure_ascii=False),
             int(report["asked_next_step"]), now.isoformat(), now.isoformat()),
        )
        store.audit(db, None, "agent.need.record", report_id)
        return view(db.execute(ONE, (report_id,)).fetchone())


def listed(store, actor, *, limit=50):
    """Un asesor ve los informes sin dueño y los suyos; administración los ve todos."""
    with store.connect() as db:
        rows = (db.execute(LISTED_ALL, (limit,)) if actor["role"] == "admin"
                else db.execute(LISTED_MINE, (actor["id"], actor["id"], limit)))
        reports = [view(row) for row in rows]
    order = {"high": 0, "normal": 1, "low": 2}
    reports.sort(key=lambda item: (order.get(item["urgency"], 1), item["created_at"]))
    return {"reports": reports, "reasons": {name: spec["label"] for name, spec in REASONS.items()},
            "notice": ("El informe se arma con reglas a partir de lo que la persona escribió y"
                       " contestó. No lo redacta el modelo y no añade nada que ella no haya dicho.")}


def _owned(db, store, report_id, actor):
    row = db.execute(ONE, (report_id,)).fetchone()
    if not row:
        _error("Ese informe no existe.", 404)
    if actor["role"] != "admin" and row["owner_id"] and row["owner_id"] != actor["id"]:
        _error("Ese informe lo está atendiendo otra persona.", 403)
    return row


def claim(store, report_id, actor, *, now=None):
    now = now or datetime.now(UTC)
    with store.connect() as db:
        row = _owned(db, store, report_id, actor)
        if row["status"] == "resolved":
            _error("Ese informe ya está cerrado.", 409)
        db.execute("UPDATE agent_need_reports SET status='claimed',owner_id=?,claimed_at=?,updated_at=? WHERE id=?",
                   (actor["id"], now.isoformat(), now.isoformat(), report_id))
        store.audit(db, actor, "agent.need.claim", report_id)
        return view(db.execute(ONE, (report_id,)).fetchone())


def resolve(store, report_id, data, actor, *, now=None):
    core = _core()
    now = now or datetime.now(UTC)
    resolution = core.text((data or {}).get("resolution"), "resultado", limit=400, required=True)
    with store.connect() as db:
        row = _owned(db, store, report_id, actor)
        if row["status"] == "resolved":
            _error("Ese informe ya está cerrado.", 409)
        db.execute("UPDATE agent_need_reports SET status='resolved',owner_id=COALESCE(owner_id,?),"
                   "resolved_at=?,resolution=?,updated_at=? WHERE id=?",
                   (actor["id"], now.isoformat(), resolution, now.isoformat(), report_id))
        store.audit(db, actor, "agent.need.resolve", report_id)
        return view(db.execute(ONE, (report_id,)).fetchone())
