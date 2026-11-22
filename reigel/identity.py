"""R.E.I.G.E.L. Identity: independent customer and Team Caguas authentication realms."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from datetime import timedelta
from urllib.parse import urlencode

import httpx

from . import webauthn
from .core import DomainError, email_address, missing_password_hash, now, password_hash, password_matches, stamp, text, uid

CUSTOMER_SESSION_DAYS = 14
CODE_MINUTES = 15
CODE_ATTEMPTS = 5
GRANT_MINUTES = 60
CHALLENGE_MINUTES = 5
OAUTH_MINUTES = 10
USERNAME = re.compile(r"^[a-z][a-z0-9_.]{2,29}$")
PHONE = re.compile(r"^\+[1-9]\d{7,14}$")
RESERVED = {"admin", "administrador", "root", "soporte", "support", "reigel", "powersolar", "team", "teamcaguas"}
TEAM_ROLES = {"administrador", "supervisor", "consultor"}
POLICY_KEY = "team_passkey_required"

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, display_name TEXT NOT NULL DEFAULT '',
 password_hash TEXT, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_identifiers (
 id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
 kind TEXT NOT NULL CHECK(kind IN ('email','phone')), value TEXT NOT NULL, verified_at TEXT, created_at TEXT NOT NULL,
 UNIQUE(customer_id, kind, value)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_identifier_verified ON customer_identifiers(kind, value) WHERE verified_at IS NOT NULL;
CREATE TABLE IF NOT EXISTS customer_sessions (
 token_hash TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id), created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_codes (
 id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id), identifier_id TEXT NOT NULL REFERENCES customer_identifiers(id),
 purpose TEXT NOT NULL CHECK(purpose IN ('verify','recover')), salt TEXT NOT NULL, code_hash TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, expires_at TEXT NOT NULL, consumed_at TEXT
);
CREATE TABLE IF NOT EXISTS customer_oauth_accounts (
 id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id), provider TEXT NOT NULL, subject TEXT NOT NULL,
 display_name TEXT NOT NULL DEFAULT '', linked_at TEXT NOT NULL, UNIQUE(provider, subject), UNIQUE(customer_id, provider)
);
CREATE TABLE IF NOT EXISTS customer_oauth_states (
 state_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('login','link')),
 customer_id TEXT REFERENCES customers(id), verifier TEXT NOT NULL, binding_hash TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commerce_products (
 id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commerce_plans (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES commerce_products(id), code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 billing_interval TEXT NOT NULL CHECK(billing_interval IN ('once','month','year')), amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
 currency TEXT NOT NULL DEFAULT 'USD', active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_subscriptions (
 id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id), plan_id TEXT NOT NULL REFERENCES commerce_plans(id),
 status TEXT NOT NULL CHECK(status IN ('trialing','active','past_due','canceled','expired')), provider TEXT NOT NULL DEFAULT '',
 provider_reference TEXT NOT NULL DEFAULT '', current_period_end TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_purchases (
 id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id), plan_id TEXT NOT NULL REFERENCES commerce_plans(id),
 status TEXT NOT NULL CHECK(status IN ('pending','paid','refunded','failed')), amount_cents INTEGER NOT NULL, currency TEXT NOT NULL,
 provider TEXT NOT NULL DEFAULT '', provider_reference TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_entitlements (
 id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id), product_id TEXT NOT NULL REFERENCES commerce_products(id),
 permission TEXT NOT NULL, source TEXT NOT NULL, expires_at TEXT, created_at TEXT NOT NULL, UNIQUE(customer_id, product_id, permission)
);
CREATE TABLE IF NOT EXISTS team_identities (
 user_id TEXT PRIMARY KEY REFERENCES users(id), team_role TEXT NOT NULL CHECK(team_role IN ('administrador','supervisor','consultor')),
 webauthn_handle TEXT NOT NULL UNIQUE, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_passkeys (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), credential_id TEXT NOT NULL UNIQUE, public_key BLOB NOT NULL,
 sign_count INTEGER NOT NULL DEFAULT 0, transports TEXT NOT NULL DEFAULT '[]', label TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('pending','approved','revoked')), approved_by TEXT, approved_at TEXT, last_used_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_access_grants (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), purpose TEXT NOT NULL CHECK(purpose IN ('enroll','recovery')),
 token_hash TEXT NOT NULL UNIQUE, issued_by TEXT, reason TEXT NOT NULL, expires_at TEXT NOT NULL, consumed_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webauthn_challenges (
 id TEXT PRIMARY KEY, purpose TEXT NOT NULL CHECK(purpose IN ('register','login')), user_id TEXT REFERENCES users(id),
 grant_id TEXT REFERENCES team_access_grants(id), challenge_hash TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS identity_audit (
 id TEXT PRIMARY KEY, realm TEXT NOT NULL CHECK(realm IN ('customer','team')), actor_id TEXT, action TEXT NOT NULL, subject_id TEXT, created_at TEXT NOT NULL
);
"""

