"""Synthetic business workflows and cross-user isolation for Team Caguas."""
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from reigel import core
from reigel.api import create_app
from reigel.core import DomainError, SCHEMA, Store
from team_auth import allow, login as team_login


@pytest.fixture
def ops(tmp_path, monkeypatch):
    fixed = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
    monkeypatch.setattr(core, "now", lambda: fixed)
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "operations.db")
    store = app.state.store
    admin = store.create_user({"name": "QA Admin", "email": "ops-admin@example.test", "password": "synthetic-password-ops", "role": "admin"}, bootstrap=True)
    allow(store, admin, "ops-a@example.test", "ops-b@example.test")
    a = store.create_user({"name": "QA Asesora A", "email": "ops-a@example.test", "password": "synthetic-password-ops", "role": "advisor"}, admin)
    b = store.create_user({"name": "QA Asesor B", "email": "ops-b@example.test", "password": "synthetic-password-ops", "role": "advisor"}, admin)
    for person in (a, b):
        store.update_user(person["id"], {"public_booking": True, "work_days": list(range(7))}, admin)
    return app, store, admin, a, b


def lead(store, actor, **overrides):
    return store.create_lead({"name": "Prospecto sintético", "email": "persona@example.test", "phone": "+17875550100", "consent": True, **overrides}, actor)


def login(client, person):
    assert team_login(client, person["email"], "synthetic-password-ops").status_code == 200


def test_workflow_lead_edit_activity_task_schedule_dashboard_and_permissions(ops):
    app, store, admin, a, b = ops
    with TestClient(app) as manager, TestClient(app) as outsider:
        login(manager, admin)
        login(outsider, b)
        response = manager.post("/api/leads", json={"name": "Flujo completo", "phone": "7875550199", "advisor_id": a["id"], "consent": True, "interest": "Respaldo", "monthly_kwh": 750})
        assert response.status_code == 201, response.text
        prospect = response.json()["lead"]
        assert prospect["monthly_kwh"] == 750
        response = manager.patch(f"/api/leads/{prospect['id']}", json={"stage": "calificado", "municipality": "Caguas", "opportunity_value": 1000, "next_followup_at": "2026-11-05T14:00:00+00:00"})
        assert response.status_code == 200, response.text
        response = manager.post(f"/api/leads/{prospect['id']}/activities", json={"type": "call", "description": "El asesor registra una llamada manual", "outcome": "Solicita orientación"})
        assert response.status_code == 201, response.text
        response = manager.post("/api/tasks", json={"lead_id": prospect["id"], "owner_id": a["id"], "type": "prepare_orientation", "description": "Preparar orientación preliminar", "priority": "high", "due_at": "2026-11-05T16:00:00+00:00", "reminder_hours": 2})
        assert response.status_code == 201, response.text
        task = response.json()["task"]
        slot = store.slots(a["id"], "2026-11-06")["slots"][0]
        response = manager.post("/api/appointments", json={"lead_id": prospect["id"], "advisor_id": a["id"], "start_at": slot["start_at"]})
        assert response.status_code == 201, response.text
        appointment = response.json()["appointment"]
        detail = manager.get(f"/api/leads/{prospect['id']}").json()
        assert detail["lead"]["stage"] == "cita"
        assert detail["activities"][0]["type"] == "call"
        assert detail["tasks"][0]["id"] == task["id"]
        assert any(item["field"] == "stage" for item in detail["history"])
        assert detail["appointments"][0]["id"] == appointment["id"]
        dashboard = manager.get("/api/dashboard?period=month").json()
        assert dashboard["metrics"]["leads"] == 1
        assert dashboard["metrics"]["opportunity_value"] == 1000
        assert dashboard["metrics"]["overdue_followups"] == 1
        assert any(item["task_id"] == task["id"] for item in dashboard["priorities"] if "task_id" in item)
        for path in (f"/api/leads/{prospect['id']}", f"/api/tasks/{task['id']}", f"/api/appointments/{appointment['id']}/ics"):
            assert outsider.get(path).status_code == 404
        assert outsider.patch(f"/api/leads/{prospect['id']}", json={"stage": "ganado"}).status_code == 404
        assert outsider.patch(f"/api/tasks/{task['id']}", json={"status": "completed"}).status_code == 404
        assert outsider.get("/api/leads").json()["total"] == 0
        assert outsider.get("/api/tasks").json()["total"] == 0


