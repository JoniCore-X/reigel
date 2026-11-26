"""Phase 1: platform owner, one-step offboarding and plans kept out of the public site."""
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from reigel.api import create_app
from reigel.core import SCHEMA, migrate_owner, stamp, uid
from team_auth import allow, login as team_login

OWNER = ("owner@example.test", "correct-horse-test-42")
ADMIN = ("lider@example.test", "correct-horse-test-44")
ADVISOR = ("advisor@example.test", "correct-horse-test-43")
OTHER = ("otra@example.test", "correct-horse-test-45")


@pytest.fixture
def team(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "owner.sqlite3")
    store = app.state.store
    owner = store.create_user({"name": "Propietario", "email": OWNER[0], "password": OWNER[1], "role": "admin"}, bootstrap=True)
    allow(store, owner, ADMIN[0], ADVISOR[0], OTHER[0], "l2@example.test", "nuevo@example.test", "lider2@example.test")
    admin = store.create_user({"name": "Líder", "email": ADMIN[0], "password": ADMIN[1], "role": "admin"}, owner)
    advisor = store.create_user({"name": "Asesora", "email": ADVISOR[0], "password": ADVISOR[1]}, owner)
    other = store.create_user({"name": "Otra asesora", "email": OTHER[0], "password": OTHER[1]}, owner)
    for person in (advisor, other):
        store.update_user(person["id"], {"public_booking": True, "work_days": list(range(7))}, owner)
    return app, store, owner, admin, advisor, other


def login(client, credentials):
    response = team_login(client, credentials[0], credentials[1])
    assert response.status_code == 200, response.text
    return client


def future_slot(store, advisor_id, index=0):
    day = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    return store.slots(advisor_id, day)["slots"][index]["start_at"]


def test_bootstrap_account_is_the_only_owner(team):
    _, store, owner, admin, advisor, _ = team
    users = {user["id"]: user for user in store.list_users()}
    assert users[owner["id"]]["is_owner"] is True
    assert users[admin["id"]]["is_owner"] is False
    assert users[advisor["id"]]["is_owner"] is False


