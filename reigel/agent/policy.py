"""Catálogo de acciones del motor y la política que decide quién las autoriza.

Cada acción declara `outbound`: si sale hacia una persona ajena al equipo. En esta
fase ninguna acción saliente está implementada y `runtime` las rechaza, de modo
que el motor no puede enviar nada aunque la política diga lo contrario.

Modos: `auto` ejecuta sin intervención; `approval` deja la decisión registrada y
esperando a una persona; `draft` reserva el modo para cuando haya texto redactado.
"""
from __future__ import annotations

MODES = ("auto", "approval", "draft")

# task_type debe existir en operations.TASK_TYPES; effect "notify" no crea tarea.
ACTIONS: dict[str, dict] = {
    "assign_advisor": {
        "title": "Asignar asesor",
        "effect": "notify",
        "audience": "admin",
        "task_type": "",
        "base": 130.0,
        "due_hours": 4,
        "outbound": False,
        "default_mode": "auto",
    },
    "confirm_appointment": {
        "title": "Confirmar cita próxima",
        "effect": "task",
        "audience": "advisor",
        "task_type": "confirm_appointment",
        "base": 110.0,
        "due_hours": 6,
        "outbound": False,
        "default_mode": "auto",
    },
    "close_appointment": {
        "title": "Registrar el resultado de la cita",
        "effect": "task",
        "audience": "advisor",
        "task_type": "follow_up",
        "base": 105.0,
        "due_hours": 8,
        "outbound": False,
        "default_mode": "auto",
    },
    "first_contact": {
        "title": "Primer contacto",
        "effect": "task",
        "audience": "advisor",
        "task_type": "call",
        "base": 100.0,
        "due_hours": 8,
        "outbound": False,
        "default_mode": "auto",
    },
    "propose_appointment": {
        "title": "Proponer orientación",
        "effect": "task",
        "audience": "advisor",
        "task_type": "call",
        "base": 95.0,
        "due_hours": 24,
        "outbound": False,
        "default_mode": "auto",
    },
    "followup": {
        "title": "Seguimiento vencido",
        "effect": "task",
        "audience": "advisor",
        "task_type": "follow_up",
        "base": 90.0,
        "due_hours": 12,
        "outbound": False,
        "default_mode": "auto",
    },
    "prepare_proposal": {
        "title": "Preparar propuesta",
        "effect": "task",
        "audience": "advisor",
        "task_type": "review_proposal",
        "base": 85.0,
        "due_hours": 48,
        "outbound": False,
        "default_mode": "auto",
    },
    "followup_proposal": {
        "title": "Seguimiento de propuesta",
        "effect": "task",
        "audience": "advisor",
        "task_type": "follow_up",
        "base": 80.0,
        "due_hours": 24,
        "outbound": False,
        "default_mode": "auto",
    },
    "escalate_stalled": {
        "title": "Negociación detenida",
        "effect": "notify",
        "audience": "both",
        "task_type": "",
        "base": 120.0,
        "due_hours": 8,
        "outbound": False,
        "default_mode": "auto",
    },
    "review_dormant": {
        "title": "Revisar registro inactivo",
        "effect": "task",
        "audience": "advisor",
        "task_type": "follow_up",
        "base": 20.0,
        "due_hours": 72,
        "outbound": False,
        "default_mode": "approval",
    },
}

# Topes del ciclo. Protegen al equipo de una avalancha de tareas y al servidor de
# un ciclo interminable; se pueden ajustar en agent_runtime sin tocar el código.
LIMITS = {
    "max_leads_per_cycle": 300,
    "max_decisions_per_cycle": 60,
    "max_decisions_per_lead": 1,
    "interval_seconds": 300,
}


def _core():
    from .. import core
    return core


def defaults() -> dict[str, str]:
    return {name: spec["default_mode"] for name, spec in ACTIONS.items()}


def modes(db) -> dict[str, str]:
    """Modo vigente de cada acción, con el valor por defecto si no está en la tabla."""
    stored = {row["action"]: row["mode"] for row in db.execute("SELECT action,mode FROM agent_policies")}
    return {name: stored.get(name, spec["default_mode"]) for name, spec in ACTIONS.items()}


def set_mode(db, action: str, mode: str, actor=None) -> dict[str, str]:
    core = _core()
    if action not in ACTIONS:
        raise core.DomainError("Acción del motor no reconocida.", 422)
    if mode not in MODES:
        raise core.DomainError("Modo no válido: usa auto, approval o draft.", 422)
    db.execute(
        "INSERT INTO agent_policies(action,mode,max_per_day,updated_at,updated_by) VALUES(?,?,0,?,?)"
        " ON CONFLICT(action) DO UPDATE SET mode=excluded.mode,updated_at=excluded.updated_at,updated_by=excluded.updated_by",
        (action, mode, core.stamp(), actor and actor["id"]),
    )
    return modes(db)


def runtime_value(db, key: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM agent_runtime WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_runtime_value(db, key: str, value: str) -> None:
    core = _core()
    db.execute(
        "INSERT INTO agent_runtime(key,value,updated_at) VALUES(?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
        (key, value, core.stamp()),
    )


def enabled(db) -> bool:
    """El motor arranca apagado: una base nueva nunca empieza a trabajar sola."""
    return runtime_value(db, "enabled", "0") == "1"


def set_enabled(db, value: bool, actor=None) -> bool:
    set_runtime_value(db, "enabled", "1" if value else "0")
    db.execute(
        "INSERT INTO audit_events VALUES(?,?,?,?,?)",
        (_core().uid(), actor and actor["id"], "agent.enabled" if value else "agent.disabled", None, _core().stamp()),
    )
    return enabled(db)


def limits(db) -> dict[str, int]:
    result = dict(LIMITS)
    for key in result:
        raw = runtime_value(db, key)
        if raw.isdigit() and int(raw) > 0:
            result[key] = int(raw)
    return result
