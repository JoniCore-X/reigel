"""Preparación y cierre de llamadas. El sistema no marca: marca una persona.

Esto es deliberado y no es falta de tiempo. La FCC declaró en febrero de 2024 que
una voz generada por IA es voz «artificial» bajo la TCPA: una llamada comercial así
a un número sin consentimiento previo expreso por escrito es ilegal, y Puerto Rico
se rige por la ley federal. Lo que sí se puede construir, y es donde está casi todo
el valor, son las dos puntas: llegar a la llamada sabiendo qué decir y con qué
permiso, y que lo hablado vuelva al sistema.

Tres piezas:

1. **Permiso.** Un registro de constancias, solo de inserción: quién la recogió,
   cuándo y de qué tipo. «No llamar» es una constancia más, y la última manda. Sin
   ninguna, se cae al permiso general de la ficha, y el plan lo dice con todas las
   letras: no es lo mismo una autorización escrita que una casilla marcada en el CRM.
2. **Plan.** Se arma con reglas a partir de la ficha, de la memoria del agente y de
   los informes de necesidad abiertos. Nada lo redacta un modelo.
3. **Cierre.** El resultado entra por `store.create_activity`, que ya actualiza el
   último contacto; «no llamar» deja su constancia en el mismo acto.
"""
from __future__ import annotations

from datetime import UTC, datetime

# Constancias que autorizan una llamada, de la más fuerte a la más débil.
CONSENT_KINDS = {
    "written": {"label": "Autorización escrita", "strength": 3, "allows": True},
    "web_form": {"label": "Formulario del sitio", "strength": 2, "allows": True},
    "inbound_request": {"label": "La persona pidió que la llamaran", "strength": 2, "allows": True},
    "verbal": {"label": "Autorización verbal registrada", "strength": 1, "allows": True},
    "do_not_call": {"label": "Pidió no recibir llamadas", "strength": 4, "allows": False},
}
RESULTS = {
    "reached": {"label": "Habló con la persona", "contacted": True},
    "voicemail": {"label": "Buzón de voz", "contacted": False},
    "no_answer": {"label": "No contestó", "contacted": False},
    "callback": {"label": "Pidió que la llamaran luego", "contacted": True},
    "refused": {"label": "No quiere continuar ahora", "contacted": True},
    "wrong_number": {"label": "Número equivocado", "contacted": False},
    "do_not_call": {"label": "Pidió no recibir más llamadas", "contacted": True},
}
# Lo que no se dice en una llamada, venga de donde venga la pregunta.
NEVER_SAY = (
    "Precios, cuotas o importes de cualquier tipo.",
    "Ahorro, porcentajes de reducción o independencia de la red.",
    "Aprobación de financiación o condiciones de crédito.",
    "Garantías, plazos de instalación o disponibilidad de equipos.",
    "Que una cita queda confirmada sin su referencia.",
)
PURPOSES = {
    "nuevo": "Presentarse, confirmar que la persona pidió información y entender qué busca.",
    "contacto_pendiente": "Retomar el contacto y acordar un próximo paso concreto.",
    "contactado": "Avanzar: entender la necesidad y proponer una orientación.",
    "calificado": "Proponer una orientación y coordinar fecha.",
    "cita": "Confirmar la cita ya reservada y qué hace falta tener a mano.",
    "cita_realizada": "Recoger lo que quedó pendiente de la orientación.",
    "propuesta_preparacion": "Avisar de que la propuesta está en preparación y confirmar datos.",
    "propuesta_presentada": "Escuchar dudas sobre la propuesta presentada.",
    "negociacion": "Entender qué falta para decidir y quién más participa.",
}
DEFAULT_PURPOSE = "Entender en qué puede ayudar el equipo y acordar un próximo paso."

CONSENT_HISTORY = "SELECT * FROM agent_call_consent WHERE lead_id=? ORDER BY captured_at DESC,rowid DESC"
OPEN_NEEDS = ("SELECT n.need,n.question,n.urgency FROM agent_need_reports n"
              " JOIN conversations c ON c.id=n.conversation_id"
              " WHERE n.status<>'resolved' AND (n.lead_id=? OR c.lead_id=?) ORDER BY n.created_at DESC LIMIT 5")