def test_old_schema_migrates_twice_without_changing_history_or_records(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO leads(id,name,email,stage,created_at,updated_at) VALUES(?,?,?,?,?,?)", ("old-id", "Conservado", "legacy@example.test", "calificado", "2026-10-01T12:00:00+00:00", "2026-10-01T12:00:00+00:00"))
    for _ in range(2):
        store = Store(path)
        with store.connect() as db:
            row = db.execute("SELECT * FROM leads WHERE id='old-id'").fetchone()
            assert row["name"] == "Conservado" and row["stage"] == "calificado"
            assert row["interest"] == "" and row["monthly_kwh"] is None
            assert db.execute("SELECT count(*) FROM schema_migrations WHERE version='team_caguas_operations_v1'").fetchone()[0] == 1
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("changes", [{"monthly_kwh": -1}, {"monthly_kwh": float("nan")}, {"opportunity_value": float("inf")}, {"last_contact_at": "2026-11-06T12:00:00+00:00"}, {"next_followup_at": "2026-11-06T12:00:00"}, {"email": "invalid"}, {"stage": "inventado"}, {"consent": "yes"}, {"unknown": "field"}])
def test_invalid_edits_roll_back_without_audit_or_partial_change(ops, changes):
    _, store, admin, a, _ = ops
    item = lead(store, admin, advisor_id=a["id"])
    with pytest.raises(DomainError) as raised:
        store.update_lead(item["id"], {"notes": "No debe persistir", **changes}, admin)
    assert raised.value.status == 422
    assert store.get_lead(item["id"], admin)["notes"] == ""
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM lead_history").fetchone()[0] == 0


def test_search_filters_order_pagination_and_duplicate_detection_are_scoped(ops):
    _, store, admin, a, b = ops
    first = lead(store, admin, name="Alba", advisor_id=a["id"])
    second = lead(store, admin, name="Berta", advisor_id=a["id"])
    lead(store, admin, name="Oculto", advisor_id=b["id"])
    page = store.query_leads(a, q="example.test", sort="name", order="asc", limit=1, offset=1)
    assert page["total"] == 2 and [row["name"] for row in page["leads"]] == ["Berta"]
    assert store.query_leads(a, q="%") ["total"] == 0
    assert [row["id"] for row in store.lead_detail(first["id"], a)["duplicates"]] == [second["id"]]
    with pytest.raises(DomainError) as raised:
        store.query_leads(a, advisor_id=b["id"])
    assert raised.value.status == 403


def test_reassignment_moves_pending_tasks_and_revokes_old_access_and_notifications(ops):
    _, store, admin, a, b = ops
    item = lead(store, admin, advisor_id=a["id"])
    task = store.save_task({"lead_id": item["id"], "owner_id": a["id"], "description": "Seguir", "due_at": "2026-11-05T14:00:00+00:00"}, admin)
    assert store.list_notifications(a)["total"] >= 2
    store.update_lead(item["id"], {"advisor_id": b["id"]}, admin)
    assert store.query_tasks(b)["tasks"][0]["id"] == task["id"]
    assert store.query_tasks(a)["total"] == 0
    assert store.list_notifications(a)["total"] == 0
    with pytest.raises(DomainError):
        store.get_lead(item["id"], a)
    with store.connect() as db:
        assert store._task(db, task["id"], b)["owner_id"] == b["id"]


def test_advisor_cannot_assign_task_or_lead_to_another_user(ops):
    _, store, admin, a, b = ops
    item = lead(store, admin, advisor_id=a["id"])
    with pytest.raises(DomainError) as raised:
        store.save_task({"lead_id": item["id"], "owner_id": b["id"], "description": "No autorizada", "due_at": "2026-11-06T12:00:00+00:00"}, a)
    assert raised.value.status == 403
    with pytest.raises(DomainError) as raised:
        store.update_lead(item["id"], {"advisor_id": b["id"]}, a)
    assert raised.value.status == 403
    with pytest.raises(DomainError) as raised:
        store.save_task({"lead_id": item["id"], "owner_id": b["id"], "description": "Inconsistente", "due_at": "2026-11-06T12:00:00+00:00"}, admin)
    assert raised.value.status == 422


def test_notifications_survive_restart_dedupe_read_and_hide_rescheduled_or_done_tasks(ops):
    _, store, admin, a, b = ops
    item = lead(store, admin, advisor_id=a["id"])
    task = store.save_task({"lead_id": item["id"], "owner_id": a["id"], "description": "Seguimiento persistente", "due_at": "2026-11-05T16:00:00+00:00", "reminder_hours": 2}, admin)
    first = store.list_notifications(a)
    second = store.list_notifications(a)
    assert first["total"] == second["total"]
    notice = next(row for row in first["notifications"] if row["type"] == "task_reminder")
    store.mark_notification(notice["id"], {"read": True}, a)
    restarted = Store(store.path)
    assert next(row for row in restarted.list_notifications(a)["notifications"] if row["id"] == notice["id"])["read"]
    with pytest.raises(DomainError) as raised:
        store.mark_notification(notice["id"], {"read": True}, b)
    assert raised.value.status == 404
    store.save_task({"due_at": "2026-11-05T14:00:00+00:00"}, admin, task["id"])
    current = store.list_notifications(a)["notifications"]
    assert sum(row["entity_id"] == task["id"] for row in current) == 1
    store.save_task({"status": "completed", "outcome": "Registrado manualmente"}, a, task["id"])
    assert not any(row["entity_id"] == task["id"] for row in store.list_notifications(a)["notifications"])
    completed = store.query_tasks(a, status="completed")["tasks"][0]
    assert completed["completed_at"] and completed["outcome"] == "Registrado manualmente"


def test_appointment_completion_and_transfer_require_valid_state_and_no_schedule_conflict(ops):
    _, store, admin, a, b = ops
    item = lead(store, admin, advisor_id=a["id"])
    slot = store.slots(a["id"], "2026-11-06")["slots"][0]
    appointment = store.book({"lead_id": item["id"], "advisor_id": a["id"], "start_at": slot["start_at"]}, actor=admin)
    for operation in (lambda: store.update_appointment(appointment["id"], {"status": "completed"}, admin), lambda: store.update_lead(item["id"], {"advisor_id": b["id"]}, admin)):
        with pytest.raises(DomainError) as raised:
            operation()
        assert raised.value.status == 409
    reminder = store.update_appointment(appointment["id"], {"reminder_hours": 3}, a)
    assert reminder["reminder_hours"] == 3
    with store.connect() as db:
        db.execute("UPDATE appointments SET start_at=?,end_at=? WHERE id=?", ("2026-11-04T14:00:00+00:00", "2026-11-04T14:30:00+00:00", appointment["id"]))
    assert store.update_appointment(appointment["id"], {"status": "completed"}, a)["status"] == "completed"
    assert store.get_lead(item["id"], a)["stage"] == "cita_realizada"
    store.update_lead(item["id"], {"advisor_id": b["id"]}, admin)
    with pytest.raises(DomainError):
        store.get_appointment(appointment["id"], a)
    assert store.list_appointments(a) == []


@pytest.mark.parametrize("hours", [0, 3])
def test_appointment_reminder_is_reloaded_in_agenda_and_lead_detail(ops, hours):
    app, store, admin, a, b = ops
    item = lead(store, admin, advisor_id=a["id"])
    slot = store.slots(a["id"], "2026-11-06")["slots"][0]
    appointment = store.book({"lead_id": item["id"], "advisor_id": a["id"], "start_at": slot["start_at"]}, actor=admin)
    assert store.list_appointments(a)[0]["reminder_hours"] == 24
    with TestClient(app) as advisor, TestClient(app) as outsider:
        login(advisor, a)
        login(outsider, b)
        response = advisor.patch(f"/api/appointments/{appointment['id']}", json={"reminder_hours": hours})
        assert response.status_code == 200, response.text
        assert response.json()["appointment"]["reminder_hours"] == hours
        assert advisor.get("/api/appointments").json()["appointments"][0]["reminder_hours"] == hours
        assert advisor.get(f"/api/leads/{item['id']}").json()["appointments"][0]["reminder_hours"] == hours
        assert outsider.get("/api/appointments").json()["appointments"] == []
        assert outsider.get(f"/api/leads/{item['id']}").status_code == 404
        assert outsider.patch(f"/api/appointments/{appointment['id']}", json={"reminder_hours": 5}).status_code == 404
    restarted = Store(store.path)
    assert restarted.list_appointments(a)[0]["reminder_hours"] == hours


def test_conversation_assignment_cannot_bypass_calendar_transfer_guard(ops):
    _, store, admin, a, b = ops
    item = lead(store, admin, advisor_id=a["id"])
    slot = store.slots(a["id"], "2026-11-06")["slots"][0]
    store.book({"lead_id": item["id"], "advisor_id": a["id"], "start_at": slot["start_at"]}, actor=admin)
    conversation_id = core.uid()
    with store.connect() as db:
        db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?,?,?)", (conversation_id, "web", "qa-external", "QA", item["id"], a["id"], "human", core.stamp()))
    with pytest.raises(DomainError) as raised:
        store.assign_conversation(conversation_id, {"advisor_id": b["id"]}, admin)
    assert raised.value.status == 409
    assert store.conversation(conversation_id, admin)["advisor_id"] == a["id"]