PROVIDERS = {
    "google": {"label": "Google", "authorize": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
               "userinfo": "https://openidconnect.googleapis.com/v1/userinfo", "scope": "openid profile", "pkce": True, "client_param": "client_id"},
    "facebook": {"label": "Facebook", "authorize": "https://www.facebook.com/v23.0/dialog/oauth", "token": "https://graph.facebook.com/v23.0/oauth/access_token",
                 "userinfo": "https://graph.facebook.com/v23.0/me?fields=id,name", "scope": "public_profile", "pkce": False, "client_param": "client_id"},
    "x": {"label": "X", "authorize": "https://x.com/i/oauth2/authorize", "token": "https://api.x.com/2/oauth2/token",
          "userinfo": "https://api.x.com/2/users/me", "scope": "users.read tweet.read", "pkce": True, "client_param": "client_id", "basic": True},
    "tiktok": {"label": "TikTok", "authorize": "https://www.tiktok.com/v2/auth/authorize/", "token": "https://open.tiktokapis.com/v2/oauth/token/",
               "userinfo": "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name", "scope": "user.info.basic", "pkce": False, "client_param": "client_key"},
}


def migrate_identity(db) -> None:
    """Additive only: creates new tables and never rewrites existing rows."""
    db.executescript(SCHEMA)
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY,applied_at TEXT NOT NULL)")
    db.execute("INSERT OR IGNORE INTO schema_migrations VALUES('reigel_identity_v1',?)", (stamp(),))


def token_hash(token) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def csrf_for(token: str) -> str:
    """One-way value bound to a session; a page must read it through the API."""
    return hashlib.sha256(b"reigel-csrf:" + (token or "").encode()).hexdigest()


def later(**delta) -> str:
    return (now() + timedelta(**delta)).isoformat()


def phone_number(value, *, required=False) -> str:
    if not isinstance(value, str) or not value.strip():
        if required:
            raise DomainError("Escribe un teléfono válido.", 422)
        return ""
    clean = re.sub(r"[\s().-]", "", value)
    if re.fullmatch(r"\d{10}", clean):
        clean = "+1" + clean
    elif re.fullmatch(r"1\d{10}", clean):
        clean = "+" + clean
    if not PHONE.fullmatch(clean):
        raise DomainError("Escribe un teléfono válido, con código de país si no es de EE. UU. o Puerto Rico.", 422)
    return clean


def identifier_kind(value: str) -> str:
    if "@" in value:
        return "email"
    return "phone" if re.fullmatch(r"[+\d\s().-]{8,24}", value) else "username"


def password_login_block(db, user_id: str) -> str:
    """Return the reason a correct Team password may not open a session."""
    if db.execute("SELECT 1 FROM team_passkeys WHERE user_id=? AND status='approved' LIMIT 1", (user_id,)).fetchone():
        return "Esta cuenta entra con su llave de acceso."
    row = db.execute("SELECT value FROM settings WHERE key=?", (POLICY_KEY,)).fetchone()
    if row and row["value"] == "1":
        return "El equipo requiere llave de acceso. Solicita a un administrador un código de registro."
    return ""


class NoDelivery:
    """No channel is active until the owner explicitly configures and authorizes one."""

    def available(self, kind: str) -> bool:
        return False

    def send(self, kind: str, destination: str, code: str, purpose: str) -> bool:
        return False


