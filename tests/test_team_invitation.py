"""SEC-003: invitation codes for the first Google Authenticator registration,
fail-closed TOTP key, owner-only control of administrators, and the related
hardening (per-account limits, escalating lockout, audit, session revocation).

Synthetic example.test accounts and temporary databases only; .env is never read.
"""
import base64
import importlib.util
import shutil
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reigel import api, totp
from reigel.api import COOKIE, create_app
from reigel.core import client_network
from reigel.identity import INVITE_HOURS, TOTP_LOCK_STEPS, grant_hashes
from team_auth import allow, decode, fresh_code, invitation, login, secret_for

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "Prueba-Invitacion-2026!"
INVITE = {"mfa_required": True, "enrollment_required": True, "invitation_required": True}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.delenv("REIGEL_TOTP_KEY", raising=False)
    app = create_app(tmp_path / "invite.db")
    store = app.state.store
    owner = store.create_user({"name": "Dueña", "email": "duena@example.test", "password": PASSWORD, "role": "admin"}, bootstrap=True)
    allow(store, owner, "lider@example.test", "lider2@example.test", "ana@example.test", "luis@example.test")
    admin = store.create_user({"name": "Líder", "email": "lider@example.test", "password": PASSWORD, "role": "admin"}, owner)
    admin2 = store.create_user({"name": "Líder dos", "email": "lider2@example.test", "password": PASSWORD, "role": "admin"}, owner)
    ana = store.create_user({"name": "Ana", "email": "ana@example.test", "password": PASSWORD}, owner)
    luis = store.create_user({"name": "Luis", "email": "luis@example.test", "password": PASSWORD}, owner)
    return app, owner, admin, admin2, ana, luis


def browser(app, host="testclient"):
    return TestClient(app, base_url="http://localhost", client=(host, 50000))


def signed_in(app, email):
    client = browser(app)
    response = login(client, email, PASSWORD)
    assert response.status_code == 200, response.text
    client.headers["x-reigel-csrf"] = client.get("/api/team-identity/me").json()["csrf"]
    return client


def password_step(app, email, host="testclient"):
    client = browser(app, host)
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client, response.json()


def rows(app, sql, *args):
    with sqlite3.connect(app.state.store.path) as db:
        return db.execute(sql, args).fetchall()


def identity_actions(app):
    return [row[0] for row in rows(app, "SELECT action FROM identity_audit ORDER BY created_at")]


