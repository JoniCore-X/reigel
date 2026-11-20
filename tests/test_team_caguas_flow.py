"""A real HTTP workflow over synthetic SQLite data, including cross-advisor denial."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import httpx

from reigel import api


def test_team_caguas_commercial_workflow_and_advisor_isolation(tmp_path, monkeypatch):
    # Explicit DB + no dotenv ensure this integration never opens operator data.
    monkeypatch.setattr(api, "load_environment", lambda: None)
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.setenv("SITE_URL", "")
    app = api.create_app(tmp_path / "team-caguas.sqlite3")
    store = app.state.store
    password = "Synthetic-Caguas-Workflow-2026!"
    admin = store.create_user({"name": "Administración ficticia", "email": "admin@workflow.test",
                               "password": password, "role": "admin"}, bootstrap=True)

    def checked(client, method, path, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == expected, f"{method} {path}: {response.status_code} {response.text}"
        return response.json() if response.headers.get("content-type", "").startswith("application/json") else response

    with TestClient(app) as manager, TestClient(app) as owner, TestClient(app) as outsider:
        checked(manager, "POST", "/api/auth/login", json={"email": admin["email"], "password": password})
        assert checked(manager, "GET", "/api/dashboard")["metrics"]["leads"] == 0
        advisor = checked(manager, "POST", "/api/team", expected=201,
                          json={"name": "Asesor asignado ficticio", "email": "owner@workflow.test", "password": password})["user"]
        other = checked(manager, "POST", "/api/team", expected=201,
                        json={"name": "Otro asesor ficticio", "email": "other@workflow.test", "password": password})["user"]
        assert {user["id"] for user in checked(manager, "GET", "/api/team")["users"]} == {admin["id"], advisor["id"], other["id"]}
        checked(manager, "PATCH", f"/api/team/{advisor['id']}",
                json={"public_booking": True, "work_days": list(range(7)), "timezone": "America/Puerto_Rico"})
        lead = checked(manager, "POST", "/api/leads", expected=201, json={
            "name": "Prospecto completamente ficticio", "email": "person@workflow.test",
            "phone": "+17875550123", "municipality": "Caguas", "source": "referido",
            "monthly_bill": 175, "consent": True, "advisor_id": admin["id"],
        })["lead"]
        lead_id = lead["id"]
        checked(manager, "PATCH", f"/api/leads/{lead_id}", json={"advisor_id": advisor["id"]})
        moment = datetime.now(UTC)
        edited = checked(manager, "PATCH", f"/api/leads/{lead_id}", json={
            "municipality": "Gurabo", "stage": "calificado", "interest": "Respaldo y consumo",
            "monthly_kwh": 600, "opportunity_value": 12000, "notes": "Registro QA ficticio; no contactar.",
            "next_followup_at": (moment - timedelta(hours=1)).isoformat(),
        })["lead"]
        assert edited["advisor_id"] == advisor["id"]
        assert edited["monthly_kwh"] == 600
        found = checked(manager, "GET", "/api/leads", params={"q": "ficticio", "stage": "calificado", "advisor_id": advisor["id"], "sort": "name", "order": "asc"})
        assert found["total"] == 1 and found["leads"][0]["id"] == lead_id
        activity = checked(manager, "POST", f"/api/leads/{lead_id}/activities", expected=201, json={
            "type": "call", "description": "El asesor registra una llamada ficticia realizada manualmente.",
            "outcome": "Solicitó orientación; ninguna llamada automática.",
            "occurred_at": (moment - timedelta(minutes=30)).isoformat(),
        })["activity"]
        task = checked(manager, "POST", "/api/tasks", expected=201, json={
            "lead_id": lead_id, "owner_id": advisor["id"], "type": "follow_up", "priority": "high",
            "description": "Preparar seguimiento ficticio con permiso", "due_at": (moment - timedelta(minutes=5)).isoformat(),
            "reminder_hours": 1,
        })["task"]
        day = (moment + timedelta(days=2)).date().isoformat()
        slots = checked(manager, "GET", "/api/public/slots", params={"advisor_id": advisor["id"], "date": day})
        assert slots["timezone"] == "America/Puerto_Rico" and slots["slots"]
        slot = slots["slots"][0]
        booking = {"lead_id": lead_id, "advisor_id": advisor["id"], "start_at": slot["start_at"]}
        appointment = checked(manager, "POST", "/api/appointments", expected=201, json=booking)["appointment"]
        appointment_id = appointment["id"]
        checked(manager, "PATCH", f"/api/appointments/{appointment_id}", json={"reminder_hours": 72})
        assert appointment["status"] == "confirmed"
        assert checked(manager, "GET", "/api/appointments")["appointments"][0]["id"] == appointment_id
        assert checked(manager, "GET", "/api/tasks", params={"status": "overdue"})["tasks"][0]["id"] == task["id"]
        profile = checked(manager, "GET", f"/api/leads/{lead_id}")
        assert profile["lead"]["stage"] == "cita"
        assert profile["activities"][0]["id"] == activity["id"]
        assert profile["tasks"][0]["id"] == task["id"]
        assert profile["appointments"][0]["id"] == appointment_id
        assert any(item["field"] == "advisor_id" for item in profile["history"])
        brief = checked(manager, "GET", f"/api/leads/{lead_id}/brief")
        assert brief["lead_id"] == lead_id and brief["review_required"] is True and brief["certified"] is False
        energy = checked(manager, "POST", "/api/energy/calculate", json={
            "monthly_kwh": profile["lead"]["monthly_kwh"], "panel_watts": 400, "panel_count": 12,
            "specific_yield_kwh_per_kw_year": 1500, "coverage_target_percent": 100,
        })
        assert energy["results"]["system_kw"] == 4.8
        assert energy["results"]["annual_production_kwh"] == 7200
        assert energy["results"]["coverage_percent"] == 100
        dashboard = checked(manager, "GET", "/api/dashboard", params={"period": "all"})
        assert dashboard["metrics"]["leads"] == 1
        assert dashboard["metrics"]["appointments"] == 1
        assert dashboard["metrics"]["contacts"] == 1
        assert dashboard["metrics"]["overdue_tasks"] == 1
        assert dashboard["metrics"]["overdue_followups"] == 1
        assert dashboard["metrics"]["opportunity_value"] == 12000
        assert dashboard["metrics"]["sales"] == 0
        assert any(item.get("task_id") == task["id"] for item in dashboard["priorities"])

        checked(owner, "POST", "/api/auth/login", json={"email": advisor["email"], "password": password})
        assert checked(owner, "GET", f"/api/leads/{lead_id}")["lead"]["id"] == lead_id
        notifications = checked(owner, "GET", "/api/notifications")
        notification_id = next(item["id"] for item in notifications["notifications"] if item["entity_id"] == task["id"])
        repeated = checked(owner, "GET", "/api/notifications")
        assert {item["id"] for item in repeated["notifications"]} == {item["id"] for item in notifications["notifications"]}
        assert checked(owner, "PATCH", f"/api/notifications/{notification_id}", json={"read": True})["notification"]["read"] is True
        assert checked(owner, "GET", "/api/notifications")["unread"] == notifications["unread"] - 1

        checked(outsider, "POST", "/api/auth/login", json={"email": other["email"], "password": password})
        assert checked(outsider, "GET", "/api/leads")["leads"] == []
        assert checked(outsider, "GET", "/api/tasks")["tasks"] == []
        assert checked(outsider, "GET", "/api/appointments")["appointments"] == []
        assert checked(outsider, "GET", "/api/notifications")["notifications"] == []
        assert checked(outsider, "GET", "/api/dashboard")["metrics"]["leads"] == 0
        for path in (f"/api/leads/{lead_id}", f"/api/leads/{lead_id}/brief", f"/api/tasks/{task['id']}", f"/api/appointments/{appointment_id}/ics"):
            checked(outsider, "GET", path, expected=404)
        checked(outsider, "PATCH", f"/api/leads/{lead_id}", expected=404, json={"stage": "ganado"})
        checked(outsider, "PATCH", f"/api/tasks/{task['id']}", expected=404, json={"status": "completed"})
        checked(outsider, "PATCH", f"/api/notifications/{notification_id}", expected=404, json={"read": True})
        checked(outsider, "PATCH", f"/api/appointments/{appointment_id}", expected=404, json={"status": "cancelled"})
        checked(outsider, "POST", f"/api/leads/{lead_id}/activities", expected=404,
                json={"type": "note", "description": "Intento no autorizado"})
        checked(outsider, "GET", "/api/leads", expected=403, params={"advisor_id": advisor["id"]})
        checked(outsider, "GET", "/api/tasks", expected=403, params={"owner_id": advisor["id"]})

        # Real availability rejects retries and public conflicts atomically.
        checked(manager, "POST", "/api/appointments", expected=409, json=booking)
        checked(manager, "POST", "/api/public/book", expected=409, json={
            "name": "Otro prospecto ficticio sin guardar", "email": "rollback@workflow.test", "consent": True,
            "advisor_id": advisor["id"], "start_at": slot["start_at"],
        })
        assert checked(manager, "GET", "/api/leads")["total"] == 1
        assert len(checked(manager, "GET", "/api/appointments")["appointments"]) == 1
        checked(owner, "PATCH", f"/api/appointments/{appointment_id}", expected=409, json={"status": "completed"})
        calendar = checked(owner, "GET", f"/api/appointments/{appointment_id}/ics")
        assert "BEGIN:VCALENDAR" in calendar.text and appointment_id in calendar.text
        checked(owner, "PATCH", f"/api/appointments/{appointment_id}", json={"status": "cancelled"})
        reopened_slots = checked(owner, "GET", "/api/public/slots", params={"advisor_id": advisor["id"], "date": day})
        assert any(item["start_at"] == slot["start_at"] for item in reopened_slots["slots"])
        replacement = checked(owner, "POST", "/api/appointments", expected=201, json=booking)["appointment"]
        assert replacement["id"] != appointment_id and replacement["status"] == "confirmed"
        checked(owner, "POST", "/api/appointments", expected=409, json=booking)
        done = checked(owner, "PATCH", f"/api/tasks/{task['id']}", json={"status": "completed", "outcome": "Preparación ficticia registrada manualmente."})["task"]
        assert done["completed_at"] and done["outcome"]
        assert checked(owner, "GET", "/api/tasks", params={"status": "overdue"})["tasks"] == []
        assert not any(item["id"] == notification_id for item in checked(owner, "GET", "/api/notifications")["notifications"])
    with store.connect() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM appointments").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM appointments WHERE status='confirmed'").fetchone()[0] == 1


def test_preview_builder_ignores_commercial_path_dotenv_and_external_services(tmp_path, monkeypatch):
    from scripts import preview_team_caguas

    preview_dir = tmp_path / "synthetic-preview"
    preview_dir.mkdir()
    commercial_sentinel = tmp_path / "commercial-do-not-open.sqlite3"
    sentinel_bytes = b"PRIVATE SENTINEL; intentionally not a SQLite database"
    commercial_sentinel.write_bytes(sentinel_bytes)
    monkeypatch.setenv("REIGEL_DB_PATH", str(commercial_sentinel))
    monkeypatch.setenv("REIGEL_ENV", "production")
    monkeypatch.setenv("SITE_URL", "https://private-operator.example")
    monkeypatch.setattr(preview_team_caguas.tempfile, "mkdtemp", lambda **kwargs: str(preview_dir))
    calls, environment_calls, network_calls = [], [], []
    original_connect, original_read_text = sqlite3.connect, Path.read_text

    def guarded_connect(database, *args, **kwargs):
        resolved = Path(database).resolve()
        calls.append(resolved)
        assert resolved == (preview_dir / "preview.sqlite3").resolve()
        return original_connect(database, *args, **kwargs)

    def forbidden_load(*args, **kwargs):
        environment_calls.append(True)
        raise AssertionError("La vista sintética no puede cargar dotenv.")

    def guarded_read_text(path, *args, **kwargs):
        assert path.name != ".env", "La vista sintética no puede leer credenciales dotenv."
        return original_read_text(path, *args, **kwargs)

    async def forbidden_network(self, request, *args, **kwargs):
        network_calls.append(str(request.url))
        raise AssertionError("La vista sintética no puede contactar servicios externos.")

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    monkeypatch.setattr(api, "load_environment", forbidden_load)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_network)
    app, directory = preview_team_caguas.build_preview()
    assert directory == preview_dir
    assert Path(app.state.store.path).resolve() == (preview_dir / "preview.sqlite3").resolve()
    assert commercial_sentinel.read_bytes() == sentinel_bytes
    assert api.load_environment is forbidden_load
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        login = client.post("/api/auth/login", json={"email": preview_team_caguas.PREVIEW_EMAIL,
                                                      "password": preview_team_caguas.PREVIEW_PASSWORD})
        assert login.status_code == 200
        dashboard = client.get("/api/dashboard").json()
        assert dashboard["metrics"]["leads"] >= 1
        assert "DEMO" in client.get("/api/settings").json()["business"]["market"]
        assert all("ficticio" in item["name"] for item in client.get("/api/leads").json()["leads"])
    assert calls and not environment_calls and not network_calls
    assert commercial_sentinel.read_bytes() == sentinel_bytes