def test_owner_migration_is_additive_and_picks_the_oldest_active_admin(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    assert "is_owner" not in {row["name"] for row in db.execute("PRAGMA table_info(users)")}
    rows = [("a1", "admin", 0, "2026-01-02T00:00:00+00:00"), ("a2", "admin", 1, "2026-01-03T00:00:00+00:00"),
            ("a3", "admin", 1, "2026-01-04T00:00:00+00:00"), ("v1", "advisor", 1, "2026-01-01T00:00:00+00:00")]
    for user_id, role, active, created in rows:
        db.execute("INSERT INTO users(id,name,email,password_hash,role,active,created_at) VALUES(?,?,?,?,?,?,?)",
                   (user_id, user_id, f"{user_id}@example.test", "x", role, active, created))
    migrate_owner(db)
    migrate_owner(db)  # idempotent
    owners = [row["id"] for row in db.execute("SELECT id FROM users WHERE is_owner=1")]
    assert owners == ["a2"]
    assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 4
    db.close()


def test_plans_are_private_to_the_owner(team):
    app, *_ = team
    for credentials, expected in ((OWNER, 200), (ADMIN, 403), (ADVISOR, 403)):
        with TestClient(app) as client:
            response = login(client, credentials).get("/api/owner/plans")
            assert response.status_code == expected, credentials
    with TestClient(app) as client:
        assert client.get("/api/owner/plans").status_code == 401
        data = login(client, OWNER).get("/api/owner/plans").json()
        assert [plan["name"] for plan in data["plans"]] == ["Consultor", "Team Caguas", "Team Pro", "Corporativo"]
        assert data["usage"] == {"advisors": 2, "admins": 2, "inactive": 0}
        assert "no cobra" in data["notice"]


def test_plans_page_is_gone_from_the_public_site(team):
    app, *_ = team
    with TestClient(app) as client:
        assert client.get("/precios", headers={"accept": "text/html"}).status_code == 404
        for path in ("/static/pages/precios.html", "/static/css/pricing.css", "/static/js/pricing.js"):
            assert client.get(path).status_code == 404, path
        assert "/precios" not in client.get("/sitemap.xml").text
        for page in ("/captacion", "/empresa", "/soluciones", "/contacto", "/no-existe"):
            text = client.get(page, headers={"accept": "text/html"}).text
            assert "/precios" not in text and "Planes R.E.I.G.E.L." not in text, page
        assert '<button class="nav-item" data-view="subscription" type="button" hidden>' in client.get("/app").text


def test_only_the_owner_manages_administrators(team):
    app, store, owner, admin, _, _ = team
    with TestClient(app) as client:
        login(client, ADMIN)
        created = client.post("/api/team", json={"name": "Nuevo", "email": "nuevo@example.test", "password": "correct-horse-test-46", "role": "admin"})
        assert created.status_code == 403
        assert client.post("/api/team", json={"name": "Nuevo", "email": "nuevo@example.test", "password": "correct-horse-test-46", "role": "advisor"}).status_code == 201
        assert client.patch(f"/api/team/{owner['id']}", json={"active": False}).status_code in {403, 409}
    with TestClient(app) as client:
        login(client, OWNER)
        assert client.patch(f"/api/team/{owner['id']}", json={"active": False}).status_code == 409
        assert client.post("/api/team", json={"name": "Otro líder", "email": "lider2@example.test", "password": "correct-horse-test-47", "role": "admin"}).status_code == 201
        assert client.patch(f"/api/team/{admin['id']}", json={"active": False}).status_code == 200


def test_offboarding_moves_work_and_cuts_access_immediately(team):
    app, store, owner, admin, advisor, other = team
    lead = store.create_lead({"name": "Prospecto", "email": "p@example.test", "phone": "+17875550101", "municipality": "Caguas",
                              "consent": True, "advisor_id": advisor["id"]}, owner)
    appointment = store.book({"lead_id": lead["id"], "advisor_id": advisor["id"], "start_at": future_slot(store, advisor["id"])},
                             source="equipo", actor=owner)
    with store.connect() as db:
        db.execute("INSERT INTO conversations(id,channel,external_id,contact_name,lead_id,advisor_id,mode,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                   ("c1", "web", "ext-1", "Prospecto", lead["id"], advisor["id"], "ai", stamp()))
    due = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    personal = store.save_task({"type": "call", "due_at": due, "description": "Llamada sin prospecto"}, advisor)
    linked = store.save_task({"lead_id": lead["id"], "type": "follow_up", "due_at": due, "description": "Seguimiento"}, advisor)

    departing = login(TestClient(app), ADVISOR)
    assert departing.get("/api/auth/me").status_code == 200
    with TestClient(app) as client:
        login(client, ADMIN)
        response = client.post(f"/api/team/{advisor['id']}/offboard", json={"target_id": other["id"]})
        assert response.status_code == 200, response.text
        result = response.json()
    assert result["moved"] == {"leads": 1, "appointments": 1, "tasks": 2}
    assert result["public_booking_accounts"] == 1  # «Otra asesora» sigue recibiendo reservas
    assert result["user"]["active"] is False and result["user"]["public_booking"] is False

    assert departing.get("/api/auth/me").status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"email": ADVISOR[0], "password": ADVISOR[1]}).status_code == 401
    with store.connect() as db:
        assert db.execute("SELECT advisor_id FROM leads WHERE id=?", (lead["id"],)).fetchone()[0] == other["id"]
        assert db.execute("SELECT advisor_id FROM appointments WHERE id=?", (appointment["id"],)).fetchone()[0] == other["id"]
        assert {row[0] for row in db.execute("SELECT owner_id FROM tasks WHERE id IN (?,?)", (personal["id"], linked["id"]))} == {other["id"]}
        assert tuple(db.execute("SELECT advisor_id,mode FROM conversations WHERE id='c1'").fetchone()) == (other["id"], "human")
        assert db.execute("SELECT count(*) FROM sessions WHERE user_id=?", (advisor["id"],)).fetchone()[0] == 0
        assert db.execute("SELECT new_value FROM lead_history WHERE lead_id=? AND field='advisor_id'", (lead["id"],)).fetchone()[0] == other["id"]
        assert db.execute("SELECT actor_id FROM audit_events WHERE action='user.offboard' AND entity_id=?", (advisor["id"],)).fetchone()[0] == admin["id"]
    with TestClient(app) as client:
        login(client, OTHER)
        assert [item["id"] for item in client.get("/api/leads").json()["leads"]] == [lead["id"]]