NEXT_APPOINTMENT = ("SELECT start_at,advisor_id FROM appointments WHERE lead_id=? AND status='confirmed'"
                    " AND start_at>=? ORDER BY start_at LIMIT 1")


def _core():
    from .. import core
    return core


def _error(message, status=422):
    raise _core().DomainError(message, status)


def _consent_view(row):
    spec = CONSENT_KINDS.get(row["kind"], {})
    return {"id": row["id"], "kind": row["kind"], "label": spec.get("label", row["kind"]),
            "allows": bool(spec.get("allows")), "evidence": row["evidence"],
            "captured_at": row["captured_at"], "captured_by": row["captured_by"]}


def permission(store, lead_id, actor=None):
    """¿Se puede llamar, y con qué respaldo? La constancia más reciente manda."""
    with store.connect() as db:
        lead = store._lead(db, lead_id, actor)
        rows = [_consent_view(row) for row in db.execute(CONSENT_HISTORY, (lead_id,))]
    latest = rows[0] if rows else None
    if latest and not latest["allows"]:
        return {"allowed": False, "basis": latest["kind"], "basis_label": latest["label"],
                "since": latest["captured_at"], "history": rows,
                "notice": "Esta persona pidió no recibir llamadas. No la llames aunque la ficha tenga permiso general."}
    if latest:
        return {"allowed": True, "basis": latest["kind"], "basis_label": latest["label"],
                "since": latest["captured_at"], "history": rows,
                "notice": "Hay constancia específica para llamadas. Revisa que siga vigente."}
    if lead.get("consent"):
        return {"allowed": True, "basis": "lead_consent", "basis_label": "Permiso general de la ficha",
                "since": lead.get("created_at"), "history": rows,
                "notice": ("Solo hay el permiso general del registro, no una constancia específica para"
                           " llamadas. Si la llamada es comercial, conviene registrar la autorización.")}
    return {"allowed": False, "basis": "none", "basis_label": "Sin permiso registrado",
            "since": None, "history": rows,
            "notice": "El registro no tiene autorización de contacto. Verifícala antes de llamar."}


def record_consent(store, lead_id, data, actor, *, now=None):
    """Deja constancia de un permiso o de una negativa. No se sobrescribe ninguna anterior."""
    core = _core()
    now = now or datetime.now(UTC)
    if not isinstance(data, dict) or set(data) - {"kind", "evidence"}:
        _error("La constancia requiere un tipo y su evidencia.")
    kind = core.text(data.get("kind"), "tipo", limit=40, required=True)
    if kind not in CONSENT_KINDS:
        _error("Tipo de constancia no reconocido.")
    evidence = core.text(data.get("evidence"), "evidencia", limit=400, required=True)
    with store.connect() as db:
        store._lead(db, lead_id, actor)
        consent_id = core.uid()
        db.execute("INSERT INTO agent_call_consent(id,lead_id,kind,evidence,captured_at,captured_by,created_at)"
                   " VALUES(?,?,?,?,?,?,?)",
                   (consent_id, lead_id, kind, evidence, now.isoformat(), actor["id"], core.stamp()))
        store.audit(db, actor, "agent.call.consent", consent_id)
    return permission(store, lead_id, actor)


LAST_REFUSAL = ("SELECT id FROM agent_call_consent WHERE lead_id=? AND kind='do_not_call'"
                " ORDER BY captured_at DESC LIMIT 1")


def record_refusal(store, lead_id, evidence, *, now=None):
    """La persona misma rechazó la llamada por escrito en una conversación.

    No hay actor: no lo registra nadie del equipo, lo pidió ella. Va sin permisos
    porque en un sentido solo restringe —nunca habilita una llamada— y la última
    constancia manda, así que una negativa automática no puede abrir una puerta.
    Si la más reciente ya es una negativa, no se apila otra igual.
    """
    core = _core()
    now = now or datetime.now(UTC)
    evidence = core.text(evidence, "evidencia", limit=400, required=True)
    with store.connect() as db:
        if not db.execute("SELECT 1 FROM leads WHERE id=?", (lead_id,)).fetchone():
            return None
        latest = db.execute(CONSENT_HISTORY, (lead_id,)).fetchone()
        if latest and latest["kind"] == "do_not_call":
            return None
        consent_id = core.uid()
        db.execute("INSERT INTO agent_call_consent(id,lead_id,kind,evidence,captured_at,captured_by,created_at)"
                   " VALUES(?,?,'do_not_call',?,?,NULL,?)",
                   (consent_id, lead_id, evidence, now.isoformat(), core.stamp()))
        store.audit(db, None, "agent.call.refusal", consent_id)
    return consent_id


