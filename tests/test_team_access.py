"""Team access: mandatory Google Authenticator, owner-controlled allowlist and the
"Power Solar" naming rule (an organizational filter, not a security control).
Synthetic example.com accounts and a temporary database only."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from reigel import core, team_access
from reigel.api import COOKIE, create_app
from reigel.core import DomainError
from team_auth import login

PASSWORD = "Prueba-Acceso-Equipo-2026!"
OWNER = "duena.powersolar@example.com"
ADMIN = "lider.powersolar@example.com"
ADVISOR = "ana.powersolar@example.com"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "team-access.db")
    store = app.state.store
    owner = store.create_user({"name": "Dueña", "email": OWNER, "password": PASSWORD, "role": "admin"}, bootstrap=True)
    store.allow_team_email(ADMIN, owner)
    store.allow_team_email(ADVISOR, owner)
    admin = store.create_user({"name": "Líder", "email": ADMIN, "password": PASSWORD, "role": "admin"}, owner)
    advisor = store.create_user({"name": "Ana", "email": ADVISOR, "password": PASSWORD}, owner)
    return app, store, owner, admin, advisor


def signed_in(app, email):
    browser = TestClient(app, base_url="http://localhost")
    assert login(browser, email, PASSWORD).status_code == 200
    browser.headers["x-reigel-csrf"] = browser.get("/api/team-identity/me").json()["csrf"]
    return browser


def audit_actions(store):
    with sqlite3.connect(store.path) as db:
        return [row[0] for row in db.execute("SELECT action FROM audit_events ORDER BY created_at")]


def test_password_only_login_never_opens_app(world):
    app, *_ = world
    for email in (OWNER, ADMIN, ADVISOR):
        browser = TestClient(app, base_url="http://localhost")
        response = browser.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200 and response.json()["mfa_required"] is True
        assert "user" not in response.json() and COOKIE not in browser.cookies
        for path in ("/api/auth/me", "/api/leads", "/api/dashboard", "/api/team"):
            assert browser.get(path).status_code == 401
    with sqlite3.connect(app.state.store.path) as db:
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_every_role_is_forced_through_enrollment_then_code(world):
    app, store, *_ = world
    for email in (OWNER, ADMIN, ADVISOR):
        first = TestClient(app, base_url="http://localhost").post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert first.json() == {"mfa_required": True, "enrollment_required": True, "invitation_required": True}
        assert login(TestClient(app, base_url="http://localhost"), email, PASSWORD).status_code == 200
        again = TestClient(app, base_url="http://localhost").post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert again.json() == {"mfa_required": True}
    assert "team.totp_enrolled_at_login" in audit_actions(store)


def test_off_list_email_is_refused_for_creation(world):
    app, store, owner, admin, _ = world
    with pytest.raises(DomainError) as refused:
        store.create_user({"name": "Fuera", "email": "fuera.powersolar@example.com", "password": PASSWORD}, owner)
    assert refused.value.status == 403
    browser = signed_in(app, ADMIN)
    response = browser.post("/api/team", json={"name": "Fuera", "email": "fuera.powersolar@example.com", "password": PASSWORD})
    assert response.status_code == 403
    store.allow_team_email(" Fuera.PowerSolar@Example.com ", owner)
    assert browser.post("/api/team", json={"name": "Dentro", "email": "fuera.powersolar@example.com", "password": PASSWORD}).status_code == 201


def test_off_list_login_gets_the_same_generic_error_and_password_cost(world, monkeypatch):
    app, store, owner, _, advisor = world
    store.remove_team_email(ADVISOR, owner)
    checks = []
    original = core.password_matches
    monkeypatch.setattr(core, "password_matches", lambda password, encoded: checks.append(encoded) or original(password, encoded))
    answers = []
    for email, password in ((ADVISOR, PASSWORD), ("nadie.powersolar@example.com", PASSWORD), (ADMIN, "Contraseña-Incorrecta-1")):
        response = TestClient(app, base_url="http://localhost").post("/api/auth/login", json={"email": email, "password": password})
        answers.append((response.status_code, response.json()))
    assert answers[0] == answers[1] == answers[2] == (401, {"detail": "Correo o contraseña incorrectos."})
    # One full Argon2id verification per attempt; off-list and unknown accounts use the dummy hash.
    assert len(checks) == 3 and checks[0] == checks[1] == core.missing_password_hash() != checks[2]
    assert audit_actions(store).count("auth.login_failed") == 3


def test_removing_an_email_revokes_sessions_immediately(world):
    app, store, owner, _, advisor = world
    browser = signed_in(app, ADVISOR)
    assert browser.get("/api/auth/me").status_code == 200
    pending = TestClient(app, base_url="http://localhost")
    pending.post("/api/auth/login", json={"email": ADVISOR, "password": PASSWORD})
    manager = signed_in(app, OWNER)
    result = manager.post("/api/team-access/emails/remove", json={"email": "  ANA.powersolar@example.com"})
    assert result.status_code == 200 and ADVISOR not in [item["email"] for item in result.json()["emails"]]
    assert browser.get("/api/auth/me").status_code == 401
    assert pending.post("/api/team-identity/totp/login", json={"code": "123456"}).status_code == 401
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM sessions WHERE user_id=?", (advisor["id"],)).fetchone()[0] == 0
    assert TestClient(app, base_url="http://localhost").post("/api/auth/login", json={"email": ADVISOR, "password": PASSWORD}).status_code == 401
    assert {"team_access.email_removed", "auth.sessions_revoked"} <= set(audit_actions(store))
    # Allowing the email again restores login; nothing else was deleted.
    manager.post("/api/team-access/emails", json={"email": ADVISOR})
    assert login(TestClient(app, base_url="http://localhost"), ADVISOR, PASSWORD).status_code == 200


def test_the_owner_cannot_be_removed_and_is_re_allowed_on_start(world):
    app, store, owner, *_ = world
    manager = signed_in(app, OWNER)
    assert manager.post("/api/team-access/emails/remove", json={"email": OWNER}).status_code == 409
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE team_allowed_emails SET removed_at='2026-01-01T00:00:00+00:00' WHERE email=?", (OWNER,))
    assert manager.get("/api/auth/me").status_code == 401
    restarted = create_app(store.path)
    assert login(TestClient(restarted, base_url="http://localhost"), OWNER, PASSWORD).status_code == 200
    assert "team_access.owner_auto_allowed" in audit_actions(store)


def test_env_seed_only_adds_and_never_re_adds_a_removed_email(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    path = tmp_path / "seed.db"
    monkeypatch.setenv(team_access.ENV_KEY, " Uno.PowerSolar@example.com, dos.powersolar@example.com,no-es-correo,")
    app = create_app(path)
    store = app.state.store
    owner = store.create_user({"name": "Dueña", "email": OWNER, "password": PASSWORD, "role": "admin"}, bootstrap=True)
    listed = lambda: {item["email"] for item in store.team_access(owner)["emails"]}
    assert listed() == {OWNER, "uno.powersolar@example.com", "dos.powersolar@example.com"}
    store.remove_team_email("dos.powersolar@example.com", owner)
    monkeypatch.setenv(team_access.ENV_KEY, "tres.powersolar@example.com,dos.powersolar@example.com")
    store = create_app(path).state.store
    assert listed() == {OWNER, "uno.powersolar@example.com", "tres.powersolar@example.com"}
    monkeypatch.delenv(team_access.ENV_KEY)
    store = create_app(path).state.store
    assert listed() == {OWNER, "uno.powersolar@example.com", "tres.powersolar@example.com"}
    assert audit_actions(store).count("team_access.email_seeded") == 3


def test_naming_rule_is_on_by_default_and_only_the_owner_toggles_it(world):
    app, store, owner, admin, advisor = world
    overview = store.team_access(owner)
    assert overview["name_rule"] is True and "no un control de seguridad" in overview["notice"]
    with pytest.raises(DomainError) as refused:
        store.allow_team_email("persona@example.com", owner)
    assert refused.value.status == 422
    for email in (ADMIN, ADVISOR):
        other = signed_in(app, email)
        assert other.put("/api/team-access/name-rule", json={"enabled": False}).status_code == 403
        assert other.get("/api/team-access").status_code == 403
        assert other.post("/api/team-access/emails", json={"email": "x.powersolar@example.com"}).status_code == 403
        assert other.post("/api/team-access/emails/remove", json={"email": ADVISOR}).status_code == 403
    manager = signed_in(app, OWNER)
    del manager.headers["x-reigel-csrf"]
    assert manager.put("/api/team-access/name-rule", json={"enabled": False}).status_code == 403
    manager.headers["x-reigel-csrf"] = manager.get("/api/team-identity/me").json()["csrf"]
    assert manager.put("/api/team-access/name-rule", json={"enabled": "no"}).status_code == 422
    assert manager.put("/api/team-access/name-rule", json={"enabled": False}).json()["name_rule"] is False
    assert manager.post("/api/team-access/emails", json={"email": "persona@example.com"}).status_code == 200
    store.create_user({"name": "Sin marca", "email": "persona@example.com", "password": PASSWORD}, owner)
    outsider = signed_in(app, "persona@example.com")
    # Turning the rule back on blocks and signs out the listed account without "powersolar".
    assert manager.put("/api/team-access/name-rule", json={"enabled": True}).json()["name_rule"] is True
    assert outsider.get("/api/auth/me").status_code == 401
    assert TestClient(app, base_url="http://localhost").post("/api/auth/login", json={"email": "persona@example.com", "password": PASSWORD}).status_code == 401
    assert manager.get("/api/auth/me").status_code == 200
    assert {"team_access.name_rule.0", "team_access.name_rule.1", "team_access.email_added"} <= set(audit_actions(store))


def test_owner_endpoints_are_rate_limited_and_emails_stay_out_of_urls(world):
    app, *_ = world
    manager = signed_in(app, OWNER)
    statuses = [manager.post("/api/team-access/emails", json={"email": f"p{n}.powersolar@example.com"}).status_code for n in range(31)]
    assert statuses[:30] == [200] * 30 and statuses[30] == 429
    assert manager.get("/api/team-access/emails/ana.powersolar@example.com").status_code in {404, 405}


def test_migration_is_additive_idempotent_and_public_config_stays_clean(world):
    app, store, owner, *_ = world
    store.set_team_name_rule(False, owner)
    with sqlite3.connect(store.path) as db:
        before = db.execute("SELECT * FROM team_allowed_emails ORDER BY email").fetchall()
        users = db.execute("SELECT id,email,password_hash FROM users ORDER BY id").fetchall()
    again = create_app(store.path)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT * FROM team_allowed_emails ORDER BY email").fetchall() == before
        assert db.execute("SELECT id,email,password_hash FROM users ORDER BY id").fetchall() == users
        assert db.execute("SELECT value FROM settings WHERE key=?", (team_access.RULE_KEY,)).fetchone()[0] == "0"
        assert db.execute("SELECT 1 FROM schema_migrations WHERE version='reigel_team_access_v1'").fetchone()
    public = TestClient(again, base_url="http://localhost").get("/api/public/config").json()
    assert set(public["business"]) <= {"name", "timezone", "market", "privacy_contact", "site_url"}