def wrong_code(secret):
    valid = {totp.code_at(secret, int(datetime.now(UTC).timestamp() // totp.PERIOD) + offset) for offset in (-1, 0, 1)}
    return next(f"{value:06d}" for value in range(1000000) if f"{value:06d}" not in valid)


# H1 ---------------------------------------------------------------------------
def test_password_alone_never_registers_an_authenticator(world):
    app, *_, ana, _ = world
    client, body = password_step(app, ana["email"])
    assert body == INVITE and COOKIE not in client.cookies
    for payload in ({}, {"invitation_code": ""}, {"invitation_code": "AAAA-AAAA-AAAA-AAAA"}):
        refused = client.post("/api/team-identity/totp/enroll", json=payload)
        assert refused.status_code == 401 and "setup" not in refused.json()
    assert rows(app, "SELECT count(*) FROM team_totp_setups")[0][0] == 0
    assert client.get("/api/auth/me").status_code == 401
    assert "team.invitation_invalid" in identity_actions(app)


def test_valid_invitation_enrolls_once_and_cannot_be_reused(world):
    app, *_, ana, _ = world
    code = invitation(app, ana["email"])
    client, _ = password_step(app, ana["email"])
    # Case, spaces and hyphens do not matter when the code is typed.
    setup = client.post("/api/team-identity/totp/enroll", json={"invitation_code": " " + code.replace("-", " ").lower() + " "})
    assert setup.status_code == 200, setup.text
    # The code was consumed when the QR was shown: a second sign-in cannot reuse it
    # (and a new sign-in replaces the pending one, so only one QR is ever pending).
    other, _ = password_step(app, ana["email"])
    assert other.post("/api/team-identity/totp/enroll", json={"invitation_code": code}).status_code == 401
    stored = rows(app, "SELECT token_hash,consumed_at,purpose,expires_at,created_at FROM team_access_grants WHERE user_id=?", ana["id"])
    assert len(stored) == 1 and stored[0][0] != code and stored[0][1] and stored[0][2] == "enroll"
    setup = other.post("/api/team-identity/totp/enroll", json={"invitation_code": invitation(app, ana["email"])})
    secret = decode(setup.json()["setup"]["secret"])
    done = other.post("/api/team-identity/totp/enroll/confirm", json={"code": totp.code_at(secret, int(datetime.now(UTC).timestamp() // totp.PERIOD))})
    assert done.status_code == 200 and done.json()["user"]["id"] == ana["id"]
    lifetime = datetime.fromisoformat(stored[0][3]) - datetime.fromisoformat(stored[0][4])
    assert timedelta(hours=INVITE_HOURS) - timedelta(minutes=1) < lifetime <= timedelta(hours=INVITE_HOURS, seconds=1)
    assert {"team.invitation_used", "team.totp_enabled"} <= set(identity_actions(app))


def test_invitation_of_another_account_or_expired_or_replaced_is_refused(world):
    app, *_, ana, luis = world
    luis_code = invitation(app, luis["email"])
    client, _ = password_step(app, ana["email"])
    assert client.post("/api/team-identity/totp/enroll", json={"invitation_code": luis_code}).status_code == 401
    # Expired.
    expired = invitation(app, ana["email"])
    with sqlite3.connect(app.state.store.path) as db:
        db.execute("UPDATE team_access_grants SET expires_at=? WHERE user_id=?", ("2000-01-01T00:00:00+00:00", ana["id"]))
    assert client.post("/api/team-identity/totp/enroll", json={"invitation_code": expired}).status_code == 401
    # A new code invalidates the previous one, and a QR shown for the older code can no longer be confirmed.
    first = invitation(app, ana["email"])
    setup = client.post("/api/team-identity/totp/enroll", json={"invitation_code": first})
    assert setup.status_code == 200
    second = invitation(app, ana["email"])
    secret = decode(setup.json()["setup"]["secret"])
    current = totp.code_at(secret, int(datetime.now(UTC).timestamp() // totp.PERIOD))
    assert client.post("/api/team-identity/totp/enroll/confirm", json={"code": current}).status_code == 401
    again, _ = password_step(app, ana["email"])
    assert again.post("/api/team-identity/totp/enroll", json={"invitation_code": first}).status_code == 401
    assert again.post("/api/team-identity/totp/enroll", json={"invitation_code": second}).status_code == 200
    assert "team.grant_revoked" in identity_actions(app)


def test_who_may_issue_codes(world):
    app, owner, admin, admin2, ana, _ = world
    leader = signed_in(app, admin["email"])
    grant = lambda client, user, purpose="enroll": client.post(f"/api/team-identity/users/{user['id']}/grant", json={"purpose": purpose, "reason": "acceso"})
    assert grant(leader, ana).status_code == 200
    assert grant(leader, admin2).status_code == 403
    assert grant(leader, owner).status_code == 403
    assert grant(leader, admin).status_code == 403
    boss = signed_in(app, owner["email"])
    issued = grant(boss, admin2)
    assert issued.status_code == 200 and len(grant_hashes(issued.json()["code"])) >= 1
    # Nobody obtains the owner's codes over HTTP, not even the owner.
    assert grant(boss, owner).status_code == 403
    # Type must match the account state.
    assert grant(boss, admin, "enroll").status_code == 409
    assert grant(boss, ana, "recovery").status_code == 409
    # Without the session CSRF value the request is refused and audited.
    del boss.headers["x-reigel-csrf"]
    assert grant(boss, ana).status_code == 403
    assert "security.csrf_rejected" in identity_actions(app)


def test_local_script_issues_the_owner_invitation_with_confirmation(world, capsys, monkeypatch):
    app, owner, *_ = world
    spec = importlib.util.spec_from_file_location("reigel_team_recovery", ROOT / "scripts" / "team_recovery.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    argv = ["--db", str(app.state.store.path), "--email", owner["email"], "--motivo", "primer acceso", "--purpose", "enroll"]
    assert script.main(argv, ask=lambda prompt: "no") == 3
    assert rows(app, "SELECT count(*) FROM team_access_grants WHERE user_id=?", owner["id"])[0][0] == 0
    assert script.main(argv + ["--yes"]) == 0
    out = capsys.readouterr()
    assert "ATENCIÓN" in out.err and "en persona" in out.err
    code = out.out.split("Código de un solo uso: ")[1].split()[0]
    client, body = password_step(app, owner["email"])
    assert body == INVITE
    assert client.post("/api/team-identity/totp/enroll", json={"invitation_code": code}).status_code == 200
    assert "team.grant_issued_locally.enroll" in identity_actions(app)


def test_code_page_needs_the_password_and_keeps_the_code_on_failure(world):
    app, *_, ana, _ = world
    code = invitation(app, ana["email"])
    device = browser(app)
    assert device.post("/api/team-identity/totp/setup", json={"email": ana["email"], "password": "otra-clave-incorrecta", "grant_code": code}).status_code == 401
    assert device.post("/api/team-identity/totp/setup", json={"email": ana["email"], "grant_code": code}).status_code == 401
    assert rows(app, "SELECT consumed_at FROM team_access_grants WHERE user_id=?", ana["id"])[0][0] is None
    assert device.post("/api/team-identity/totp/setup", json={"email": ana["email"], "password": PASSWORD, "grant_code": code}).status_code == 200
    assert "team.grant_code_invalid" in identity_actions(app)


# H3 ---------------------------------------------------------------------------
def test_only_the_owner_changes_administrators(world):
    app, owner, admin, admin2, ana, _ = world
    leader = signed_in(app, admin["email"])
    new = {"password": "Nueva-Clave-Propia-2026!"}
    assert leader.patch(f"/api/team/{owner['id']}", json=new).status_code == 403
    assert leader.patch(f"/api/team/{owner['id']}", json={"name": "Otra"}).status_code == 403
    assert leader.patch(f"/api/team/{owner['id']}", json={"work_start": "08:00"}).status_code == 403
    assert leader.patch(f"/api/team/{admin2['id']}", json=new).status_code == 403
    assert leader.patch(f"/api/team/{admin2['id']}", json={"name": "Otro"}).status_code == 403
    # An administrator does not rename or reset itself through this route either.
    assert leader.patch(f"/api/team/{admin['id']}", json={"name": "Yo"}).status_code == 403
    assert leader.patch(f"/api/team/{admin['id']}", json=new).status_code == 403
    assert leader.patch(f"/api/team/{admin['id']}", json={"work_start": "08:00"}).status_code == 200
    assert leader.patch(f"/api/team/{ana['id']}", json={"name": "Ana María", "password": "Clave-Asesora-2026!"}).status_code == 200
    # The owner's password is unchanged.
    assert password_step(app, owner["email"])[1] == INVITE
    boss = signed_in(app, owner["email"])
    assert boss.patch(f"/api/team/{admin2['id']}", json={"name": "Líder 2", "password": "Clave-Lider-Dos-2026!"}).status_code == 200
    assert boss.patch(f"/api/team/{owner['id']}", json=new).status_code == 403  # own password: with the current one only
    assert boss.patch(f"/api/team/{owner['id']}", json={"name": "Dueña Principal"}).status_code == 200
    # Roles and emails are not editable through this route for anyone.
    assert boss.patch(f"/api/team/{ana['id']}", json={"role": "admin"}).status_code == 422
    assert boss.patch(f"/api/team/{ana['id']}", json={"email": "otra@example.test"}).status_code == 422


# H4 / H5 / H12 / H13 --------------------------------------------------------
def test_password_attempts_are_limited_per_account_across_addresses(world):
    app, *_, ana, _ = world
    statuses = []
    for index in range(22):
        response = browser(app, f"203.0.113.{index}").post("/api/auth/login", json={"email": ana["email"], "password": "incorrecta-" + str(index)})
        statuses.append(response.status_code)
    assert statuses[:20] == [401] * 20 and statuses[20:] == [429, 429]
    assert browser(app, "198.51.100.7").post("/api/auth/login", json={"email": ana["email"], "password": PASSWORD}).status_code == 429
    # Another account is not affected, and errors stay generic.
    other = browser(app, "198.51.100.8").post("/api/auth/login", json={"email": "nadie@example.test", "password": "incorrecta"})
    assert other.status_code == 401 and other.json()["detail"] == "Correo o contraseña incorrectos."


def test_failed_login_audit_names_the_account_and_only_a_truncated_network(world):
    app, *_, ana, _ = world
    browser(app, "203.0.113.77").post("/api/auth/login", json={"email": ana["email"], "password": "incorrecta-1"})
    browser(app, "2001:db8:abcd:12::5").post("/api/auth/login", json={"email": "nadie@example.test", "password": "incorrecta-2"})
    assert rows(app, "SELECT entity_id FROM audit_events WHERE action='auth.login_failed' ORDER BY created_at") == [(ana["id"],), (None,)]
    nets = rows(app, "SELECT subject_id,client_net FROM identity_audit WHERE action='auth.login_failed' ORDER BY created_at")
    assert nets == [(ana["id"], "203.0.113.0/24"), (None, "2001:db8:abcd::/48")]
    dump = "\n".join(str(line) for line in sqlite3.connect(app.state.store.path).iterdump())
    assert "203.0.113.77" not in dump and "incorrecta" not in dump
    assert client_network("::ffff:192.0.2.9") == "192.0.2.0/24" and client_network("testclient") is None


def test_wrong_codes_lock_with_escalation(world):
    app, *_, ana, _ = world
    signed_in(app, ana["email"])
    secret = secret_for(app.state.store, ana["email"])
    bad = wrong_code(secret)

    hosts = iter(f"192.0.2.{index}" for index in range(1, 250))

    def cycle():
        for _ in range(5):
            client, _ = password_step(app, ana["email"], next(hosts))
            client.post("/api/team-identity/totp/login", json={"code": bad})
        locked = rows(app, "SELECT locked_until FROM team_totp WHERE user_id=?", ana["id"])[0][0]
        minutes = (datetime.fromisoformat(locked) - datetime.now(UTC)).total_seconds() / 60
        with sqlite3.connect(app.state.store.path) as db:  # let the lock lapse (test database only)
            db.execute("UPDATE team_totp SET locked_until=? WHERE user_id=?", ("2000-01-01T00:00:00+00:00", ana["id"]))
        return minutes

    for expected in TOTP_LOCK_STEPS + (TOTP_LOCK_STEPS[-1],):
        assert expected - 1 < cycle() <= expected
    assert {"team.totp_locked", "team.totp_lock_escalated.60m", "team.totp_lock_escalated.1440m"} <= set(identity_actions(app))
    client, _ = password_step(app, ana["email"], next(hosts))
    assert client.post("/api/team-identity/totp/login", json={"code": fresh_code(app.state.store.path, ana["email"], secret)}).status_code == 200
    assert rows(app, "SELECT lock_count FROM team_totp WHERE user_id=?", ana["id"])[0][0] == 0


def test_failed_enrollment_confirmation_is_audited(world):
    app, *_, ana, _ = world
    client, _ = password_step(app, ana["email"])
    setup = client.post("/api/team-identity/totp/enroll", json={"invitation_code": invitation(app, ana["email"])}).json()["setup"]
    assert client.post("/api/team-identity/totp/enroll/confirm", json={"code": wrong_code(decode(setup["secret"]))}).status_code == 401
    assert "team.enrollment_confirm_failed" in identity_actions(app)


def test_changing_the_authenticator_closes_the_other_sessions(world):
    app, *_, ana, _ = world
    phone = signed_in(app, ana["email"])
    laptop = signed_in(app, ana["email"])
    secret = secret_for(app.state.store, ana["email"])
    setup = phone.post("/api/team-identity/totp/setup", json={"current_code": fresh_code(app.state.store.path, ana["email"], secret)})
    assert setup.status_code == 200
    fresh = decode(setup.json()["setup"]["secret"])
    done = phone.post("/api/team-identity/totp/confirm", json={"code": totp.code_at(fresh, int(datetime.now(UTC).timestamp() // totp.PERIOD))})
    assert done.status_code == 200
    assert phone.get("/api/auth/me").status_code == 200
    assert laptop.get("/api/auth/me").status_code == 401


# H2 ---------------------------------------------------------------------------
def test_missing_key_with_existing_secrets_fails_closed_without_a_new_key(world, tmp_path):
    app, *_, ana, _ = world
    signed_in(app, ana["email"])
    path = Path(app.state.store.path)
    key = Path(f"{path}.totp.key")
    assert key.is_file()
    moved = path.with_name("copia")
    moved.mkdir()
    for suffix in ("", "-wal", "-shm"):
        if Path(f"{path}{suffix}").exists():
            shutil.copyfile(f"{path}{suffix}", moved / f"reigel.db{suffix}")
    restarted = create_app(moved / "reigel.db")
    assert restarted.state.identity.key_status()[0] == "missing"
    client, _ = password_step(restarted, ana["email"])
    response = client.post("/api/team-identity/totp/login", json={"code": "123456"})
    assert response.status_code == 503 and "clave" in response.json()["detail"]
    assert not Path(f"{moved / 'reigel.db'}.totp.key").exists()
    # Even a first registration of another account stays closed.
    luis_client, _ = password_step(restarted, "luis@example.test")
    code = invitation(restarted, "luis@example.test")
    assert luis_client.post("/api/team-identity/totp/enroll", json={"invitation_code": code}).status_code == 503
    assert rows(restarted, "SELECT consumed_at FROM team_access_grants WHERE user_id=(SELECT id FROM users WHERE email='luis@example.test')")[0][0] is None
    assert not Path(f"{moved / 'reigel.db'}.totp.key").exists()


def test_malformed_environment_key_gives_a_clear_error(world, monkeypatch):
    app, *_, ana, _ = world
    signed_in(app, ana["email"])
    monkeypatch.setenv("REIGEL_TOTP_KEY", "esto no es base64 !!")
    restarted = create_app(app.state.store.path)
    assert restarted.state.identity.key_status()[0] == "invalid"
    client, _ = password_step(restarted, ana["email"])
    response = client.post("/api/team-identity/totp/login", json={"code": "123456"})
    assert response.status_code == 503 and response.json()["detail"].startswith("El acceso con Google Authenticator no está disponible")
    monkeypatch.setenv("REIGEL_TOTP_KEY", base64.urlsafe_b64encode(b"x" * 16).decode())
    assert create_app(app.state.store.path).state.identity.key_status()[0] == "invalid"


def run_backup(monkeypatch, *argv):
    monkeypatch.setattr(api, "load_environment", lambda path=None: None)
    spec = importlib.util.spec_from_file_location("reigel_backup_script_sec", ROOT / "scripts" / "backup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "argv", ["backup.py", *argv])
    module.main()


def test_restore_drill_backup_with_key_to_a_new_path_keeps_totp_login(world, tmp_path, monkeypatch, capsys):
    app, *_, ana, _ = world
    signed_in(app, ana["email"])
    secret = secret_for(app.state.store, ana["email"])
    copy = tmp_path / "copias" / "copia.db"
    run_backup(monkeypatch, "--db", str(app.state.store.path), "--output", str(copy))
    out = capsys.readouterr().out
    key_copy = Path(f"{copy}.totp.key")
    assert key_copy.is_file() and str(key_copy) in out and "por separado" in out
    assert key_copy.read_bytes() == Path(f"{app.state.store.path}.totp.key").read_bytes()
    # Restore to a new path: both files keep the same base name.
    target = tmp_path / "restaurada" / "reigel.db"
    target.parent.mkdir()
    shutil.copyfile(copy, target)
    shutil.copyfile(key_copy, f"{target}.totp.key")
    restored = create_app(target)
    assert restored.state.identity.key_status()[0] == "file"
    client, _ = password_step(restored, ana["email"])
    response = client.post("/api/team-identity/totp/login", json={"code": fresh_code(target, ana["email"], secret)})
    assert response.status_code == 200 and response.json()["user"]["id"] == ana["id"]


def test_restore_with_the_environment_key_and_backup_reminder(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.setenv("REIGEL_TOTP_KEY", base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("="))
    app = create_app(tmp_path / "env.db")
    owner = app.state.store.create_user({"name": "Dueña", "email": "duena@example.test", "password": PASSWORD, "role": "admin"}, bootstrap=True)
    assert login(browser(app), owner["email"], PASSWORD).status_code == 200
    secret = secret_for(app.state.store, owner["email"])
    assert not Path(f"{app.state.store.path}.totp.key").exists()
    copy = tmp_path / "copia.db"
    run_backup(monkeypatch, "--db", str(app.state.store.path), "--output", str(copy))
    assert "REIGEL_TOTP_KEY" in capsys.readouterr().out and not Path(f"{copy}.totp.key").exists()
    restored = create_app(copy)
    client, _ = password_step(restored, owner["email"])
    assert client.post("/api/team-identity/totp/login", json={"code": fresh_code(copy, owner["email"], secret)}).status_code == 200


def test_doctor_reports_the_key_before_start(world):
    app, *_, ana, _ = world
    spec = importlib.util.spec_from_file_location("reigel_doctor_sec", ROOT / "scripts" / "doctor.py")
    doctor = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = doctor  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(doctor)
    assert doctor.check_totp_key(None).status == "AVISO"
    signed_in(app, ana["email"])
    assert doctor.check_totp_key(str(app.state.store.path)).status == "OK"
    Path(f"{app.state.store.path}.totp.key").unlink()
    result = doctor.check_totp_key(str(app.state.store.path))
    assert result.status == "ERROR" and "No se generará una clave nueva" in result.detail
    assert not Path(f"{app.state.store.path}.totp.key").exists()
