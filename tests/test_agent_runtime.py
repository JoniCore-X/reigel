"""The autonomous engine on a temporary database: it only works when switched on,
it never repeats itself, and nothing it does leaves the team."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from reigel.agent import policy, runtime
from reigel.api import create_app
from team_auth import allow, login as team_login

# El reloj del servidor no se congela: `identity.py` copia `core.now` al importarse
# y Google Authenticator necesita la hora real. Cada ciclo recibe su instante
# explícito, que es lo que hace deterministas estas pruebas. Mediodía UTC evita
# que un desplazamiento de horas cruce la medianoche y cambie el día.
NOW = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
PASSWORD = "synthetic-password-agent"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "agent.db")
    store = app.state.store
    admin = store.create_user(
        {"name": "QA Admin", "email": "agent-admin@example.test", "password": PASSWORD, "role": "admin"},
        bootstrap=True)
    allow(store, admin, "agent-a@example.test")
    advisor = store.create_user(
        {"name": "QA Asesora", "email": "agent-a@example.test", "password": PASSWORD, "role": "advisor"}, admin)
    return app, store, admin, advisor


def lead(store, actor, **overrides):
    return store.create_lead(
        {"name": "Prospecto sintético", "email": "persona@example.test", "phone": "+17875550100",
         "consent": True, **overrides}, actor)


def shape(store, lead_id, *, stage=None, last_contact_at=None, next_followup_at=None):
    """create_lead siempre abre en la etapa 'nuevo'; aquí se coloca el registro donde hace falta."""
    with store.connect() as db:
        if stage is not None:
            db.execute("UPDATE leads SET stage=? WHERE id=?", (stage, lead_id))
        if last_contact_at is not None:
            db.execute("UPDATE leads SET last_contact_at=? WHERE id=?", (last_contact_at, lead_id))
        if next_followup_at is not None:
            db.execute("UPDATE leads SET next_followup_at=? WHERE id=?", (next_followup_at, lead_id))


def login(client, person):
    assert team_login(client, person["email"], PASSWORD).status_code == 200


def enable(store):
    with store.connect() as db:
        policy.set_enabled(db, True)


def rows(store, query, args=()):
    with store.connect() as db:
        return [dict(row) for row in db.execute(query, args)]


def test_a_new_database_starts_switched_off_and_a_cycle_writes_nothing(workspace):
    app, store, admin, advisor = workspace
    lead(store, admin, advisor_id=advisor["id"])
    result = runtime.tick(store, now=NOW)
    assert result["status"] == "disabled" and result["decided"] == 0
    assert rows(store, "SELECT * FROM agent_cycles") == []
    assert rows(store, "SELECT * FROM tasks") == []


def test_once_switched_on_the_engine_opens_the_work_by_itself(workspace):
    app, store, admin, advisor = workspace
    prospect = lead(store, admin, advisor_id=advisor["id"])
    enable(store)
    result = runtime.tick(store, now=NOW)
    assert result["status"] == "ran" and result["executed"] == 1, result
    task = rows(store, "SELECT * FROM tasks")
    assert len(task) == 1
    assert task[0]["owner_id"] == advisor["id"] and task[0]["lead_id"] == prospect["id"]
    assert task[0]["type"] == "call" and task[0]["status"] == "pending"
    assert "Primer contacto" in task[0]["description"]
    decision = rows(store, "SELECT * FROM agent_decisions")[0]
    assert decision["action"] == "first_contact" and decision["status"] == "executed"
    assert decision["entity_id"] == task[0]["id"] and decision["advisor_id"] == advisor["id"]
    cycle = rows(store, "SELECT * FROM agent_cycles")[0]
    assert cycle["trigger"] == "manual" and cycle["finished_at"] and cycle["leads_seen"] == 1


def test_running_the_cycle_again_the_same_day_creates_no_second_task(workspace):
    app, store, admin, advisor = workspace
    lead(store, admin, advisor_id=advisor["id"])
    enable(store)
    runtime.tick(store, now=NOW)
    repeated = runtime.tick(store, now=NOW + timedelta(hours=1))
    assert repeated["decided"] == 0
    assert len(rows(store, "SELECT * FROM tasks")) == 1
    assert len(rows(store, "SELECT * FROM agent_decisions")) == 1


def test_the_idempotency_key_stops_a_repeated_notice_the_same_day(workspace):
    """Un aviso no deja tarea pendiente, así que el freno es la clave de idempotencia."""
    app, store, admin, advisor = workspace
    lead(store, admin, advisor_id=None)
    enable(store)
    assert runtime.tick(store, now=NOW)["executed"] == 1
    repeated = runtime.tick(store, now=NOW + timedelta(hours=5))
    assert repeated["decided"] == 0 and repeated["skipped"] == 1
    assert len(rows(store, "SELECT * FROM internal_notifications")) == 1
    assert len(rows(store, "SELECT * FROM agent_decisions")) == 1


def test_the_engine_does_not_insist_while_the_advisor_has_that_task_pending(workspace):
    app, store, admin, advisor = workspace
    lead(store, admin, advisor_id=advisor["id"])
    enable(store)
    runtime.tick(store, now=NOW)
    # Al día siguiente la tarea sigue pendiente: el motor no apila otra igual.
    later = runtime.tick(store, now=NOW + timedelta(days=1))
    assert later["decided"] == 0
    assert len(rows(store, "SELECT * FROM tasks")) == 1


def test_a_lead_with_no_advisor_is_escalated_to_administration_without_a_task(workspace):
    app, store, admin, advisor = workspace
    orphan = lead(store, admin, advisor_id=None)
    enable(store)
    result = runtime.tick(store, now=NOW)
    assert result["executed"] == 1
    assert rows(store, "SELECT * FROM tasks") == []
    notices = rows(store, "SELECT * FROM internal_notifications")
    assert [notice["user_id"] for notice in notices] == [admin["id"]]
    assert notices[0]["type"] == "agent_assign_advisor" and notices[0]["lead_id"] == orphan["id"]
    decision = rows(store, "SELECT * FROM agent_decisions")[0]
    assert decision["action"] == "assign_advisor" and decision["effect"] == "notify"


def test_an_action_under_approval_is_recorded_and_waits_for_a_person(workspace):
    app, store, admin, advisor = workspace
    lead(store, admin, advisor_id=advisor["id"])
    with store.connect() as db:
        policy.set_mode(db, "first_contact", "approval", admin)
        policy.set_enabled(db, True, admin)
    result = runtime.tick(store, now=NOW)
    assert result["held"] == 1 and result["executed"] == 0, result
    decision = rows(store, "SELECT * FROM agent_decisions")[0]
    assert decision["action"] == "first_contact" and decision["status"] == "planned"
    assert decision["mode"] == "approval" and decision["entity_id"] is None
    assert rows(store, "SELECT * FROM tasks") == []


def test_switching_an_action_to_auto_lets_the_engine_execute_it(workspace):
    app, store, admin, advisor = workspace
    prospect = lead(store, admin, advisor_id=advisor["id"])
    shape(store, prospect["id"], stage="contactado", last_contact_at=(NOW - timedelta(days=10)).isoformat())
    with store.connect() as db:
        policy.set_mode(db, "followup", "approval", admin)
        policy.set_enabled(db, True, admin)
    assert runtime.tick(store, now=NOW)["held"] == 1
    assert rows(store, "SELECT * FROM tasks") == []
    with store.connect() as db:
        policy.set_mode(db, "followup", "auto", admin)
    # El mismo día la decisión ya está tomada: el cambio de modo rige la siguiente.
    assert runtime.tick(store, now=NOW + timedelta(days=1))["executed"] == 1
    assert rows(store, "SELECT type FROM tasks")[0]["type"] == "follow_up"


def test_the_preview_shows_the_plan_without_writing_anything(workspace):
    app, store, admin, advisor = workspace
    lead(store, admin, advisor_id=advisor["id"])
    plan = runtime.preview(store, now=NOW)
    assert plan["enabled"] is False and plan["leads_seen"] == 1
    assert plan["decisions"][0]["action"] == "first_contact"
    assert plan["decisions"][0]["mode"] == "auto"
    assert rows(store, "SELECT * FROM agent_decisions") == [] and rows(store, "SELECT * FROM tasks") == []


def test_a_closed_lead_is_left_alone(workspace):
    app, store, admin, advisor = workspace
    closed = lead(store, admin, advisor_id=advisor["id"])
    shape(store, closed["id"], stage="ganado")
    enable(store)
    result = runtime.tick(store, now=NOW)
    assert result["leads_seen"] == 0 and result["decided"] == 0


def test_the_cycle_respects_its_own_budget(workspace):
    app, store, admin, advisor = workspace
    for index in range(4):
        lead(store, admin, advisor_id=advisor["id"], name=f"Prospecto {index}")
    with store.connect() as db:
        policy.set_runtime_value(db, "max_decisions_per_cycle", "2")
        policy.set_enabled(db, True, admin)
    assert runtime.tick(store, now=NOW)["decided"] == 2
    assert len(rows(store, "SELECT * FROM tasks")) == 2


def test_only_administration_controls_the_engine_and_advisors_see_their_own_decisions(workspace):
    app, store, admin, advisor = workspace
    mine = lead(store, admin, advisor_id=advisor["id"], name="Mío")
    other = lead(store, admin, advisor_id=admin["id"], name="De administración")
    enable(store)
    runtime.tick(store, now=NOW)
    with TestClient(app) as manager, TestClient(app) as helper:
        login(manager, admin)
        login(helper, advisor)
        assert helper.post("/api/agent/state", json={"enabled": False}).status_code == 403
        assert helper.post("/api/agent/tick").status_code == 403
        assert helper.get("/api/agent/preview").status_code == 403
        assert helper.post("/api/agent/policy", json={"action": "first_contact", "mode": "auto"}).status_code == 403
        state = manager.get("/api/agent").json()
        assert state["enabled"] is True and state["modes"]["review_dormant"] == "approval"
        assert "envía mensajes" in state["notice"] and "marca llamadas" in state["notice"]
        seen = {row["lead_id"] for row in helper.get("/api/agent/decisions").json()["decisions"]}
        assert seen == {mine["id"]}
        every = {row["lead_id"] for row in manager.get("/api/agent/decisions").json()["decisions"]}
        assert every == {mine["id"], other["id"]}


def test_administration_can_switch_the_engine_off_over_http(workspace):
    app, store, admin, advisor = workspace
    lead(store, admin, advisor_id=advisor["id"])
    enable(store)
    with TestClient(app) as manager:
        login(manager, admin)
        assert manager.post("/api/agent/state", json={"enabled": False}).json()["enabled"] is False
        assert manager.post("/api/agent/tick").json()["status"] == "disabled"
        assert manager.post("/api/agent/state", json={"enabled": "sí"}).status_code == 422
        assert manager.post("/api/agent/policy", json={"action": "inventada", "mode": "auto"}).status_code == 422
        assert manager.post("/api/agent/policy", json={"action": "first_contact", "mode": "libre"}).status_code == 422
    assert rows(store, "SELECT * FROM tasks") == []


def test_one_unreadable_record_does_not_bring_the_whole_cycle_down(monkeypatch, workspace):
    app, store, admin, advisor = workspace
    lead(store, admin, advisor_id=advisor["id"], name="Primero")
    lead(store, admin, advisor_id=advisor["id"], name="Segundo")
    original = runtime.evaluate
    seen = []

    def explode(lead_row, context=None, now=None):
        seen.append(lead_row["name"])
        if len(seen) == 1:
            raise ValueError("etapa imposible")
        return original(lead_row, context, now)

    monkeypatch.setattr(runtime, "evaluate", explode)
    enable(store)
    result = runtime.tick(store, now=NOW)
    assert len(seen) == 2 and result["decided"] == 1 and result["skipped"] == 1
    cycle = rows(store, "SELECT * FROM agent_cycles")[0]
    assert cycle["error"] == "etapa imposible" and cycle["finished_at"]
    assert len(rows(store, "SELECT * FROM tasks")) == 1


def test_the_switch_and_every_cycle_leave_an_audit_trail(workspace):
    app, store, admin, advisor = workspace
    lead(store, admin, advisor_id=advisor["id"])
    enable(store)
    runtime.tick(store, now=NOW)
    actions = [row["action"] for row in rows(store, "SELECT action FROM audit_events")]
    assert "agent.enabled" in actions and "agent.cycle" in actions
