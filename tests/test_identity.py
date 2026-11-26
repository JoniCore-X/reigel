import base64
import hashlib
import json
import time
import sqlite3
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import segno
from fastapi.testclient import TestClient

from reigel.api import COOKIE, create_app
from reigel.core import password_matches
from reigel.identity_api import CUSTOMER_COOKIE
from reigel import totp
from team_auth import allow, fresh_code, login as login_with_code, secret_for

PASSWORD = "Prueba-Identidad-2026!"
BASE = "http://localhost"


class Delivery:
    def __init__(self):
        self.sent = []

    def available(self, kind):
        return True

    def send(self, kind, destination, code, purpose):
        self.sent.append((kind, destination, code, purpose))
        return True


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.setenv("REIGEL_ENV", "local")
    for provider in ("GOOGLE", "FACEBOOK", "X", "TIKTOK"):
        monkeypatch.delenv(f"REIGEL_OAUTH_{provider}_CLIENT_ID", raising=False)
        monkeypatch.delenv(f"REIGEL_OAUTH_{provider}_CLIENT_SECRET", raising=False)
    app = create_app(tmp_path / "identity.db")
    app.state.identity.delivery = Delivery()
    store = app.state.store
    owner = store.create_user({"name": "Owner", "email": "owner@example.test", "password": PASSWORD, "role": "admin"}, bootstrap=True)
    allow(store, owner, "admin@example.test", "consultor@example.test", "otro@example.test")
    admin = store.create_user({"name": "Admin", "email": "admin@example.test", "password": PASSWORD, "role": "admin"}, owner)
    consultant = store.create_user({"name": "Consultor", "email": "consultor@example.test", "password": PASSWORD, "role": "advisor"}, owner)
    other = store.create_user({"name": "Otro", "email": "otro@example.test", "password": PASSWORD, "role": "advisor"}, owner)
    return app, owner, admin, consultant, other


def client(app):
    return TestClient(app, base_url=BASE)


def team_login(app, email):
    """Full sign-in: password, then QR enrollment the first time or the current code."""
    browser = client(app)
    response = login_with_code(browser, email, PASSWORD)
    assert response.status_code == 200, response.text
    csrf = browser.get("/api/team-identity/me").json()["csrf"]
    browser.headers["x-reigel-csrf"] = csrf
    return browser


def register_customer(app, username="ana.cliente", email="ana@example.test", phone=None):
    browser = client(app)
    body = {"username": username, "password": PASSWORD}
    if email:
        body["email"] = email
    if phone:
        body["phone"] = phone
    response = browser.post("/api/customer/register", json=body)
    assert response.status_code == 201, response.text
    browser.headers["x-reigel-csrf"] = response.json()["csrf"]
    return browser, response.json()["customer"]


def verify_all(app, browser, customer):
    for item in customer["identifiers"]:
        assert browser.post("/api/customer/verify/start", json={"identifier_id": item["id"]}).status_code == 200
        code = app.state.identity.delivery.sent[-1][2]
        assert browser.post("/api/customer/verify/finish", json={"identifier_id": item["id"], "code": code}).status_code == 200


def secret_of(setup):
    value = setup["secret"]
    return base64.b32decode(value + "=" * (-len(value) % 8))


