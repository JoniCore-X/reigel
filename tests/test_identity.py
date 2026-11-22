import hashlib
import json
import secrets
import sqlite3
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from reigel.api import COOKIE, create_app
from reigel.core import password_matches
from reigel.identity_api import CUSTOMER_COOKIE
from reigel.webauthn import b64url, from_b64url

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


def cbor(value):
    def head(major, number):
        if number < 24:
            return bytes([major << 5 | number])
        if number < 256:
            return bytes([major << 5 | 24, number])
        return bytes([major << 5 | 25]) + number.to_bytes(2, "big")
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        return head(3, len(value.encode())) + value.encode()
    return head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())


class Authenticator:
    def __init__(self, rp_id="localhost", origin=BASE):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(32)
        self.count = 0
        self.rp_id, self.origin = rp_id, origin
        self.handle = None

    def cose(self):
        numbers = self.key.public_key().public_numbers()
        return cbor({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def client(self, kind, challenge):
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}).encode()

    def create(self, options, flags=0x45):
        self.handle = options["user"]["id"]
        attested = bytes(16) + len(self.credential_id).to_bytes(2, "big") + self.credential_id + self.cose()
        data = hashlib.sha256(self.rp_id.encode()).digest() + bytes([flags]) + (0).to_bytes(4, "big") + attested
        attestation = cbor({"fmt": "none", "attStmt": {}, "authData": data})
        cid = b64url(self.credential_id)
        return {"id": cid, "rawId": cid, "type": "public-key", "response": {
            "clientDataJSON": b64url(self.client("webauthn.create", options["challenge"])), "attestationObject": b64url(attestation), "transports": ["internal"]}}

    def get(self, options, flags=0x05, count=None):
        self.count = self.count + 1 if count is None else count
        data = hashlib.sha256(self.rp_id.encode()).digest() + bytes([flags]) + self.count.to_bytes(4, "big")
        client = self.client("webauthn.get", options["challenge"])
        signature = self.key.sign(data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        cid = b64url(self.credential_id)
        return {"id": cid, "rawId": cid, "type": "public-key", "response": {
            "clientDataJSON": b64url(client), "authenticatorData": b64url(data), "signature": b64url(signature), "userHandle": self.handle}}


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
    admin = store.create_user({"name": "Admin", "email": "admin@example.test", "password": PASSWORD, "role": "admin"}, owner)
    consultant = store.create_user({"name": "Consultor", "email": "consultor@example.test", "password": PASSWORD, "role": "advisor"}, owner)
    other = store.create_user({"name": "Otro", "email": "otro@example.test", "password": PASSWORD, "role": "advisor"}, owner)
    return app, owner, admin, consultant, other


def client(app):
    return TestClient(app, base_url=BASE)


def team_login(app, email):
    browser = client(app)
    response = browser.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
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


def enroll(browser, authenticator=None, label="Laptop"):
    authenticator = authenticator or Authenticator()
    options = browser.post("/api/team-identity/passkeys/register/options", json={}).json()["publicKey"]
    response = browser.post("/api/team-identity/passkeys/register/verify", json={"credential": authenticator.create(options), "label": label})
    assert response.status_code == 201, response.text
    return authenticator, response.json()["passkey"]


def passkey_login(app, authenticator, **kwargs):
    browser = client(app)
    options = browser.post("/api/team-identity/passkeys/login/options", json={}).json()["publicKey"]
    return browser, browser.post("/api/team-identity/passkeys/login/verify", json={"credential": authenticator.get(options, **kwargs)})


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
    assert hashlib.sha256(seen["token"]["code_verifier"][0].encode()).digest() == from_b64url(query["code_challenge"][0])
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
    denied = browser.post("/api/team-identity/passkeys/register/options", json={"email": "consultor@example.test", "code": "inventado"})
    assert denied.status_code == 401


def test_passkey_login_replaces_password_for_that_account(world):
    app, _, _, consultant, _ = world
    browser = team_login(app, consultant["email"])
    authenticator, passkey = enroll(browser)
    assert passkey["status"] == "approved"
    assert client(app).post("/api/auth/login", json={"email": consultant["email"], "password": PASSWORD}).status_code == 403
    session, response = passkey_login(app, authenticator)
    assert response.status_code == 200 and response.json()["user"]["id"] == consultant["id"]
    assert session.get("/api/auth/me").json()["user"]["id"] == consultant["id"]


@pytest.mark.parametrize("change", ["origin", "rp", "no_uv"])
def test_passkey_rejects_wrong_origin_rp_or_missing_verification(world, change):
    app, _, _, consultant, _ = world
    browser = team_login(app, consultant["email"])
    authenticator, _ = enroll(browser)
    kwargs = {}
    if change == "origin":
        authenticator.origin = "https://evil.example"
    elif change == "rp":
        authenticator.rp_id = "evil.example"
    else:
        kwargs["flags"] = 0x01
    assert passkey_login(app, authenticator, **kwargs)[1].status_code == 401


def test_challenge_is_single_use_and_counter_regression_revokes(world):
    app, _, _, consultant, _ = world
    team = team_login(app, consultant["email"])
    authenticator, _ = enroll(team)
    browser = client(app)
    options = browser.post("/api/team-identity/passkeys/login/options", json={}).json()["publicKey"]
    assertion = authenticator.get(options)
    challenge = browser.cookies.get("reigel_webauthn")
    assert browser.post("/api/team-identity/passkeys/login/verify", json={"credential": assertion}).status_code == 200
    replay = client(app)
    replay.cookies.set("reigel_webauthn", challenge, path="/api/team-identity/passkeys")
    assert replay.post("/api/team-identity/passkeys/login/verify", json={"credential": assertion}).status_code == 401
    assert passkey_login(app, authenticator, count=1)[1].status_code == 401
    assert passkey_login(app, authenticator)[1].status_code == 401


def test_additional_device_needs_authorized_approval(world):
    app, owner, admin, consultant, other = world
    browser = team_login(app, consultant["email"])
    first, _ = enroll(browser)
    second, pending = enroll(browser, label="Teléfono")
    assert pending["status"] == "pending"
    assert passkey_login(app, second)[1].status_code == 401
    assert browser.post(f"/api/team-identity/devices/{pending['id']}/decision", json={"approve": True}).status_code == 403
    peer = team_login(app, other["email"])
    assert peer.get("/api/team-identity/devices/pending").status_code == 403
    assert peer.post(f"/api/team-identity/devices/{pending['id']}/decision", json={"approve": True}).status_code == 403
    administrator = team_login(app, admin["email"])
    assert administrator.put(f"/api/team-identity/users/{other['id']}/role", json={"role": "supervisor"}).status_code == 200
    assert [item["id"] for item in peer.get("/api/team-identity/devices/pending").json()["items"]] == [pending["id"]]
    assert peer.post(f"/api/team-identity/devices/{pending['id']}/decision", json={"approve": True}).status_code == 200
    assert passkey_login(app, second)[1].status_code == 200
    assert passkey_login(app, first)[1].status_code == 200


def test_supervisor_gains_no_admin_or_data_privileges(world):
    app, _, admin, consultant, other = world
    administrator = team_login(app, admin["email"])
    administrator.put(f"/api/team-identity/users/{other['id']}/role", json={"role": "supervisor"})
    supervisor = team_login(app, other["email"])
    assert supervisor.get("/api/auth/me").json()["user"]["role"] == "advisor"
    assert supervisor.post(f"/api/team-identity/users/{consultant['id']}/grant", json={"purpose": "recovery", "reason": "x"}).status_code == 403
    assert supervisor.put(f"/api/team-identity/users/{consultant['id']}/role", json={"role": "supervisor"}).status_code == 403
    assert supervisor.put(f"/api/team-identity/users/{other['id']}/role", json={"role": "administrador"}).status_code == 403
    assert supervisor.put("/api/team-identity/policy", json={"passkey_required": True}).status_code == 403


def test_recovery_is_admin_only_audited_single_use_and_replaces_keys(world):
    app, owner, admin, consultant, _ = world
    team = team_login(app, consultant["email"])
    lost, _ = enroll(team)
    administrator = team_login(app, admin["email"])
    assert administrator.post(f"/api/team-identity/users/{admin['id']}/grant", json={"purpose": "recovery", "reason": "propio"}).status_code == 403
    assert administrator.post(f"/api/team-identity/users/{owner['id']}/grant", json={"purpose": "recovery", "reason": "dueño"}).status_code == 403
    issued = administrator.post(f"/api/team-identity/users/{consultant['id']}/grant", json={"purpose": "recovery", "reason": "teléfono perdido"})
    code = issued.json()["code"]
    device = client(app)
    wrong = device.post("/api/team-identity/passkeys/register/options", json={"email": "otro@example.test", "code": code})
    assert wrong.status_code == 401
    options = device.post("/api/team-identity/passkeys/register/options", json={"email": consultant["email"], "code": code}).json()["publicKey"]
    fresh = Authenticator()
    saved = device.post("/api/team-identity/passkeys/register/verify", json={"credential": fresh.create(options), "label": "Nuevo", "with_code": True})
    assert saved.status_code == 201 and saved.json()["passkey"]["status"] == "approved"
    assert team.get("/api/auth/me").status_code == 401
    assert passkey_login(app, lost)[1].status_code == 401
    assert passkey_login(app, fresh)[1].status_code == 200
    assert client(app).post("/api/team-identity/passkeys/register/options", json={"email": consultant["email"], "code": code}).status_code == 401
    with sqlite3.connect(app.state.store.path) as db:
        actions = {row[0] for row in db.execute("SELECT action FROM identity_audit WHERE realm='team'")}
        stored = db.execute("SELECT token_hash FROM team_access_grants").fetchone()[0]
    assert {"team.grant_issued.recovery", "team.recovery_completed"} <= actions
    assert stored != code


def test_policy_blocks_password_only_accounts_without_locking_out_owner(world):
    app, owner, _, consultant, _ = world
    owner_browser = team_login(app, owner["email"])
    assert owner_browser.put("/api/team-identity/policy", json={"passkey_required": True}).status_code == 409
    enroll(owner_browser)
    assert owner_browser.put("/api/team-identity/policy", json={"passkey_required": True}).status_code == 200
    assert client(app).post("/api/auth/login", json={"email": consultant["email"], "password": PASSWORD}).status_code == 403


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
