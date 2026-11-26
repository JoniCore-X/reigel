"""Decisión por registro: qué conviene hacer ahora y por qué.

Función pura y determinista. No lee la base, no escribe nada y no llama a ningún
modelo: recibe el registro y su contexto, y devuelve las acciones candidatas
ordenadas por prioridad. Así cada decisión del motor es reproducible y se puede
probar sin servidor, y una respuesta del modelo nunca puede cambiar la política.

La prioridad combina tres cosas: el peso de la acción (`policy.ACTIONS`), el
retraso acumulado y el valor que el equipo registró en la oportunidad. No se
inventa ninguna cifra: `opportunity_value` y `monthly_bill` los escribe el equipo.
"""
from __future__ import annotations

from datetime import UTC, datetime

from .policy import ACTIONS

# El motor no toca un registro cerrado: ni para insistir ni para reactivarlo.
TERMINAL_STAGES = ("ganado", "perdido")
# Silencio que convierte un registro en candidato a revisión.
DORMANT_DAYS = 30
NO_NEXT_STEP_DAYS = 2
PROPOSAL_SILENCE_DAYS = 3
NEGOTIATION_SILENCE_DAYS = 5
# Una cita se confirma cuando está dentro de esta ventana.
CONFIRM_WINDOW_HOURS = 48


def _field(lead, name, default=None):
    """Lee una columna tanto de un dict como de un sqlite3.Row."""
    try:
        value = lead[name]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def _moment(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _hours_since(value, now):
    moment = _moment(value)
    return None if moment is None else (now - moment).total_seconds() / 3600


def _hours_until(value, now):
    hours = _hours_since(value, now)
    return None if hours is None else -hours


def _opportunity_bonus(lead):
    """Peso del dinero que el equipo anotó, nunca una estimación del motor."""
    value = _field(lead, "opportunity_value")
    if isinstance(value, (int, float)) and value > 0:
        return min(float(value), 50000.0) / 50000.0 * 15.0
    bill = _field(lead, "monthly_bill")
    if isinstance(bill, (int, float)) and bill > 0:
        return min(float(bill), 500.0) / 500.0 * 10.0
    return 0.0


def _candidate(action, reason, now, *, delay_hours=0.0, lead=None, bucket=""):
    spec = ACTIONS[action]
    priority = spec["base"] + min(max(delay_hours, 0.0) / 24.0, 30.0) + _opportunity_bonus(lead or {})
    due = now.timestamp() + spec["due_hours"] * 3600
    return {
        "action": action,
        "reason": reason,
        "priority": round(priority, 3),
        "effect": spec["effect"],
        "task_type": spec["task_type"],
        "audience": spec["audience"],
        "outbound": spec["outbound"],
        "due_at": datetime.fromtimestamp(due, UTC).isoformat(),
        "idempotency_key": f"{action}:{_field(lead or {}, 'id', '-')}:{bucket or now.date().isoformat()}",
    }


def evaluate(lead, context=None, now=None) -> list[dict]:
    """Acciones candidatas para un registro, de mayor a menor prioridad.

    `context` admite: `open_task_types` (tipos de tarea pendientes del asesor),
    `next_appointment_at` y `next_appointment_id` (la próxima cita confirmada) y
    `last_activity_at` (la última actividad registrada).
    """
    context = context or {}
    now = now or datetime.now(UTC)
    stage = str(_field(lead, "stage", ""))
    if stage in TERMINAL_STAGES:
        return []

    open_tasks = set(context.get("open_task_types") or ())
    appointment_at = context.get("next_appointment_at")
    appointment_id = context.get("next_appointment_id")
    last_touch = _field(lead, "last_contact_at") or context.get("last_activity_at") or _field(lead, "created_at")
    quiet_hours = _hours_since(last_touch, now) or 0.0
    candidates = []

    # Sin asesor no hay a quién asignarle una tarea: lo primero es repartirlo.
    if not _field(lead, "advisor_id"):
        candidates.append(_candidate(
            "assign_advisor", "El registro no tiene asesor asignado.", now,
            delay_hours=quiet_hours, lead=lead))
        return candidates

    # Una cita próxima manda sobre todo lo demás: es la única acción con reloj.
    hours_to_appointment = _hours_until(appointment_at, now)
    if hours_to_appointment is not None and 0 <= hours_to_appointment <= CONFIRM_WINDOW_HOURS:
        candidates.append(_candidate(
            "confirm_appointment",
            f"Cita dentro de {int(hours_to_appointment)} horas, sin confirmar.", now,
            lead=lead, bucket=str(appointment_id or "cita")))

    if stage == "nuevo":
        candidates.append(_candidate(
            "first_contact", "Registro nuevo sin contacto.", now, delay_hours=quiet_hours, lead=lead))
    elif stage in ("contacto_pendiente", "contactado"):
        overdue = _hours_since(_field(lead, "next_followup_at"), now)
        if overdue is not None and overdue >= 0:
            candidates.append(_candidate(
                "followup", f"Seguimiento vencido hace {int(overdue / 24)} días.", now,
                delay_hours=overdue, lead=lead))
        elif overdue is None and NO_NEXT_STEP_DAYS * 24 <= quiet_hours < DORMANT_DAYS * 24:
            # Nadie programó el próximo paso: el registro se queda quieto sin que nada avise.
            # Pasado el silencio largo manda `review_dormant`, que pide aprobación: no se
            # llena la agenda del asesor con registros viejos sin que alguien lo decida.
            candidates.append(_candidate(
                "followup", f"Contactado hace {int(quiet_hours / 24)} días y sin próximo paso programado.", now,
                delay_hours=quiet_hours, lead=lead))
    elif stage == "calificado":
        if hours_to_appointment is None:
            candidates.append(_candidate(
                "propose_appointment", "Registro calificado sin cita.", now,
                delay_hours=quiet_hours, lead=lead))
    elif stage == "cita":
        # La etapa dice que hay cita. Sin una cita confirmada por delante, o ya
        # ocurrió sin registrar su resultado o desapareció: lo mira una persona.
        if hours_to_appointment is None:
            candidates.append(_candidate(
                "close_appointment", "La etapa indica cita, pero no hay ninguna confirmada por delante.", now,
                delay_hours=quiet_hours, lead=lead))
    elif stage in ("cita_realizada", "propuesta_preparacion"):
        candidates.append(_candidate(
            "prepare_proposal", "Cita realizada y propuesta pendiente.", now,
            delay_hours=quiet_hours, lead=lead))
    elif stage == "propuesta_presentada":
        if quiet_hours >= PROPOSAL_SILENCE_DAYS * 24:
            candidates.append(_candidate(
                "followup_proposal", f"Propuesta presentada sin respuesta hace {int(quiet_hours / 24)} días.", now,
                delay_hours=quiet_hours, lead=lead))
    elif stage == "negociacion":
        if quiet_hours >= NEGOTIATION_SILENCE_DAYS * 24:
            candidates.append(_candidate(
                "escalate_stalled", f"Negociación sin movimiento hace {int(quiet_hours / 24)} días.", now,
                delay_hours=quiet_hours, lead=lead))

    if quiet_hours >= DORMANT_DAYS * 24:
        candidates.append(_candidate(
            "review_dormant", f"Sin actividad hace {int(quiet_hours / 24)} días.", now,
            delay_hours=quiet_hours, lead=lead))

    # Si el asesor ya tiene pendiente ese tipo de tarea, el motor no insiste.
    candidates = [c for c in candidates if not (c["effect"] == "task" and c["task_type"] in open_tasks)]
    return sorted(candidates, key=lambda c: (-c["priority"], c["action"]))