def step_code(secret, offset=0):
    return totp.code_at(secret, int(time.time() // totp.PERIOD) + offset)


def enrolled_secret(app, email):
    team_login(app, email)
    return secret_for(app.state.store, email)


def password_step(app, email):
    browser = client(app)
    response = browser.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200 and response.json() == {"mfa_required": True}
    assert COOKIE not in browser.cookies
    return browser


def test_customer_passwords_use_argon2id_and_never_leave_the_server(world):
    app, *_ = world
    _, customer = register_customer(app)
    with sqlite3.connect(app.state.store.path) as db:
        encoded = db.execute("SELECT password_hash FROM customers WHERE id=?", (customer["id"],)).fetchone()[0]
    assert encoded.startswith("$argon2id$")
    assert "password" not in json.dumps({k: v for k, v in customer.items() if k != "has_password"})


def test_login_with_each_identifier_only_after_verification(world):
    app, *_ = world
    browser, customer = register_customer(app, phone="787-555-0101")
    assert client(app).post("/api/customer/login", json={"identifier": "ana.cliente", "password": PASSWORD}).status_code == 200
    assert client(app).post("/api/customer/login", json={"identifier": "ana@example.test", "password": PASSWORD}).status_code == 401
    verify_all(app, browser, customer)
    for identifier in ("ANA.cliente", "ana@example.test", "+17875550101", "(787) 555-0101"):
        assert client(app).post("/api/customer/login", json={"identifier": identifier, "password": PASSWORD}).status_code == 200


def test_unverified_claim_cannot_take_over_a_verified_identifier(world):
    app, *_ = world
    owner, customer = register_customer(app)
    attacker, intruder = register_customer(app, "intruso", email="ana@example.test")
    verify_all(app, owner, customer)
    assert attacker.post("/api/customer/verify/start", json={"identifier_id": intruder["identifiers"][0]["id"]}).status_code == 200
    code = app.state.identity.delivery.sent[-1][2]
    assert attacker.post("/api/customer/verify/finish", json={"identifier_id": intruder["identifiers"][0]["id"], "code": code}).status_code == 409


def test_customer_isolation_csrf_and_foreign_identifier(world):
    app, *_ = world
    ana, ana_data = register_customer(app)
    luis, _ = register_customer(app, "luis.cliente", "luis@example.test")
    assert luis.post("/api/customer/verify/start", json={"identifier_id": ana_data["identifiers"][0]["id"]}).status_code == 404
    assert luis.get("/api/customer/me").json()["customer"]["username"] == "luis.cliente"
    del ana.headers["x-reigel-csrf"]
    assert ana.post("/api/customer/logout").status_code == 403
    ana.headers["x-reigel-csrf"] = luis.headers["x-reigel-csrf"]
    assert ana.post("/api/customer/logout").status_code == 403


def test_recovery_is_generic_single_use_and_revokes_sessions(world):
    app, *_ = world
    browser, customer = register_customer(app)
    verify_all(app, browser, customer)
    delivery = app.state.identity.delivery
    before = len(delivery.sent)
    missing = client(app).post("/api/customer/recover/start", json={"identifier": "nadie@example.test"})
    present = client(app).post("/api/customer/recover/start", json={"identifier": "ana@example.test"})
    assert missing.status_code == present.status_code == 202 and missing.json() == present.json()
    assert len(delivery.sent) == before + 1
    code = delivery.sent[-1][2]
    new_password = "Otra-Clave-Segura-2026!"
    assert client(app).post("/api/customer/recover/finish", json={"identifier": "ana@example.test", "code": "00000000", "new_password": new_password}).status_code in {400}
    assert client(app).post("/api/customer/recover/finish", json={"identifier": "ana@example.test", "code": code, "new_password": new_password}).status_code == 200
    assert browser.get("/api/customer/me").status_code == 401
    assert client(app).post("/api/customer/recover/finish", json={"identifier": "ana@example.test", "code": code, "new_password": PASSWORD}).status_code == 400
    assert client(app).post("/api/customer/login", json={"identifier": "ana.cliente", "password": new_password}).status_code == 200


def test_recovery_code_locks_after_repeated_failures(world):
    app, *_ = world
    browser, customer = register_customer(app)
    verify_all(app, browser, customer)
    client(app).post("/api/customer/recover/start", json={"identifier": "ana@example.test"})
    code = app.state.identity.delivery.sent[-1][2]
    wrong = "00000000" if code != "00000000" else "11111111"
    for _ in range(5):
        client(app).post("/api/customer/recover/finish", json={"identifier": "ana@example.test", "code": wrong, "new_password": "Otra-Clave-Segura-2026!"})
    assert client(app).post("/api/customer/recover/finish", json={"identifier": "ana@example.test", "code": code, "new_password": "Otra-Clave-Segura-2026!"}).status_code == 400


def test_customer_and_team_realms_cannot_cross(world):
    app, _, _, consultant, _ = world
    customer_browser, _ = register_customer(app, "consultor.falso", email=consultant["email"])
    token = customer_browser.cookies.get(CUSTOMER_COOKIE)
    crossed = client(app)
    crossed.cookies.set(COOKIE, token)
    assert crossed.get("/api/auth/me").status_code == 401
    assert crossed.get("/api/leads").status_code == 401
    assert crossed.get("/api/team-identity/me").status_code == 401
    assert client(app).post("/api/auth/login", json={"email": consultant["email"], "password": "Clave-De-Cliente-2026!"}).status_code == 401
    team = team_login(app, consultant["email"])
    reverse = client(app)
    reverse.cookies.set(CUSTOMER_COOKIE, team.cookies.get(COOKIE))
    assert reverse.get("/api/customer/me").status_code == 401


def test_providers_are_disabled_without_credentials(world):
    app, *_ = world
    browser = client(app)
    assert browser.get("/api/customer/config").json()["providers"] == []
    assert browser.post("/api/customer/oauth/google/start", json={"mode": "login"}).status_code == 404


def oauth_transport(subject):
    seen = {}

    def handler(request):
        if request.url.path.endswith("/token"):
            seen["token"] = parse_qs(request.content.decode())
            return httpx.Response(200, json={"access_token": "provider-token"})
        return httpx.Response(200, json={"sub": subject, "name": "Ana", "email": "ana@example.test"})
    return httpx.MockTransport(handler), seen


def oauth_round(app, browser, subject, mode="login"):
    transport, seen = oauth_transport(subject)
    app.state.oauth_transport = transport
    url = browser.post("/api/customer/oauth/google/start", json={"mode": mode}).json()["url"]
    query = parse_qs(urlparse(url).query)
    response = browser.get("/api/customer/oauth/google/callback", params={"code": "abc", "state": query["state"][0]}, follow_redirects=False)
    return response, query, seen


def test_oauth_uses_pkce_state_binding_and_does_not_merge_by_email(world, monkeypatch):
    app, *_ = world
    monkeypatch.setenv("REIGEL_OAUTH_GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("REIGEL_OAUTH_GOOGLE_CLIENT_SECRET", "secret")
    existing, existing_data = register_customer(app)
    verify_all(app, existing, existing_data)
    browser = client(app)
    response, query, seen = oauth_round(app, browser, "google-subject")
    assert response.status_code == 303 and response.headers["location"] == "/cuenta"
    assert query["code_challenge_method"] == ["S256"]
    assert base64.urlsafe_b64encode(hashlib.sha256(seen["token"]["code_verifier"][0].encode()).digest()).rstrip(b"=").decode() == query["code_challenge"][0]
    assert browser.get("/api/customer/me").json()["customer"]["id"] != existing_data["id"]
    with sqlite3.connect(app.state.store.path) as db:
        assert "provider-token" not in " ".join(str(row) for row in db.execute("SELECT * FROM customer_oauth_accounts"))

    victim = client(app)
    url = victim.post("/api/customer/oauth/google/start", json={"mode": "login"}).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    attacker = client(app)
    failed = attacker.get("/api/customer/oauth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)
    assert failed.headers["location"] == "/cuenta?error=oauth"


def test_link_requires_session_and_cannot_steal_another_profile(world, monkeypatch):
    app, *_ = world
    monkeypatch.setenv("REIGEL_OAUTH_GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("REIGEL_OAUTH_GOOGLE_CLIENT_SECRET", "secret")
    assert client(app).post("/api/customer/oauth/google/start", json={"mode": "link"}).status_code == 401
    ana, _ = register_customer(app)
    luis, _ = register_customer(app, "luis.cliente", "luis@example.test")
    assert oauth_round(app, ana, "shared-subject", "link")[0].headers["location"] == "/cuenta"
    assert oauth_round(app, luis, "shared-subject", "link")[0].headers["location"] == "/cuenta?error=oauth"
    assert luis.get("/api/customer/me").json()["customer"]["providers"] == []
    assert ana.delete("/api/customer/oauth/google").status_code == 200


def test_entitlements_are_isolated_per_customer(world):
    app, *_ = world
    ana, ana_data = register_customer(app)
    luis, _ = register_customer(app, "luis.cliente", "luis@example.test")
    with sqlite3.connect(app.state.store.path) as db:
        db.execute("INSERT INTO commerce_products VALUES('p1','producto','Producto',1,'2026-01-01')")
        db.execute("INSERT INTO customer_entitlements VALUES('e1',?,'p1','acceso','prueba',NULL,'2026-01-01')", (ana_data["id"],))
    assert len(ana.get("/api/customer/entitlements").json()["items"]) == 1
    assert luis.get("/api/customer/entitlements").json()["items"] == []


def test_no_public_team_registration_route(world):
    app, *_ = world
    browser = client(app)
    for path in ("/api/team/register", "/api/team-identity/register", "/api/auth/register"):
        assert browser.post(path, json={"email": "x@example.test", "password": PASSWORD}).status_code in {404, 405}
    denied = browser.post("/api/team-identity/totp/setup", json={"email": "consultor@example.test", "grant_code": "inventado"})
    assert denied.status_code == 401
    assert browser.post("/api/team-identity/totp/setup", json={}).status_code == 401


def test_totp_matches_rfc6238_vector():
    assert totp.code_at(b"12345678901234567890", 1) == "287082"
    assert totp.code_at(b"12345678901234567890", 37037036) == "081804"


def test_otpauth_uri_is_google_authenticator_compatible():
    uri = totp.otpauth_uri(b"12345678901234567890", "ana@example.test")
    parsed = urlparse(uri)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "otpauth" and parsed.netloc == "totp"
    assert query["secret"] == ["GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"] and query["digits"] == ["6"] and query["period"] == ["30"] and query["algorithm"] == ["SHA1"]


def first_login(app, email):
    browser = client(app)
    response = browser.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200 and response.json() == {"mfa_required": True, "enrollment_required": True}
    assert COOKIE not in browser.cookies
    return browser


def test_setup_returns_a_qr_for_the_same_otpauth_uri(world):
    app, _, _, consultant, _ = world
    setup = first_login(app, consultant["email"]).post("/api/team-identity/totp/enroll").json()["setup"]
    assert setup["qr"].startswith("data:image/svg+xml")
    expected = segno.make(setup["otpauth_uri"], error="m", micro=False).svg_data_uri(scale=6, border=4, dark="#000", light="#fff")
    assert setup["qr"] == expected


def test_password_alone_opens_no_session_once_totp_is_enabled(world):
    app, _, _, consultant, _ = world
    secret = enrolled_secret(app, consultant["email"])
    browser = password_step(app, consultant["email"])
    assert browser.get("/api/auth/me").status_code == 401
    assert browser.post("/api/team-identity/totp/login", json={"code": "000000" if step_code(secret, 1) != "000000" else "111111"}).status_code == 401
    response = browser.post("/api/team-identity/totp/login", json={"code": fresh_code(app.state.store.path, consultant["email"], secret)})
    assert response.status_code == 200 and response.json()["user"]["id"] == consultant["id"]
    assert browser.get("/api/auth/me").json()["user"]["id"] == consultant["id"]


def test_code_requires_prior_password_and_cannot_be_replayed(world):
    app, _, _, consultant, _ = world
    secret = enrolled_secret(app, consultant["email"])
    code = fresh_code(app.state.store.path, consultant["email"], secret)
    assert client(app).post("/api/team-identity/totp/login", json={"code": code}).status_code == 401
    assert password_step(app, consultant["email"]).post("/api/team-identity/totp/login", json={"code": code}).status_code == 200
    assert password_step(app, consultant["email"]).post("/api/team-identity/totp/login", json={"code": code}).status_code == 401


def test_repeated_wrong_codes_lock_across_new_password_steps(world):
    app, _, _, consultant, _ = world
    secret = enrolled_secret(app, consultant["email"])
    valid = {step_code(secret, offset) for offset in (-1, 0, 1)}
    wrong = next(f"{value:06d}" for value in range(1000000) if f"{value:06d}" not in valid)
    for _ in range(5):
        password_step(app, consultant["email"]).post("/api/team-identity/totp/login", json={"code": wrong})
    code = fresh_code(app.state.store.path, consultant["email"], secret)
    assert password_step(app, consultant["email"]).post("/api/team-identity/totp/login", json={"code": code}).status_code == 429


def test_secret_is_encrypted_and_bound_to_its_user(world):
    app, _, _, consultant, other = world
    browser = first_login(app, consultant["email"])
    setup = browser.post("/api/team-identity/totp/enroll").json()["setup"]
    secret = secret_of(setup)
    assert browser.post("/api/team-identity/totp/enroll/confirm", json={"code": step_code(secret)}).status_code == 200
    with sqlite3.connect(app.state.store.path) as db:
        row = db.execute("SELECT secret_nonce,secret_cipher FROM team_totp").fetchone()
        dump = "\n".join(str(item) for item in db.iterdump())
    assert secret not in row[1] and setup["secret"] not in dump
    with pytest.raises(Exception):
        app.state.identity._open(row[0], row[1], other["id"])


def test_replacing_totp_needs_current_code_and_there_is_no_way_to_disable_it(world):
    app, _, _, consultant, _ = world
    browser = team_login(app, consultant["email"])
    secret = secret_for(app.state.store, consultant["email"])
    assert browser.post("/api/team-identity/totp/setup", json={}).status_code == 401
    assert browser.post("/api/team-identity/totp/setup", json={"current_code": "abc"}).status_code == 401
    for method, path in (("POST", "/api/team-identity/totp/disable"), ("DELETE", "/api/team-identity/totp"),
                         ("PUT", "/api/team-identity/policy")):
        assert browser.request(method, path, json={"code": step_code(secret), "totp_required": False}).status_code in {404, 405}
    with sqlite3.connect(app.state.store.path) as db:
        assert db.execute("SELECT count(*) FROM team_totp WHERE user_id=?", (consultant["id"],)).fetchone()[0] == 1
    assert browser.get("/api/team-identity/me").json()["totp_required"] is True
    replaced = browser.post("/api/team-identity/totp/setup", json={"current_code": fresh_code(app.state.store.path, consultant["email"], secret)})
    assert replaced.status_code == 200 and replaced.json()["setup"]["qr"].startswith("data:image/svg+xml")


def test_setup_of_one_user_cannot_be_confirmed_by_another(world):
    app, _, _, consultant, other = world
    victim = team_login(app, consultant["email"])
    current = fresh_code(app.state.store.path, consultant["email"], secret_for(app.state.store, consultant["email"]))
    setup = victim.post("/api/team-identity/totp/setup", json={"current_code": current}).json()["setup"]
    ticket = victim.cookies.get("reigel_totp_setup")
    attacker = team_login(app, other["email"])
    attacker.cookies.set("reigel_totp_setup", ticket, path="/api/team-identity/totp")
    assert attacker.post("/api/team-identity/totp/confirm", json={"code": step_code(secret_of(setup))}).status_code == 401


def test_supervisor_gains_no_admin_or_data_privileges(world):
    app, _, admin, consultant, other = world
    administrator = team_login(app, admin["email"])
    assert administrator.put(f"/api/team-identity/users/{other['id']}/role", json={"role": "supervisor"}).status_code == 200
    supervisor = team_login(app, other["email"])
    assert supervisor.get("/api/auth/me").json()["user"]["role"] == "advisor"
    assert supervisor.get("/api/team-identity/me").json()["user"]["team_role"] == "supervisor"
    assert supervisor.post(f"/api/team-identity/users/{consultant['id']}/grant", json={"purpose": "recovery", "reason": "x"}).status_code == 403
    assert supervisor.put(f"/api/team-identity/users/{consultant['id']}/role", json={"role": "supervisor"}).status_code == 403
    assert supervisor.put(f"/api/team-identity/users/{other['id']}/role", json={"role": "administrador"}).status_code == 403
    assert supervisor.get("/api/team-access").status_code == 403
    assert supervisor.put("/api/team-access/name-rule", json={"enabled": False}).status_code == 403


def test_recovery_is_admin_only_audited_single_use_and_replaces_secret(world):
    app, owner, admin, consultant, _ = world
    team = team_login(app, consultant["email"])
    lost = secret_for(app.state.store, consultant["email"])
    administrator = team_login(app, admin["email"])
    assert administrator.post(f"/api/team-identity/users/{admin['id']}/grant", json={"purpose": "recovery", "reason": "propio"}).status_code == 403
    assert administrator.post(f"/api/team-identity/users/{owner['id']}/grant", json={"purpose": "recovery", "reason": "dueño"}).status_code == 403
    code = administrator.post(f"/api/team-identity/users/{consultant['id']}/grant", json={"purpose": "recovery", "reason": "teléfono perdido"}).json()["code"]
    device = client(app)
    assert device.post("/api/team-identity/totp/setup", json={"email": "otro@example.test", "grant_code": code}).status_code == 401
    setup = device.post("/api/team-identity/totp/setup", json={"email": consultant["email"], "grant_code": code}).json()["setup"]
    fresh = secret_of(setup)
    assert device.post("/api/team-identity/totp/confirm", json={"code": step_code(fresh), "with_grant": True}).status_code == 200
    assert team.get("/api/auth/me").status_code == 401
    assert password_step(app, consultant["email"]).post("/api/team-identity/totp/login", json={"code": step_code(lost, 1)}).status_code == 401
    assert client(app).post("/api/team-identity/totp/setup", json={"email": consultant["email"], "grant_code": code}).status_code == 401
    with sqlite3.connect(app.state.store.path) as db:
        actions = {row[0] for row in db.execute("SELECT action FROM identity_audit WHERE realm='team'")}
        stored = db.execute("SELECT token_hash FROM team_access_grants").fetchone()[0]
    assert {"team.grant_issued.recovery", "team.recovery_completed"} <= actions
    assert stored != code


def test_first_login_without_totp_must_enroll_before_any_session(world):
    app, owner, _, _, _ = world
    browser = first_login(app, owner["email"])
    for path in ("/api/auth/me", "/api/dashboard", "/api/team-identity/me", "/api/team-access"):
        assert browser.get(path).status_code == 401
    # The enrollment ticket cannot stand in for the code of an enrolled account.
    assert browser.post("/api/team-identity/totp/login", json={"code": "123456"}).status_code == 401
    setup = browser.post("/api/team-identity/totp/enroll").json()["setup"]
    secret = secret_of(setup)
    wrong = "000000" if step_code(secret) != "000000" else "111111"
    assert browser.post("/api/team-identity/totp/enroll/confirm", json={"code": wrong}).status_code == 401
    assert browser.get("/api/auth/me").status_code == 401
    done = browser.post("/api/team-identity/totp/enroll/confirm", json={"code": step_code(secret)})
    assert done.status_code == 200 and done.json()["user"]["id"] == owner["id"]
    cookie = done.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert browser.get("/api/auth/me").json()["user"]["id"] == owner["id"]
    # From now on the password leads to the code step, never to a second enrollment.
    later = client(app).post("/api/auth/login", json={"email": owner["email"], "password": PASSWORD})
    assert later.json() == {"mfa_required": True}
    assert client(app).post("/api/team-identity/totp/enroll").status_code == 401


def test_enrollment_ticket_never_replaces_an_existing_authenticator(world):
    app, _, _, consultant, _ = world
    early = first_login(app, consultant["email"])
    assert early.post("/api/team-identity/totp/enroll").status_code == 200
    secret = enrolled_secret(app, consultant["email"])
    with sqlite3.connect(app.state.store.path) as db:
        db.execute("INSERT INTO team_enroll_challenges VALUES(?,?,?)",
                   (hashlib.sha256(b"forged").hexdigest(), consultant["id"], "2999-01-01T00:00:00+00:00"))
    forged = client(app)
    forged.cookies.set("reigel_team_enroll", "forged", path="/api/team-identity/totp")
    assert forged.post("/api/team-identity/totp/enroll").status_code == 409
    assert secret_for(app.state.store, consultant["email"]) == secret


def test_old_sessions_without_totp_grant_no_access(world):
    app, _, _, consultant, _ = world
    with sqlite3.connect(app.state.store.path) as db:
        db.execute("INSERT INTO sessions VALUES(?,?,?)",
                   (hashlib.sha256(b"legacy-session").hexdigest(), consultant["id"], "2999-01-01T00:00:00+00:00"))
    legacy = client(app)
    legacy.cookies.set(COOKIE, "legacy-session")
    for path in ("/api/auth/me", "/api/leads", "/api/team-identity/me"):
        assert legacy.get(path).status_code == 401
    assert legacy.get("/api/ia/bootstrap").json()["owner"] == "visitor"
    # Only after the person enrolls does that account have access again.
    enrolled_secret(app, consultant["email"])
    assert legacy.get("/api/auth/me").status_code == 200


def test_legacy_scrypt_password_keeps_working_and_upgrades(world):
    app, _, _, consultant, _ = world
    salt = bytes(16)
    digest = hashlib.scrypt(PASSWORD.encode(), salt=salt, n=16384, r=8, p=1)
    with sqlite3.connect(app.state.store.path) as db:
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (f"scrypt${salt.hex()}${digest.hex()}", consultant["id"]))
    assert client(app).post("/api/auth/login", json={"email": consultant["email"], "password": PASSWORD}).status_code == 200
    with sqlite3.connect(app.state.store.path) as db:
        encoded = db.execute("SELECT password_hash FROM users WHERE id=?", (consultant["id"],)).fetchone()[0]
    assert encoded.startswith("$argon2id$") and password_matches(PASSWORD, encoded)


def test_migration_preserves_existing_team_rows(world):
    app, *_ = world
    with sqlite3.connect(app.state.store.path) as db:
        before = db.execute("SELECT id,email,role,password_hash FROM users ORDER BY id").fetchall()
    create_app(app.state.store.path)
    with sqlite3.connect(app.state.store.path) as db:
        assert db.execute("SELECT id,email,role,password_hash FROM users ORDER BY id").fetchall() == before
        assert db.execute("SELECT 1 FROM schema_migrations WHERE version='reigel_identity_v1'").fetchone()
