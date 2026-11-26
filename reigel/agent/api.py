"""Rutas del motor. Control reservado a administración; lectura según permisos.

Un asesor ve únicamente las decisiones de sus registros, igual que en el resto de
la aplicación. Encender el motor, cambiar la política o forzar un ciclo son
acciones de administración y quedan en la auditoría.
"""
from __future__ import annotations

from fastapi import Depends, Request

from . import calls, memory, needs, policy, runtime
from ..core import DomainError

CYCLES = ("SELECT id,trigger,started_at,finished_at,leads_seen,decided,executed,held,skipped,error"
          " FROM agent_cycles ORDER BY started_at DESC LIMIT ?")
DECISIONS_ALL = ("SELECT d.*,l.name lead_name,l.stage FROM agent_decisions d JOIN leads l ON l.id=d.lead_id"
                 " ORDER BY d.decided_at DESC,d.priority DESC LIMIT ?")
DECISIONS_MINE = ("SELECT d.*,l.name lead_name,l.stage FROM agent_decisions d JOIN leads l ON l.id=d.lead_id"
                  " WHERE l.advisor_id=? ORDER BY d.decided_at DESC,d.priority DESC LIMIT ?")
PENDING_COUNT = "SELECT status,COUNT(*) total FROM agent_decisions GROUP BY status"


def _state(store):
    with store.connect() as db:
        return {
            "enabled": policy.enabled(db),
            "modes": policy.modes(db),
            "limits": policy.limits(db),
            "actions": {name: {"title": spec["title"], "effect": spec["effect"],
                               "audience": spec["audience"], "outbound": spec["outbound"]}
                        for name, spec in policy.ACTIONS.items()},
            "totals": {row["status"]: row["total"] for row in db.execute(PENDING_COUNT)},
            "cycles": [dict(row) for row in db.execute(CYCLES, (10,))],
            "notice": ("El motor crea tareas y avisos internos. No envía mensajes, no marca llamadas"
                       " y no cambia la etapa de un registro."),
        }


def register_routes(app, actor, payload):
    @app.get("/api/agent")
    async def agent_state(user=Depends(actor)):
        return _state(app.state.store)

    @app.get("/api/agent/preview")
    async def agent_preview(request: Request, user=Depends(actor)):
        app.state.store.require_admin(user)
        app.state.limiter.check(request, "agent_preview", 60, 3600)
        return runtime.preview(app.state.store)

    @app.post("/api/agent/state")
    async def agent_switch(request: Request, user=Depends(actor)):
        app.state.store.require_admin(user)
        app.state.limiter.check(request, "agent_state", 30, 3600)
        data = await payload(request)
        if not isinstance(data, dict) or not isinstance(data.get("enabled"), bool):
            raise DomainError("Indica enabled como verdadero o falso.", 422)
        with app.state.store.connect() as db:
            policy.set_enabled(db, data["enabled"], user)
        return _state(app.state.store)

    @app.post("/api/agent/policy")
    async def agent_policy(request: Request, user=Depends(actor)):
        app.state.store.require_admin(user)
        app.state.limiter.check(request, "agent_policy", 60, 3600)
        data = await payload(request)
        if not isinstance(data, dict):
            raise DomainError("La política requiere una acción y un modo.", 422)
        with app.state.store.connect() as db:
            policy.set_mode(db, str(data.get("action", "")), str(data.get("mode", "")), user)
            app.state.store.audit(db, user, "agent.policy", str(data.get("action", "")))
        return _state(app.state.store)

    @app.post("/api/agent/tick")
    async def agent_tick(request: Request, user=Depends(actor)):
        app.state.store.require_admin(user)
        app.state.limiter.check(request, "agent_tick", 30, 3600)
        return runtime.tick(app.state.store, trigger="manual", actor=user)

    @app.get("/api/agent/decisions")
    async def agent_decisions(user=Depends(actor)):
        with app.state.store.connect() as db:
            rows = (db.execute(DECISIONS_ALL, (100,)) if user["role"] == "admin"
                    else db.execute(DECISIONS_MINE, (user["id"], 100)))
            return {"decisions": [dict(row) for row in rows]}

    # Informes de necesidad. Un asesor ve los que no tienen dueño y los suyos.
    @app.get("/api/needs")
    async def open_needs(user=Depends(actor)):
        return needs.listed(app.state.store, user)

    @app.post("/api/needs/{report_id}/claim")
    async def claim_need(report_id: str, request: Request, user=Depends(actor)):
        app.state.limiter.check(request, "agent_need_claim", 120, 3600)
        return {"report": needs.claim(app.state.store, report_id, user)}

    @app.post("/api/needs/{report_id}/resolve")
    async def resolve_need(report_id: str, request: Request, user=Depends(actor)):
        app.state.limiter.check(request, "agent_need_resolve", 120, 3600)
        return {"report": needs.resolve(app.state.store, report_id, await payload(request), user)}

    # Llamadas: el sistema prepara y cierra; marcar lo hace una persona.
    @app.get("/api/leads/{lead_id}/call-plan")
    async def call_plan(lead_id: str, user=Depends(actor)):
        return calls.plan(app.state.store, lead_id, user)

    @app.post("/api/leads/{lead_id}/call-consent", status_code=201)
    async def call_consent(lead_id: str, request: Request, user=Depends(actor)):
        app.state.limiter.check(request, "agent_call_consent", 120, 3600)
        return {"permission": calls.record_consent(app.state.store, lead_id, await payload(request), user)}

    @app.post("/api/leads/{lead_id}/call-outcome", status_code=201)
    async def call_outcome(lead_id: str, request: Request, user=Depends(actor)):
        app.state.limiter.check(request, "agent_call_outcome", 240, 3600)
        return calls.record_outcome(app.state.store, lead_id, await payload(request), user)

    # Memoria del agente. El ámbito es el del propio registro: un asesor solo ve y
    # cambia la memoria de los suyos, porque `memory` pasa por `store._lead`.
    @app.get("/api/memory/pending")
    async def pending_beliefs(user=Depends(actor)):
        """Lo que el agente dedujo y espera revisión. Un asesor ve la de sus registros."""
        return memory.pending(app.state.store, user)

    @app.get("/api/leads/{lead_id}/memory")
    async def lead_memory(lead_id: str, user=Depends(actor)):
        return memory.history(app.state.store, lead_id, user)

    @app.post("/api/leads/{lead_id}/memory", status_code=201)
    async def remember(lead_id: str, request: Request, user=Depends(actor)):
        app.state.limiter.check(request, "agent_memory", 240, 3600)
        return {"belief": memory.record(app.state.store, lead_id, await payload(request), user)}

    @app.post("/api/memory/{belief_id}/approve")
    async def approve_belief(belief_id: str, request: Request, user=Depends(actor)):
        app.state.limiter.check(request, "agent_memory_approve", 120, 3600)
        return {"belief": memory.approve(app.state.store, belief_id, user)}

    @app.post("/api/memory/{belief_id}/retract")
    async def retract_belief(belief_id: str, request: Request, user=Depends(actor)):
        app.state.limiter.check(request, "agent_memory_retract", 120, 3600)
        return {"belief": memory.retract(app.state.store, belief_id, await payload(request), user)}