class Identity:
    def __init__(self, store, delivery=None):
        self.store = store
        self.delivery = delivery or NoDelivery()

    @staticmethod
    def audit(db, realm, actor_id, action, subject_id=None):
        db.execute("INSERT INTO identity_audit VALUES(?,?,?,?,?,?)", (uid(), realm, actor_id, action, subject_id, stamp()))

    # Customer realm -------------------------------------------------------
    @staticmethod
    def _customer_public(db, row) -> dict:
        identifiers = [{"id": r["id"], "kind": r["kind"], "value": r["value"], "verified": bool(r["verified_at"])}
                       for r in db.execute("SELECT * FROM customer_identifiers WHERE customer_id=? ORDER BY created_at,id", (row["id"],))]
        providers = [{"provider": r["provider"], "label": PROVIDERS.get(r["provider"], {}).get("label", r["provider"]), "linked_at": r["linked_at"]}
                     for r in db.execute("SELECT provider,linked_at FROM customer_oauth_accounts WHERE customer_id=? ORDER BY linked_at", (row["id"],))]
        return {"id": row["id"], "username": row["username"], "display_name": row["display_name"], "has_password": bool(row["password_hash"]),
                "identifiers": identifiers, "providers": providers}

    def _session(self, db, customer_id) -> str:
        token = secrets.token_urlsafe(36)
        db.execute("DELETE FROM customer_sessions WHERE expires_at<?", (stamp(),))
        db.execute("INSERT INTO customer_sessions VALUES(?,?,?,?)", (token_hash(token), customer_id, stamp(), later(days=CUSTOMER_SESSION_DAYS)))
        return token

    def register(self, data):
        username = data.get("username")
        username = username.strip().lower() if isinstance(username, str) else ""
        if not USERNAME.fullmatch(username) or username in RESERVED:
            raise DomainError("Usa un usuario de 3 a 30 caracteres: letras, números, punto o guion bajo, empezando por letra.", 422)
        email = email_address(data.get("email")) if data.get("email") else ""
        phone = phone_number(data.get("phone"))
        if not email and not phone:
            raise DomainError("Añade un correo o un teléfono.", 422)
        display = text(data.get("display_name"), "nombre", limit=100) or username
        encoded = password_hash(data.get("password", ""))
        customer_id, current = uid(), stamp()
        try:
            with self.store.connect() as db:
                db.execute("INSERT INTO customers(id,username,display_name,password_hash,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                           (customer_id, username, display, encoded, current, current))
                for kind, value in (("email", email.casefold()), ("phone", phone)):
                    if value:
                        db.execute("INSERT INTO customer_identifiers(id,customer_id,kind,value,created_at) VALUES(?,?,?,?,?)", (uid(), customer_id, kind, value, current))
                self.audit(db, "customer", customer_id, "customer.register", customer_id)
                token = self._session(db, customer_id)
                row = db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
                return token, self._customer_public(db, row)
        except sqlite3.IntegrityError:
            raise DomainError("Ese nombre de usuario no está disponible.", 409) from None

    @staticmethod
    def _find_customer(db, identifier):
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 254:
            return None, None
        value = identifier.strip()
        kind = identifier_kind(value)
        try:
            if kind == "username":
                return db.execute("SELECT * FROM customers WHERE username=? COLLATE NOCASE AND status='active'", (value.lower(),)).fetchone(), None
            normalized = email_address(value, required=True).casefold() if kind == "email" else phone_number(value, required=True)
        except DomainError:
            return None, None
        found = db.execute("SELECT id,customer_id FROM customer_identifiers WHERE kind=? AND value=? AND verified_at IS NOT NULL", (kind, normalized)).fetchone()
        if not found:
            return None, None
        return db.execute("SELECT * FROM customers WHERE id=? AND status='active'", (found["customer_id"],)).fetchone(), found["id"]

    def login(self, identifier, password):
        with self.store.connect() as db:
            row, _ = self._find_customer(db, identifier)
            encoded = row["password_hash"] if row and row["password_hash"] else missing_password_hash()
            matched = password_matches(password, encoded)
            if not row or not row["password_hash"] or not matched:
                raise DomainError("Los datos de acceso no son correctos.", 401)
            token = self._session(db, row["id"])
            self.audit(db, "customer", row["id"], "customer.login", row["id"])
            return token, self._customer_public(db, row)

    def session_customer(self, token) -> dict:
        if not token or len(token) > 200:
            raise DomainError("Inicia sesión para continuar.", 401)
        with self.store.connect() as db:
            row = db.execute("SELECT c.* FROM customers c JOIN customer_sessions s ON s.customer_id=c.id WHERE s.token_hash=? AND s.expires_at>? AND c.status='active'",
                             (token_hash(token), stamp())).fetchone()
            if not row:
                raise DomainError("La sesión terminó. Vuelve a iniciar sesión.", 401)
            return self._customer_public(db, row)

    def logout(self, token):
        with self.store.connect() as db:
            db.execute("DELETE FROM customer_sessions WHERE token_hash=?", (token_hash(token),))

    def _issue_code(self, db, customer_id, identifier_id, purpose) -> str:
        db.execute("UPDATE customer_codes SET consumed_at=? WHERE customer_id=? AND purpose=? AND consumed_at IS NULL", (stamp(), customer_id, purpose))
        code, salt = f"{secrets.randbelow(10**8):08d}", secrets.token_hex(16)
        db.execute("INSERT INTO customer_codes(id,customer_id,identifier_id,purpose,salt,code_hash,expires_at) VALUES(?,?,?,?,?,?,?)",
                   (uid(), customer_id, identifier_id, purpose, salt, hashlib.sha256((salt + code).encode()).hexdigest(), later(minutes=CODE_MINUTES)))
        return code

    @staticmethod
    def _code_matches(db, customer_id, identifier_id, purpose, code) -> bool:
        row = db.execute("SELECT * FROM customer_codes WHERE customer_id=? AND identifier_id=? AND purpose=? AND consumed_at IS NULL ORDER BY expires_at DESC LIMIT 1",
                         (customer_id, identifier_id, purpose)).fetchone()
        if not row or row["expires_at"] <= stamp() or row["attempts"] >= CODE_ATTEMPTS or not isinstance(code, str):
            return False
        actual = hashlib.sha256((row["salt"] + code.strip()).encode()).hexdigest()
        if not hmac.compare_digest(actual, row["code_hash"]):
            db.execute("UPDATE customer_codes SET attempts=attempts+1 WHERE id=?", (row["id"],))
            return False
        db.execute("UPDATE customer_codes SET consumed_at=? WHERE id=?", (stamp(), row["id"]))
        return True

    def start_verification(self, customer, identifier_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM customer_identifiers WHERE id=? AND customer_id=?", (identifier_id, customer["id"])).fetchone()
            if not row:
                raise DomainError("No encontramos ese dato en tu cuenta.", 404)
            if row["verified_at"]:
                raise DomainError("Ese dato ya está verificado.", 409)
            if not self.delivery.available(row["kind"]):
                raise DomainError("La verificación todavía no está disponible para este canal.", 503)
            code = self._issue_code(db, customer["id"], row["id"], "verify")
            kind, value = row["kind"], row["value"]
        if not self.delivery.send(kind, value, code, "verify"):
            raise DomainError("No se pudo enviar el código. Inténtalo más tarde.", 503)

    def finish_verification(self, customer, identifier_id, code):
        try:
            with self.store.connect() as db:
                matched = self._code_matches(db, customer["id"], identifier_id, "verify", code)
                if matched:
                    db.execute("UPDATE customer_identifiers SET verified_at=? WHERE id=? AND customer_id=?", (stamp(), identifier_id, customer["id"]))
                    self.audit(db, "customer", customer["id"], "customer.identifier_verified", identifier_id)
        except sqlite3.IntegrityError:
            raise DomainError("Ese dato no se puede verificar en esta cuenta.", 409) from None
        if not matched:
            raise DomainError("El código no es válido o venció.", 400)
        return self.customer_by_id(customer["id"])

    def customer_by_id(self, customer_id):
        with self.store.connect() as db:
            return self._customer_public(db, db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone())

    def start_recovery(self, identifier) -> None:
        """Always succeeds for the caller so that accounts cannot be enumerated."""
        pending = None
        if isinstance(identifier, str) and identifier_kind(identifier.strip()) != "username":
            with self.store.connect() as db:
                row, identifier_id = self._find_customer(db, identifier)
                if row and identifier_id:
                    found = db.execute("SELECT kind,value FROM customer_identifiers WHERE id=?", (identifier_id,)).fetchone()
                    if self.delivery.available(found["kind"]):
                        pending = (found["kind"], found["value"], self._issue_code(db, row["id"], identifier_id, "recover"))
                        self.audit(db, "customer", None, "customer.recovery_requested", row["id"])
        if pending:
            self.delivery.send(pending[0], pending[1], pending[2], "recover")

    def finish_recovery(self, identifier, code, new_password) -> None:
        encoded = password_hash(new_password)
        with self.store.connect() as db:
            row, identifier_id = self._find_customer(db, identifier)
            matched = bool(row and identifier_id and self._code_matches(db, row["id"], identifier_id, "recover", code))
            if matched:
                db.execute("UPDATE customers SET password_hash=?,updated_at=? WHERE id=?", (encoded, stamp(), row["id"]))
                db.execute("DELETE FROM customer_sessions WHERE customer_id=?", (row["id"],))
                self.audit(db, "customer", row["id"], "customer.recovery_completed", row["id"])
        if not matched:
            raise DomainError("El código no es válido o venció.", 400)

    def change_password(self, customer, current, new_password, keep_token) -> None:
        encoded = password_hash(new_password)
        with self.store.connect() as db:
            row = db.execute("SELECT password_hash FROM customers WHERE id=?", (customer["id"],)).fetchone()
            if row["password_hash"] and not password_matches(current, row["password_hash"]):
                raise DomainError("La contraseña actual no es correcta.", 401)
            db.execute("UPDATE customers SET password_hash=?,updated_at=? WHERE id=?", (encoded, stamp(), customer["id"]))
            db.execute("DELETE FROM customer_sessions WHERE customer_id=? AND token_hash<>?", (customer["id"], token_hash(keep_token)))
            self.audit(db, "customer", customer["id"], "customer.password_changed", customer["id"])

    def entitlements(self, customer) -> list:
        with self.store.connect() as db:
            rows = db.execute("""SELECT p.slug,p.name,e.permission,e.expires_at FROM customer_entitlements e JOIN commerce_products p ON p.id=e.product_id
                                 WHERE e.customer_id=? AND p.active=1 AND (e.expires_at IS NULL OR e.expires_at>?) ORDER BY p.name,e.permission""", (customer["id"], stamp()))
            return [dict(row) for row in rows]

    # OAuth / OIDC ---------------------------------------------------------
    @staticmethod
    def oauth_credentials(provider):
        if provider not in PROVIDERS:
            return None
        client = os.environ.get(f"REIGEL_OAUTH_{provider.upper()}_CLIENT_ID", "").strip()
        secret = os.environ.get(f"REIGEL_OAUTH_{provider.upper()}_CLIENT_SECRET", "").strip()
        return (client, secret) if client and secret else None

    def enabled_providers(self) -> list:
        return [{"id": key, "label": item["label"]} for key, item in PROVIDERS.items() if self.oauth_credentials(key)]

    def oauth_start(self, provider, mode, customer, redirect_uri):
        credentials = self.oauth_credentials(provider)
        if not credentials:
            raise DomainError("Este proveedor no está disponible.", 404)
        if mode not in {"login", "link"} or (mode == "link") != bool(customer):
            raise DomainError("Solicitud no válida.", 422)
        config = PROVIDERS[provider]
        state, binding, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        with self.store.connect() as db:
            db.execute("DELETE FROM customer_oauth_states WHERE expires_at<?", (stamp(),))
            db.execute("INSERT INTO customer_oauth_states VALUES(?,?,?,?,?,?,?)",
                       (token_hash(state), provider, mode, customer["id"] if customer else None, verifier, token_hash(binding), later(minutes=OAUTH_MINUTES)))
        query = {config["client_param"]: credentials[0], "redirect_uri": redirect_uri, "response_type": "code", "scope": config["scope"], "state": state}
        if config["pkce"]:
            digest = hashlib.sha256(verifier.encode()).digest()
            query |= {"code_challenge": base64.urlsafe_b64encode(digest).rstrip(b"=").decode(), "code_challenge_method": "S256"}
        return f"{config['authorize']}?{urlencode(query)}", binding

    async def oauth_callback(self, provider, code, state, binding, redirect_uri, transport=None):
        credentials = self.oauth_credentials(provider)
        if not credentials or not isinstance(code, str) or not code or not isinstance(state, str) or not binding:
            raise DomainError("No se pudo completar el acceso.", 400)
        with self.store.connect() as db:
            saved = db.execute("DELETE FROM customer_oauth_states WHERE state_hash=? RETURNING *", (token_hash(state),)).fetchone()
        if not saved or saved["provider"] != provider or saved["expires_at"] <= stamp() or not hmac.compare_digest(saved["binding_hash"], token_hash(binding)):
            raise DomainError("No se pudo completar el acceso.", 400)
        subject, name = await self._oauth_profile(provider, credentials, code, saved["verifier"], redirect_uri, transport)
        with self.store.connect() as db:
            linked = db.execute("SELECT customer_id FROM customer_oauth_accounts WHERE provider=? AND subject=?", (provider, subject)).fetchone()
            if saved["mode"] == "link":
                if linked and linked["customer_id"] != saved["customer_id"]:
                    raise DomainError("Esa cuenta externa ya está vinculada a otro perfil.", 409)
                if not linked:
                    if db.execute("SELECT 1 FROM customer_oauth_accounts WHERE customer_id=? AND provider=?", (saved["customer_id"], provider)).fetchone():
                        raise DomainError("Ya tienes una cuenta de este proveedor vinculada.", 409)
                    db.execute("INSERT INTO customer_oauth_accounts VALUES(?,?,?,?,?,?)", (uid(), saved["customer_id"], provider, subject, name, stamp()))
                    self.audit(db, "customer", saved["customer_id"], f"customer.oauth_linked.{provider}", saved["customer_id"])
                return None
            if linked:
                row = db.execute("SELECT * FROM customers WHERE id=? AND status='active'", (linked["customer_id"],)).fetchone()
                if not row:
                    raise DomainError("No se pudo completar el acceso.", 403)
                customer_id = row["id"]
            else:
                # Never merge by matching email, phone or name: a new external identity is a new profile.
                customer_id, current = uid(), stamp()
                username = f"user_{secrets.token_hex(6)}"
                db.execute("INSERT INTO customers(id,username,display_name,password_hash,created_at,updated_at) VALUES(?,?,?,NULL,?,?)",
                           (customer_id, username, name or username, current, current))
                db.execute("INSERT INTO customer_oauth_accounts VALUES(?,?,?,?,?,?)", (uid(), customer_id, provider, subject, name, current))
                self.audit(db, "customer", customer_id, f"customer.oauth_registered.{provider}", customer_id)
            self.audit(db, "customer", customer_id, f"customer.oauth_login.{provider}", customer_id)
            return self._session(db, customer_id)

    @staticmethod
    async def _oauth_profile(provider, credentials, code, verifier, redirect_uri, transport):
        config = PROVIDERS[provider]
        client_id, secret = credentials
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        auth = None
        if config.get("basic"):
            auth = httpx.BasicAuth(client_id, secret)
            form["client_id"] = client_id
        else:
            form |= {config["client_param"]: client_id, "client_secret": secret}
        if config["pkce"]:
            form["code_verifier"] = verifier
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, transport=transport) as client:
                token_response = await client.post(config["token"], data=form, auth=auth, headers={"Accept": "application/json"})
                token_response.raise_for_status()
                access = token_response.json().get("access_token")
                if not isinstance(access, str) or not access:
                    raise ValueError
                # The provider token is used once here and is never persisted.
                profile_response = await client.get(config["userinfo"], headers={"Authorization": f"Bearer {access}", "Accept": "application/json"})
                profile_response.raise_for_status()
                profile = profile_response.json()
        except (httpx.HTTPError, ValueError, AttributeError):
            raise DomainError("No se pudo completar el acceso con el proveedor.", 502) from None
        if provider == "google":
            subject, name = profile.get("sub"), profile.get("name")
        elif provider == "facebook":
            subject, name = profile.get("id"), profile.get("name")
        elif provider == "x":
            data = profile.get("data") or {}
            subject, name = data.get("id"), data.get("name")
        else:
            user = (profile.get("data") or {}).get("user") or {}
            subject, name = user.get("open_id"), user.get("display_name")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise DomainError("No se pudo completar el acceso con el proveedor.", 502)
        return subject, name[:100] if isinstance(name, str) else ""

    def unlink_provider(self, customer, provider) -> dict:
        with self.store.connect() as db:
            row = db.execute("SELECT password_hash FROM customers WHERE id=?", (customer["id"],)).fetchone()
            count = db.execute("SELECT count(*) FROM customer_oauth_accounts WHERE customer_id=?", (customer["id"],)).fetchone()[0]
            if not row["password_hash"] and count <= 1:
                raise DomainError("Crea una contraseña antes de quitar tu único método de acceso.", 409)
            removed = db.execute("DELETE FROM customer_oauth_accounts WHERE customer_id=? AND provider=?", (customer["id"], provider)).rowcount
            if not removed:
                raise DomainError("Ese proveedor no está vinculado.", 404)
            self.audit(db, "customer", customer["id"], f"customer.oauth_unlinked.{provider}", customer["id"])
        return self.customer_by_id(customer["id"])

    # Team realm -----------------------------------------------------------
    @staticmethod
    def _team_row(db, user_id):
        row = db.execute("SELECT * FROM team_identities WHERE user_id=?", (user_id,)).fetchone()
        if row:
            return row
        user = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise DomainError("Usuario no encontrado.", 404)
        role = "administrador" if user["role"] == "admin" else "consultor"
        db.execute("INSERT INTO team_identities VALUES(?,?,?,?)", (user_id, role, webauthn.b64url(secrets.token_bytes(32)), stamp()))
        return db.execute("SELECT * FROM team_identities WHERE user_id=?", (user_id,)).fetchone()

    @classmethod
    def _effective_role(cls, db, user_id) -> str:
        """The core account role always wins, so a stale row can never grant admin."""
        user = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise DomainError("Usuario no encontrado.", 404)
        if user["role"] == "admin":
            return "administrador"
        role = cls._team_row(db, user_id)["team_role"]
        return "supervisor" if role == "supervisor" else "consultor"

    @staticmethod
    def _passkey_public(row) -> dict:
        return {"id": row["id"], "label": row["label"], "status": row["status"], "created_at": row["created_at"], "last_used_at": row["last_used_at"]}

    def team_profile(self, user) -> dict:
        with self.store.connect() as db:
            role = self._effective_role(db, user["id"])
            keys = db.execute("SELECT * FROM team_passkeys WHERE user_id=? AND status<>'revoked' ORDER BY created_at", (user["id"],)).fetchall()
            policy = db.execute("SELECT value FROM settings WHERE key=?", (POLICY_KEY,)).fetchone()
            return {"user": {"id": user["id"], "name": user["name"], "email": user["email"], "team_role": role, "is_owner": bool(user.get("is_owner"))},
                    "passkeys": [self._passkey_public(row) for row in keys], "passkey_required": bool(policy and policy["value"] == "1")}

    def _valid_grant(self, db, email, code):
        if not isinstance(code, str) or not code or len(code) > 128:
            return None
        try:
            email = email_address(email, required=True)
        except DomainError:
            return None
        return db.execute("""SELECT g.* FROM team_access_grants g JOIN users u ON u.id=g.user_id
                             WHERE g.token_hash=? AND g.consumed_at IS NULL AND g.expires_at>? AND u.email=? COLLATE NOCASE AND u.active=1""",
                          (token_hash(code), stamp(), email)).fetchone()

    def register_options(self, rp_id, rp_name, user=None, email=None, code=None):
        with self.store.connect() as db:
            grant = None
            if user:
                user_id = user["id"]
            else:
                grant = self._valid_grant(db, email, code)
                if not grant:
                    raise DomainError("El código de registro no es válido o venció.", 401)
                user_id = grant["user_id"]
            account = db.execute("SELECT id,name,email FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
            if not account:
                raise DomainError("Usuario no encontrado.", 404)
            identity = self._team_row(db, user_id)
            excluded = [] if grant and grant["purpose"] == "recovery" else [
                {"type": "public-key", "id": row["credential_id"]}
                for row in db.execute("SELECT credential_id FROM team_passkeys WHERE user_id=? AND status<>'revoked'", (user_id,))]
            challenge = secrets.token_bytes(32)
            challenge_id = secrets.token_urlsafe(24)
            db.execute("DELETE FROM webauthn_challenges WHERE expires_at<?", (stamp(),))
            db.execute("INSERT INTO webauthn_challenges VALUES(?,?,?,?,?,?)",
                       (token_hash(challenge_id), "register", user_id, grant["id"] if grant else None, hashlib.sha256(challenge).hexdigest(), later(minutes=CHALLENGE_MINUTES)))
            options = {"challenge": webauthn.b64url(challenge), "rp": {"id": rp_id, "name": rp_name},
                       "user": {"id": identity["webauthn_handle"], "name": account["email"], "displayName": account["name"]},
                       "pubKeyCredParams": [{"type": "public-key", "alg": webauthn.ES256}, {"type": "public-key", "alg": webauthn.RS256}],
                       "timeout": 120000, "attestation": "none", "excludeCredentials": excluded,
                       "authenticatorSelection": {"residentKey": "required", "requireResidentKey": True, "userVerification": "required"}}
            return challenge_id, options

    @staticmethod
    def _take_challenge(db, challenge_id, purpose):
        row = db.execute("DELETE FROM webauthn_challenges WHERE id=? AND purpose=? RETURNING *", (token_hash(challenge_id), purpose)).fetchone()
        if not row or row["expires_at"] <= stamp():
            return None
        return row

    def register_finish(self, challenge_id, credential, label, rp_id, origin, session_user=None) -> dict:
        label = text(label, "nombre del dispositivo", limit=60) or "Dispositivo"
        with self.store.connect() as db:
            saved = self._take_challenge(db, challenge_id, "register")
        if not saved or (session_user and saved["user_id"] != session_user["id"]) or (not session_user and not saved["grant_id"]):
            raise webauthn.invalid()
        verified = webauthn.verify_registration(credential, saved["challenge_hash"], rp_id, origin)
        key_id, current = uid(), stamp()
        try:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                grant = None
                if saved["grant_id"]:
                    grant = db.execute("SELECT * FROM team_access_grants WHERE id=? AND consumed_at IS NULL AND expires_at>?", (saved["grant_id"], current)).fetchone()
                    if not grant:
                        raise webauthn.invalid()
                    db.execute("UPDATE team_access_grants SET consumed_at=? WHERE id=?", (current, grant["id"]))
                if not db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (saved["user_id"],)).fetchone():
                    raise webauthn.invalid()
                if grant and grant["purpose"] == "recovery":
                    db.execute("UPDATE team_passkeys SET status='revoked' WHERE user_id=? AND status<>'revoked'", (saved["user_id"],))
                    db.execute("DELETE FROM sessions WHERE user_id=?", (saved["user_id"],))
                    self.audit(db, "team", grant["issued_by"], "team.recovery_completed", saved["user_id"])
                has_approved = db.execute("SELECT 1 FROM team_passkeys WHERE user_id=? AND status='approved' LIMIT 1", (saved["user_id"],)).fetchone()
                status = "pending" if has_approved else "approved"
                db.execute("""INSERT INTO team_passkeys(id,user_id,credential_id,public_key,sign_count,transports,label,status,approved_at,created_at)
                              VALUES(?,?,?,?,?,?,?,?,?,?)""",
                           (key_id, saved["user_id"], verified["credential_id"], verified["public_key"], verified["sign_count"], json.dumps(verified["transports"]),
                            label, status, current if status == "approved" else None, current))
                self.audit(db, "team", saved["user_id"], f"team.passkey_registered.{status}", key_id)
                return self._passkey_public(db.execute("SELECT * FROM team_passkeys WHERE id=?", (key_id,)).fetchone())
        except sqlite3.IntegrityError:
            raise DomainError("Esta llave de acceso ya está registrada.", 409) from None

    def login_options(self, rp_id):
        challenge, challenge_id = secrets.token_bytes(32), secrets.token_urlsafe(24)
        with self.store.connect() as db:
            db.execute("DELETE FROM webauthn_challenges WHERE expires_at<?", (stamp(),))
            db.execute("INSERT INTO webauthn_challenges VALUES(?,?,NULL,NULL,?,?)",
                       (token_hash(challenge_id), "login", hashlib.sha256(challenge).hexdigest(), later(minutes=CHALLENGE_MINUTES)))
        return challenge_id, {"challenge": webauthn.b64url(challenge), "rpId": rp_id, "timeout": 120000, "userVerification": "required", "allowCredentials": []}

    def login_finish(self, challenge_id, credential, rp_id, origin):
        from .core import user_dict
        credential_id = credential.get("rawId") if isinstance(credential, dict) else None
        with self.store.connect() as db:
            saved = self._take_challenge(db, challenge_id, "login")
            key = db.execute("""SELECT k.*,i.webauthn_handle FROM team_passkeys k JOIN team_identities i ON i.user_id=k.user_id JOIN users u ON u.id=k.user_id
                                WHERE k.credential_id=? AND k.status='approved' AND u.active=1""", (credential_id if isinstance(credential_id, str) else "",)).fetchone()
        if not saved or not key:
            raise webauthn.invalid()
        try:
            count = webauthn.verify_assertion(credential, key["public_key"], key["sign_count"], key["webauthn_handle"], saved["challenge_hash"], rp_id, origin)
        except DomainError as error:
            if "bloqueada" in error.detail:
                with self.store.connect() as db:
                    db.execute("UPDATE team_passkeys SET status='revoked' WHERE id=?", (key["id"],))
                    self.audit(db, "team", key["user_id"], "team.passkey_clone_detected", key["id"])
            raise
        token = secrets.token_urlsafe(36)
        with self.store.connect() as db:
            updated = db.execute("UPDATE team_passkeys SET sign_count=?,last_used_at=? WHERE id=? AND status='approved' AND sign_count=?",
                                 (count, stamp(), key["id"], key["sign_count"])).rowcount
            if not updated:
                raise webauthn.invalid()
            db.execute("DELETE FROM sessions WHERE expires_at<?", (stamp(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), key["user_id"], later(hours=12)))
            self.store.audit(db, {"id": key["user_id"]}, "auth.passkey_login", key["user_id"])
            self.audit(db, "team", key["user_id"], "team.passkey_login", key["id"])
            return token, user_dict(db.execute("SELECT * FROM users WHERE id=?", (key["user_id"],)).fetchone())

    def pending_devices(self, actor) -> list:
        with self.store.connect() as db:
            role = self._effective_role(db, actor["id"])
            if role == "consultor":
                raise DomainError("Esta acción requiere supervisión.", 403)
            rows = db.execute("""SELECT k.id,k.label,k.created_at,k.user_id,u.name,u.role FROM team_passkeys k JOIN users u ON u.id=k.user_id
                                 WHERE k.status='pending' AND u.active=1 AND k.user_id<>? ORDER BY k.created_at""", (actor["id"],)).fetchall()
            return [{"id": r["id"], "label": r["label"], "created_at": r["created_at"], "user_id": r["user_id"], "user_name": r["name"], "team_role": self._effective_role(db, r["user_id"])}
                    for r in rows if role == "administrador" and (r["role"] != "admin" or actor.get("is_owner")) or role == "supervisor" and self._effective_role(db, r["user_id"]) == "consultor"]

    def decide_device(self, device_id, approve: bool, actor) -> dict:
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            actor_role = self._effective_role(db, actor["id"])
            row = db.execute("SELECT * FROM team_passkeys WHERE id=? AND status='pending'", (device_id,)).fetchone()
            if not row:
                raise DomainError("Dispositivo no encontrado.", 404)
            target_role = self._effective_role(db, row["user_id"])
            allowed = actor_role == "administrador" and (target_role != "administrador" or actor.get("is_owner")) or actor_role == "supervisor" and target_role == "consultor"
            if row["user_id"] == actor["id"] or not allowed:
                raise DomainError("No puedes decidir sobre este dispositivo.", 403)
            status = "approved" if approve else "revoked"
            db.execute("UPDATE team_passkeys SET status=?,approved_by=?,approved_at=? WHERE id=?", (status, actor["id"], stamp(), device_id))
            self.audit(db, "team", actor["id"], f"team.device_{status}", device_id)
            return self._passkey_public(db.execute("SELECT * FROM team_passkeys WHERE id=?", (device_id,)).fetchone())

    def revoke_own_passkey(self, device_id, actor) -> None:
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM team_passkeys WHERE id=? AND user_id=? AND status<>'revoked'", (device_id, actor["id"])).fetchone()
            if not row:
                raise DomainError("Dispositivo no encontrado.", 404)
            others = db.execute("SELECT count(*) FROM team_passkeys WHERE user_id=? AND status='approved' AND id<>?", (actor["id"], device_id)).fetchone()[0]
            policy = db.execute("SELECT value FROM settings WHERE key=?", (POLICY_KEY,)).fetchone()
            if row["status"] == "approved" and not others and policy and policy["value"] == "1":
                raise DomainError("No puedes quitar tu única llave de acceso.", 409)
            db.execute("UPDATE team_passkeys SET status='revoked' WHERE id=?", (device_id,))
            self.audit(db, "team", actor["id"], "team.passkey_revoked", device_id)

    def issue_grant(self, user_id, purpose, reason, actor) -> dict:
        self.store.require_admin(actor)
        if purpose not in {"enroll", "recovery"}:
            raise DomainError("Tipo de código no válido.", 422)
        reason = text(reason, "motivo", required=True, limit=200)
        if user_id == actor["id"]:
            raise DomainError("Otro administrador debe emitir tu código.", 403)
        with self.store.connect() as db:
            target = db.execute("SELECT id,role,active FROM users WHERE id=?", (user_id,)).fetchone()
            if not target or not target["active"]:
                raise DomainError("Usuario no encontrado.", 404)
            if target["role"] == "admin" and not actor.get("is_owner"):
                raise DomainError("Solo el propietario puede emitir códigos para administradores.", 403)
            return self._create_grant(db, user_id, purpose, reason, actor["id"])

    def _create_grant(self, db, user_id, purpose, reason, issuer) -> dict:
        current = stamp()
        db.execute("UPDATE team_access_grants SET consumed_at=? WHERE user_id=? AND consumed_at IS NULL", (current, user_id))
        code, expires = secrets.token_urlsafe(24), later(minutes=GRANT_MINUTES)
        grant_id = uid()
        db.execute("INSERT INTO team_access_grants VALUES(?,?,?,?,?,?,?,?,?)", (grant_id, user_id, purpose, token_hash(code), issuer, reason, expires, None, current))
        self.audit(db, "team", issuer, f"team.grant_issued.{purpose}", user_id)
        return {"code": code, "expires_at": expires, "purpose": purpose}

    def local_recovery(self, email, reason) -> dict:
        """Operator break-glass, run on the server host; there is no HTTP route for it."""
        email = email_address(email, required=True)
        reason = text(reason, "motivo", required=True, limit=200)
        with self.store.connect() as db:
            target = db.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE AND active=1", (email,)).fetchone()
            if not target:
                raise DomainError("Usuario no encontrado.", 404)
            return self._create_grant(db, target["id"], "recovery", f"local: {reason}", None)

    def set_team_role(self, user_id, role, actor) -> dict:
        self.store.require_admin(actor)
        if role not in {"supervisor", "consultor"}:
            raise DomainError("Rol no válido.", 422)
        if user_id == actor["id"]:
            raise DomainError("No puedes cambiar tu propio rol.", 403)
        with self.store.connect() as db:
            target = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                raise DomainError("Usuario no encontrado.", 404)
            if target["role"] == "admin":
                raise DomainError("Los administradores se gestionan desde Equipo.", 409)
            self._team_row(db, user_id)
            db.execute("UPDATE team_identities SET team_role=?,updated_at=? WHERE user_id=?", (role, stamp(), user_id))
            self.audit(db, "team", actor["id"], f"team.role_set.{role}", user_id)
        return {"id": user_id, "team_role": role}

    def set_passkey_policy(self, required: bool, actor) -> dict:
        self.store.require_owner(actor)
        if not isinstance(required, bool):
            raise DomainError("Valor no válido.", 422)
        with self.store.connect() as db:
            if required and not db.execute("SELECT 1 FROM team_passkeys WHERE user_id=? AND status='approved'", (actor["id"],)).fetchone():
                raise DomainError("Registra primero tu llave de acceso para no quedarte fuera.", 409)
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (POLICY_KEY, "1" if required else "0"))
            self.audit(db, "team", actor["id"], f"team.passkey_policy.{int(required)}")
        return {"passkey_required": required}