def test_dashboard_dates_use_puerto_rico_and_counts_are_not_limited_to_priority_page(ops):
    _, store, admin, a, _ = ops
    for index in range(12):
        item = lead(store, admin, name=f"Seguimiento {index}", advisor_id=a["id"])
        store.update_lead(item["id"], {"next_followup_at": "2026-11-04T12:00:00+00:00"}, admin)
    old = lead(store, admin, name="Noche anterior", advisor_id=a["id"])
    with store.connect() as db:
        db.execute("UPDATE leads SET created_at='2026-11-05T02:00:00+00:00' WHERE id=?", (old["id"],))
    today = store.operations_dashboard(a, period="today")
    assert today["metrics"]["leads"] == 12
    assert today["metrics"]["overdue_followups"] == 12
    assert today["period"]["timezone"] == "America/Puerto_Rico"
    assert today["metrics"]["opportunity_value"] is None
    with pytest.raises(DomainError):
        store.operations_dashboard(a, start="2026-11-10", end="2026-11-01")


@pytest.mark.parametrize("change", [{"due_at": "sin-fecha"}, {"due_at": "2026-11-06T12:00:00"}, {"reminder_hours": True}, {"reminder_hours": -1}, {"status": "inventado"}, {"priority": "urgent"}, {"type": "send_automatically"}])
def test_task_validation_rejects_malformed_data_without_partial_write(ops, change):
    _, store, admin, a, _ = ops
    item = lead(store, admin, advisor_id=a["id"])
    with pytest.raises(DomainError) as raised:
        store.save_task({"lead_id": item["id"], "owner_id": a["id"], "description": "Validación", "due_at": "2026-11-06T12:00:00+00:00", **change}, admin)
    assert raised.value.status == 422
    assert store.query_tasks(admin)["total"] == 0