def _known_and_missing(lead):
    """Los valores viajan como están guardados y con su tipo: darles formato de
    pantalla es trabajo del frontend, que conoce la zona horaria y la moneda."""
    fields = (("municipality", "Municipio", "text"), ("interest", "Interés registrado", "text"),
              ("monthly_kwh", "Consumo mensual (kWh)", "number"),
              ("monthly_bill", "Importe de la factura", "currency"))
    known, missing = [], []
    for key, label, kind in fields:
        value = lead.get(key)
        if value in (None, "", 0):
            missing.append(label)
        else:
            known.append({"label": label, "value": value, "kind": kind})
    return known, missing


def plan(store, lead_id, actor, *, now=None):
    """El plan de la llamada: con qué permiso, para qué, qué se sabe y qué preguntar.

    Se arma con reglas. Ningún modelo participa: el asesor necesita poder fiarse de
    esta hoja aunque Ollama esté apagado.
    """
    from .memory import speaking_context

    now = now or datetime.now(UTC)
    with store.connect() as db:
        lead = store._lead(db, lead_id, actor)
        needs = [{"need": row["need"], "question": row["question"], "urgency": row["urgency"]}
                 for row in db.execute(OPEN_NEEDS, (lead_id, lead_id))]
        appointment = db.execute(NEXT_APPOINTMENT, (lead_id, now.isoformat())).fetchone()
    allowed = permission(store, lead_id, actor)
    known, missing = _known_and_missing(lead)
    remembered = [{"claim": item["claim"], "subject": item["subject_label"], "source": item["source_label"]}
                  for item in speaking_context(store, lead_id, now=now)]
    ask = list(missing)
    if not lead.get("next_followup_at"):
        ask.append("Cuándo le viene bien retomar el contacto")
    confirm = [f"Lo que quedó sin responder en el chat: {item['question']}" for item in needs]
    return {
        "lead_id": lead["id"], "lead_name": lead["name"], "stage": lead["stage"],
        "phone_on_file": bool(lead.get("phone")),
        "permission": allowed,
        # El instante va en bruto; la pantalla lo muestra en la zona del equipo.
        "appointment_at": appointment["start_at"] if appointment else None,
        "purpose": PURPOSES.get(lead["stage"], DEFAULT_PURPOSE),
        "known": known, "ask": ask, "confirm": confirm,
        "remembered": remembered, "open_needs": needs,
        "never_say": list(NEVER_SAY),
        "notice": ("Esta hoja la prepara el sistema con reglas; la llamada la hace una persona."
                   " R.E.I.G.E.L. no marca, no deja mensajes grabados y no habla por teléfono."),
    }


def record_outcome(store, lead_id, data, actor, *, now=None):
    """Cierra la llamada: deja la actividad, el próximo paso y, si toca, el «no llamar»."""
    core = _core()
    now = now or datetime.now(UTC)
    if not isinstance(data, dict) or set(data) - {"result", "notes", "next_followup_at"}:
        _error("El cierre requiere el resultado y lo que se habló.")
    result = core.text(data.get("result"), "resultado", limit=40, required=True)
    if result not in RESULTS:
        _error("Resultado de llamada no reconocido.")
    notes = core.text(data.get("notes"), "notas", limit=1500, required=True)
    follow_up = data.get("next_followup_at")
    label = RESULTS[result]["label"]
    activity = store.create_activity(
        lead_id, {"type": "call", "description": "Llamada del equipo: " + label, "outcome": notes}, actor)
    if result == "do_not_call":
        record_consent(store, lead_id, {"kind": "do_not_call", "evidence": notes}, actor, now=now)
    if follow_up:
        store.update_lead(lead_id, {"next_followup_at": follow_up}, actor)
    with store.connect() as db:
        store.audit(db, actor, "agent.call.outcome", activity["id"])
    return {"activity": activity, "result": result, "result_label": label,
            "permission": permission(store, lead_id, actor)}