def test_offboarding_is_atomic_when_the_receiver_is_busy(team):
    app, store, owner, _, advisor, other = team
    start = future_slot(store, advisor["id"])
    lead = store.create_lead({"name": "Uno", "email": "uno@example.test", "phone": "+17875550102", "municipality": "Caguas",
                              "consent": True, "advisor_id": advisor["id"]}, owner)
    busy = store.create_lead({"name": "Dos", "email": "dos@example.test", "phone": "+17875550103", "municipality": "Caguas",
                              "consent": True, "advisor_id": other["id"]}, owner)
    store.book({"lead_id": lead["id"], "advisor_id": advisor["id"], "start_at": start}, source="equipo", actor=owner)
    store.book({"lead_id": busy["id"], "advisor_id": other["id"], "start_at": start}, source="equipo", actor=owner)
    with TestClient(app) as client:
        login(client, OWNER)
        response = client.post(f"/api/team/{advisor['id']}/offboard", json={"target_id": other["id"]})
        assert response.status_code == 409
        assert "chocan" in response.json()["detail"]
    with store.connect() as db:
        assert db.execute("SELECT active FROM users WHERE id=?", (advisor["id"],)).fetchone()[0] == 1
        assert db.execute("SELECT advisor_id FROM leads WHERE id=?", (lead["id"],)).fetchone()[0] == advisor["id"]


def test_offboarding_permissions(team):
    app, store, owner, admin, advisor, other = team
    with TestClient(app) as client:
        login(client, ADVISOR)
        assert client.post(f"/api/team/{other['id']}/offboard", json={"target_id": advisor["id"]}).status_code == 403
    with TestClient(app) as client:
        login(client, ADMIN)
        assert client.post(f"/api/team/{owner['id']}/offboard", json={"target_id": advisor["id"]}).status_code == 409
        assert client.post(f"/api/team/{admin['id']}/offboard", json={"target_id": advisor["id"]}).status_code == 409
        second = store.create_user({"name": "Líder dos", "email": "l2@example.test", "password": "correct-horse-test-48", "role": "admin"}, owner)
        assert client.post(f"/api/team/{second['id']}/offboard", json={"target_id": advisor["id"]}).status_code == 403
        assert client.post(f"/api/team/{advisor['id']}/offboard", json={"target_id": advisor["id"]}).status_code == 422
        assert client.post(f"/api/team/{advisor['id']}/offboard", json={"target_id": uid()}).status_code == 422
        assert client.post(f"/api/team/{advisor['id']}/offboard", json={}).status_code == 422
    with TestClient(app) as client:
        login(client, OWNER)
        assert client.post(f"/api/team/{admin['id']}/offboard", json={"target_id": owner["id"]}).status_code == 200
        assert client.post(f"/api/team/{admin['id']}/offboard", json={"target_id": owner["id"]}).status_code == 409


def test_offboarding_the_last_bookable_account_is_reported(team):
    app, store, owner, _, advisor, other = team
    store.update_user(other["id"], {"public_booking": False}, owner)
    with TestClient(app) as client:
        assert [item["id"] for item in client.get("/api/public/config").json()["advisors"]] == [advisor["id"]]
        login(client, OWNER)
        result = client.post(f"/api/team/{advisor['id']}/offboard", json={"target_id": other["id"]}).json()
        assert result["public_booking_accounts"] == 0
        assert client.get("/api/public/config").json()["advisors"] == []

