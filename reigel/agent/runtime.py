"""Bucle del motor: mira la cartera, decide y ejecuta los efectos internos.

Un ciclo es atómico y repetible. Cada decisión lleva una clave de idempotencia,
así que repetir el ciclo el mismo día no duplica tareas ni avisos. El interruptor
`enabled` manda sobre todo: apagado, `tick` no escribe nada.

Lo que un ciclo puede hacer hoy: crear una tarea para el asesor asignado y un
aviso interno. Lo que no puede hacer, por diseño y no por falta de tiempo:
enviar un mensaje, marcar una llamada o cambiar la etapa de un registro. Una
acción marcada como saliente se rechaza aunque la política la autorice.

Todo el SQL es estático. Las listas de identificadores viajan como un parámetro
JSON y se expanden con `json_each`, de modo que no se construye ninguna consulta
con texto interpolado.

Una vuelta entera es una sola transacción: o queda completa o no deja rastro. Por
eso el presupuesto está acotado (300 registros y 60 decisiones), para no mantener
el bloqueo de escritura mientras alguien usa la aplicación. Un registro que falla
no tumba la vuelta: se cuenta como omitido y su motivo queda en `agent_cycles.error`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from . import policy
from .planner import TERMINAL_STAGES, evaluate

LOGGER = logging.getLogger(__name__)
TASK_PRIORITY_HIGH = 100.0
TASK_PRIORITY_NORMAL = 60.0

OPEN_LEADS = ("SELECT * FROM leads WHERE stage NOT IN (SELECT value FROM json_each(?))"
              " ORDER BY updated_at ASC LIMIT ?")
PENDING_TASKS = ("SELECT lead_id,type FROM tasks WHERE status='pending'"
                 " AND lead_id IN (SELECT value FROM json_each(?))")
NEXT_APPOINTMENTS = ("SELECT lead_id,id,start_at FROM appointments WHERE status='confirmed' AND start_at>=?"
                     " AND lead_id IN (SELECT value FROM json_each(?)) ORDER BY start_at")
LAST_ACTIVITY = ("SELECT lead_id,MAX(occurred_at) last FROM lead_activities"
                 " WHERE lead_id IN (SELECT value FROM json_each(?)) GROUP BY lead_id")


def _core():
    from .. import core
    return core


def _lead_batch(db, limit):
    """Los registros abiertos, empezando por el más desatendido."""
    return db.execute(OPEN_LEADS, (json.dumps(list(TERMINAL_STAGES)), limit)).fetchall()


def _contexts(db, leads, now):
    """Contexto de todos los registros del ciclo en tres consultas, no tres por registro."""
    ids = [lead["id"] for lead in leads]
    result = {lead_id: {"open_task_types": set(), "next_appointment_at": None,
                        "next_appointment_id": None, "last_activity_at": None} for lead_id in ids}
    if not ids:
        return result
    batch = json.dumps(ids)
    for row in db.execute(PENDING_TASKS, (batch,)):
        result[row["lead_id"]]["open_task_types"].add(row["type"])
    for row in db.execute(NEXT_APPOINTMENTS, (now.isoformat(), batch)):
        entry = result[row["lead_id"]]
        if entry["next_appointment_at"] is None:
            entry["next_appointment_at"] = row["start_at"]
            entry["next_appointment_id"] = row["id"]
    for row in db.execute(LAST_ACTIVITY, (batch,)):
        result[row["lead_id"]]["last_activity_at"] = row["last"]
    return result


def _task_priority(value):
    if value >= TASK_PRIORITY_HIGH:
        return "high"
    return "normal" if value >= TASK_PRIORITY_NORMAL else "low"


def _create_task(db, lead, decision, now):
    core = _core()
    task_id = core.uid()
    db.execute(
        "INSERT INTO tasks(id,lead_id,owner_id,type,priority,due_at,status,description,outcome,"
        "completed_at,reminder_hours,created_at,updated_at) VALUES(?,?,?,?,?,?,'pending',?,'',NULL,24,?,?)",
        (task_id, lead["id"], lead["advisor_id"], decision["task_type"],
         _task_priority(decision["priority"]), decision["due_at"],
         policy.ACTIONS[decision["action"]]["title"] + ": " + decision["reason"],
         now.isoformat(), now.isoformat()),
    )
    return task_id


def _notify(db, lead, decision, now):
    """Aviso interno, deduplicado por la propia clave de idempotencia de la decisión."""
    core = _core()
    audience = decision["audience"]
    targets = []
    if audience in ("advisor", "both") and lead["advisor_id"]:
        targets.append(lead["advisor_id"])
    if audience in ("admin", "both"):
        targets.extend(row["id"] for row in db.execute(
            "SELECT id FROM users WHERE role='admin' AND active=1"))
    title = policy.ACTIONS[decision["action"]]["title"] + ": " + lead["name"]
    for user_id in dict.fromkeys(targets):
        db.execute(
            "INSERT OR IGNORE INTO internal_notifications(id,user_id,event_key,type,title,entity_id,lead_id,read_at,created_at)"
            " VALUES(?,?,?,?,?,?,?,NULL,?)",
            (core.uid(), user_id, decision["idempotency_key"], "agent_" + decision["action"],
             title, lead["id"], lead["id"], now.isoformat()),
        )
    return lead["id"]


def preview(store, *, now=None, limit=50):
    """Qué decidiría el motor ahora mismo, sin escribir nada. Para revisar antes de encender."""
    now = now or datetime.now(UTC)
    with store.connect() as db:
        leads = _lead_batch(db, limit)
        contexts = _contexts(db, leads, now)
        modes = policy.modes(db)
        rows = []
        for lead in leads:
            for decision in evaluate(lead, contexts[lead["id"]], now)[:1]:
                rows.append({**decision, "lead_id": lead["id"], "lead_name": lead["name"],
                             "stage": lead["stage"], "mode": modes[decision["action"]]})
        rows.sort(key=lambda row: -row["priority"])
        return {"enabled": policy.enabled(db), "generated_at": now.isoformat(),
                "leads_seen": len(leads), "decisions": rows}


def tick(store, *, now=None, trigger="manual", actor=None):
    """Un ciclo completo. Devuelve el resumen y lo deja registrado en agent_cycles."""
    core = _core()
    now = now or datetime.now(UTC)
    with store.connect() as db:
        if not policy.enabled(db):
            return {"status": "disabled", "cycle_id": None, "leads_seen": 0,
                    "decided": 0, "executed": 0, "held": 0, "skipped": 0}
        limits = policy.limits(db)
        modes = policy.modes(db)
        cycle_id = core.uid()
        db.execute("INSERT INTO agent_cycles(id,trigger,started_at) VALUES(?,?,?)",
                   (cycle_id, trigger, now.isoformat()))
        leads = _lead_batch(db, limits["max_leads_per_cycle"])
        contexts = _contexts(db, leads, now)
        counts = {"decided": 0, "executed": 0, "held": 0, "skipped": 0}
        problem = ""
        for lead in leads:
            if counts["decided"] >= limits["max_decisions_per_cycle"]:
                break
            try:
                chosen = evaluate(lead, contexts[lead["id"]], now)[:limits["max_decisions_per_lead"]]
            except Exception as failure:  # noqa: BLE001 - un registro con datos raros no tumba la vuelta
                LOGGER.exception("El motor no pudo decidir sobre un registro")
                counts["skipped"] += 1
                problem = problem or str(failure)[:200]
                continue
            for decision in chosen:
                if decision["outbound"]:
                    # Defensa en profundidad: ninguna acción saliente se ejecuta aquí.
                    LOGGER.warning("El motor omitió una acción saliente: %s", decision["action"])
                    counts["skipped"] += 1
                    continue
                if decision["effect"] == "task" and not lead["advisor_id"]:
                    # Una tarea necesita responsable. Sin asesor, el planificador ya
                    # devuelve «asignar asesor»; esto cubre una regla futura mal escrita.
                    LOGGER.warning("Tarea sin responsable omitida: %s", decision["action"])
                    counts["skipped"] += 1
                    continue
                mode = modes[decision["action"]]
                inserted = db.execute(
                    "INSERT OR IGNORE INTO agent_decisions(id,cycle_id,lead_id,advisor_id,action,reason,"
                    "priority,mode,status,effect,entity_id,due_at,idempotency_key,decided_at,resolved_at)"
                    " VALUES(?,?,?,?,?,?,?,?,'planned',?,NULL,?,?,?,NULL)",
                    (core.uid(), cycle_id, lead["id"], lead["advisor_id"], decision["action"],
                     decision["reason"], decision["priority"], mode, decision["effect"],
                     decision["due_at"], decision["idempotency_key"], now.isoformat()),
                ).rowcount
                if not inserted:
                    # Ya se decidió lo mismo antes: el motor no repite trabajo.
                    counts["skipped"] += 1
                    continue
                counts["decided"] += 1
                if mode != "auto":
                    counts["held"] += 1
                    continue
                entity_id = (_create_task(db, lead, decision, now) if decision["effect"] == "task"
                             else _notify(db, lead, decision, now))
                db.execute(
                    "UPDATE agent_decisions SET status='executed',entity_id=?,resolved_at=? WHERE idempotency_key=?",
                    (entity_id, now.isoformat(), decision["idempotency_key"]),
                )
                counts["executed"] += 1
        db.execute(
            "UPDATE agent_cycles SET finished_at=?,leads_seen=?,decided=?,executed=?,held=?,skipped=?,error=? WHERE id=?",
            (core.stamp(), len(leads), counts["decided"], counts["executed"],
             counts["held"], counts["skipped"], problem, cycle_id),
        )
        store.audit(db, actor, "agent.cycle", cycle_id)
        return {"status": "ran", "cycle_id": cycle_id, "leads_seen": len(leads), **counts}


async def loop(store, *, interval=None):
    """Bucle de fondo. Cada vuelta vuelve a leer el interruptor, así que apagarlo surte efecto."""
    while True:
        wait = interval or policy.LIMITS["interval_seconds"]
        try:
            if interval is None:
                with store.connect() as db:
                    wait = policy.limits(db)["interval_seconds"]
            await asyncio.to_thread(tick, store, trigger="tick")
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("El ciclo del motor comercial falló")
        await asyncio.sleep(wait)
