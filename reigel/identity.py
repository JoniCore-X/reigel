"""R.E.I.G.E.L. Identity: independent customer and Team Caguas authentication realms."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import totp
from .core import DomainError, email_address, missing_password_hash, now, password_hash, password_matches, stamp, text, uid

CUSTOMER_SESSION_DAYS = 14
CODE_MINUTES = 15
CODE_ATTEMPTS = 5
GRANT_MINUTES = 60
MFA_MINUTES = 5
TOTP_SETUP_MINUTES = 10
TOTP_ATTEMPTS = 5
TOTP_LOCK_MINUTES = 15
ENROLL_MINUTES = 10
OAUTH_MINUTES = 10
USERNAME = re.compile(r"^[a-z][a-z0-9_.]{2,29}$")
PHONE = re.compile(r"^\+[1-9]\d{7,14}$")
RESERVED = {"admin", "administrador", "root", "soporte", "support", "reigel", "powersolar", "team", "teamcaguas"}
TEAM_ROLES = {"administrador", "supervisor", "consultor"}
# Google Authenticator is mandatory for every team account, with no switch to turn it off.
# The former "team_totp_required" setting row is left untouched in old databases and ignored.

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
CREATE TABLE IF NOT EXISTS team_roles (
 user_id TEXT PRIMARY KEY REFERENCES users(id), team_role TEXT NOT NULL CHECK(team_role IN ('administrador','supervisor','consultor')), updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_totp (
 user_id TEXT PRIMARY KEY REFERENCES users(id), secret_nonce BLOB NOT NULL, secret_cipher BLOB NOT NULL, last_step INTEGER NOT NULL DEFAULT -1,
 failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until TEXT, confirmed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_totp_setups (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE REFERENCES users(id), grant_id TEXT REFERENCES team_access_grants(id),
 secret_nonce BLOB NOT NULL, secret_cipher BLOB NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_mfa_challenges (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_enroll_challenges (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_access_grants (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), purpose TEXT NOT NULL CHECK(purpose IN ('enroll','recovery')),
 token_hash TEXT NOT NULL UNIQUE, issued_by TEXT, reason TEXT NOT NULL, expires_at TEXT NOT NULL, consumed_at TEXT, created_at TEXT NOT NULL
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
    # Roles assigned while passkeys existed stay valid; old passkey tables are left untouched.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='team_identities'").fetchone():
        db.execute("INSERT OR IGNORE INTO team_roles SELECT user_id,team_role,updated_at FROM team_identities")
    db.execute("INSERT OR IGNORE INTO schema_migrations VALUES('reigel_identity_totp_v2',?)", (stamp(),))
    db.execute("INSERT OR IGNORE INTO schema_migrations VALUES('reigel_identity_totp_mandatory_v3',?)", (stamp(),))


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
        self._totp_key = None

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
    def _cipher(self) -> AESGCM:
        """The key lives outside the database, so a copy of the database cannot read secrets."""
        if self._totp_key is None:
            configured = os.environ.get("REIGEL_TOTP_KEY", "").strip()
            if configured:
                key = base64.urlsafe_b64decode(configured + "=" * (-len(configured) % 4))
            else:
                path = Path(f"{self.store.path}.totp.key")
                try:
                    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(secrets.token_bytes(32))
                except FileExistsError:
                    pass
                key = path.read_bytes()
            if len(key) != 32:
                raise DomainError("La protección de códigos no está configurada correctamente.", 503)
            self._totp_key = key
        return AESGCM(self._totp_key)

    def _seal(self, secret: bytes, user_id: str):
        nonce = secrets.token_bytes(12)
        return nonce, self._cipher().encrypt(nonce, secret, user_id.encode())

    def _open(self, nonce: bytes, cipher: bytes, user_id: str) -> bytes:
        try:
            return self._cipher().decrypt(nonce, cipher, user_id.encode())
        except InvalidTag:
            raise DomainError("No se pudo validar el código. Contacta a un administrador.", 503) from None

    @staticmethod
    def _team_row(db, user_id):
        row = db.execute("SELECT * FROM team_roles WHERE user_id=?", (user_id,)).fetchone()
        if row:
            return row
        user = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise DomainError("Usuario no encontrado.", 404)
        role = "administrador" if user["role"] == "admin" else "consultor"
        db.execute("INSERT INTO team_roles VALUES(?,?,?)", (user_id, role, stamp()))
        return db.execute("SELECT * FROM team_roles WHERE user_id=?", (user_id,)).fetchone()

    @classmethod
    def _effective_role(cls, db, user_id) -> str:
        """The core account role always wins, so a stale row can never grant admin."""
        user = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise DomainError("Usuario no encontrado.", 404)
        if user["role"] == "admin":
            return "administrador"
        return "supervisor" if cls._team_row(db, user_id)["team_role"] == "supervisor" else "consultor"

    def team_profile(self, user) -> dict:
        with self.store.connect() as db:
            role = self._effective_role(db, user["id"])
            enabled = db.execute("SELECT confirmed_at FROM team_totp WHERE user_id=?", (user["id"],)).fetchone()
            return {"user": {"id": user["id"], "name": user["name"], "email": user["email"], "team_role": role, "is_owner": bool(user.get("is_owner"))},
                    "totp_enabled": bool(enabled), "totp_confirmed_at": enabled["confirmed_at"] if enabled else None, "totp_required": True}

    def _check_stored_code(self, db, user_id, code):
        """Verify and record the attempt; the caller raises after this transaction commits."""
        row = db.execute("SELECT * FROM team_totp WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None, "invalid"
        if row["locked_until"] and row["locked_until"] > stamp():
            return None, "locked"
        step = totp.matching_step(self._open(row["secret_nonce"], row["secret_cipher"], user_id), code, row["last_step"])
        if step is None:
            failures = row["failed_attempts"] + 1
            locked = later(minutes=TOTP_LOCK_MINUTES) if failures >= TOTP_ATTEMPTS else None
            db.execute("UPDATE team_totp SET failed_attempts=?,locked_until=? WHERE user_id=?", (0 if locked else failures, locked, user_id))
            self.audit(db, "team", user_id, "team.totp_locked" if locked else "team.totp_failed", user_id)
            return None, "locked" if locked else "invalid"
        db.execute("UPDATE team_totp SET last_step=?,failed_attempts=0,locked_until=NULL WHERE user_id=?", (step, user_id))
        return step, ""

    @staticmethod
    def _raise_code_error(reason):
        if reason == "locked":
            raise DomainError("Demasiados códigos incorrectos. Espera 15 minutos o contacta a un administrador.", 429)
        raise DomainError("El código no es correcto.", 401)

    def begin_mfa(self, user_id) -> str:
        ticket = secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute("DELETE FROM team_mfa_challenges WHERE expires_at<? OR user_id=?", (stamp(), user_id))
            db.execute("INSERT INTO team_mfa_challenges VALUES(?,?,?)", (token_hash(ticket), user_id, later(minutes=MFA_MINUTES)))
        return ticket

    def totp_login(self, ticket, code):
        from .core import user_dict
        if not ticket:
            raise DomainError("Vuelve a iniciar sesión.", 401)
        session = None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            challenge = db.execute("SELECT * FROM team_mfa_challenges WHERE token_hash=? AND expires_at>?", (token_hash(ticket), stamp())).fetchone()
            if not challenge or not self._account_allowed(db, challenge["user_id"]):
                reason = "expired"
            else:
                step, reason = self._check_stored_code(db, challenge["user_id"], code)
                if step is not None:
                    db.execute("DELETE FROM team_mfa_challenges WHERE token_hash=?", (token_hash(ticket),))
                    session = self.store.issue_session(db, challenge["user_id"])
                    self.audit(db, "team", challenge["user_id"], "team.totp_login", challenge["user_id"])
                    user = user_dict(db.execute("SELECT * FROM users WHERE id=?", (challenge["user_id"],)).fetchone())
        if reason == "expired":
            raise DomainError("Vuelve a iniciar sesión.", 401)
        if not session:
            self._raise_code_error(reason)
        return session, user

    @staticmethod
    def _account_allowed(db, user_id) -> bool:
        """Active and still on the owner's allowlist (re-checked at every sign-in step)."""
        from . import team_access
        row = db.execute("SELECT email,is_owner FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        return bool(row) and team_access.is_allowed(db, row["email"], owner=bool(row["is_owner"]))

    # First-login enrollment: a correct password for an account without Google
    # Authenticator yields only this short-lived ticket, which can do nothing but
    # register a new authenticator. The session is issued after the first code.
    def begin_enrollment(self, user_id) -> str:
        ticket = secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute("DELETE FROM team_enroll_challenges WHERE expires_at<? OR user_id=?", (stamp(), user_id))
            db.execute("INSERT INTO team_enroll_challenges VALUES(?,?,?)", (token_hash(ticket), user_id, later(minutes=ENROLL_MINUTES)))
            self.audit(db, "team", user_id, "team.enrollment_required", user_id)
        return ticket

    def _enroll_challenge(self, db, ticket):
        if not ticket or len(ticket) > 200:
            return None
        challenge = db.execute("SELECT * FROM team_enroll_challenges WHERE token_hash=? AND expires_at>?", (token_hash(ticket), stamp())).fetchone()
        if not challenge or not self._account_allowed(db, challenge["user_id"]):
            return None
        return challenge

    def enrollment_setup(self, ticket) -> tuple[str, dict]:
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            challenge = self._enroll_challenge(db, ticket)
            if not challenge:
                raise DomainError("Vuelve a iniciar sesión.", 401)
            user_id = challenge["user_id"]
            if db.execute("SELECT 1 FROM team_totp WHERE user_id=?", (user_id,)).fetchone():
                raise DomainError("Esta cuenta ya tiene Google Authenticator. Vuelve a iniciar sesión.", 409)
            account = db.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
            secret, setup_ticket = totp.new_secret(), secrets.token_urlsafe(32)
            nonce, cipher = self._seal(secret, user_id)
            db.execute("DELETE FROM team_totp_setups WHERE user_id=? OR expires_at<?", (user_id, stamp()))
            db.execute("INSERT INTO team_totp_setups VALUES(?,?,?,?,?,?)",
                       (token_hash(setup_ticket), user_id, None, nonce, cipher, later(minutes=TOTP_SETUP_MINUTES)))
        uri = totp.otpauth_uri(secret, account["email"])
        return setup_ticket, {"secret": totp.display_secret(secret), "otpauth_uri": uri, "qr": totp.qr_data_uri(uri), "digits": totp.DIGITS, "period": totp.PERIOD}

    def enrollment_confirm(self, ticket, setup_ticket, code):
        from .core import user_dict
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            challenge = self._enroll_challenge(db, ticket)
            if not challenge:
                raise DomainError("Vuelve a iniciar sesión.", 401)
            user_id = challenge["user_id"]
            setup = db.execute("SELECT * FROM team_totp_setups WHERE token_hash=? AND expires_at>? AND user_id=? AND grant_id IS NULL",
                               (token_hash(setup_ticket or ""), stamp(), user_id)).fetchone()
            if not setup:
                raise DomainError("La configuración venció. Empieza de nuevo.", 401)
            if db.execute("SELECT 1 FROM team_totp WHERE user_id=?", (user_id,)).fetchone():
                # A password alone never replaces an existing authenticator; that takes a recovery grant.
                raise DomainError("Esta cuenta ya tiene Google Authenticator. Vuelve a iniciar sesión.", 409)
            step = totp.matching_step(self._open(setup["secret_nonce"], setup["secret_cipher"], user_id), code)
            if step is None:
                raise DomainError("El código no es correcto. Revisa la hora de tu teléfono.", 401)
            db.execute("INSERT INTO team_totp(user_id,secret_nonce,secret_cipher,last_step,confirmed_at) VALUES(?,?,?,?,?)",
                       (user_id, setup["secret_nonce"], setup["secret_cipher"], step, stamp()))
            db.execute("DELETE FROM team_totp_setups WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM team_enroll_challenges WHERE user_id=?", (user_id,))
            self.audit(db, "team", user_id, "team.totp_enabled", user_id)
            self.store.audit(db, {"id": user_id}, "team.totp_enrolled_at_login", user_id)
            session = self.store.issue_session(db, user_id)
            user = user_dict(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        return session, user

    def _valid_grant(self, db, email, code):
        if not isinstance(code, str) or not code or len(code) > 128:
            return None
        try:
            email = email_address(email, required=True)
        except DomainError:
            return None
        grant = db.execute("""SELECT g.* FROM team_access_grants g JOIN users u ON u.id=g.user_id
                              WHERE g.token_hash=? AND g.consumed_at IS NULL AND g.expires_at>? AND u.email=? COLLATE NOCASE AND u.active=1""",
                           (token_hash(code), stamp(), email)).fetchone()
        return grant if grant and self._account_allowed(db, grant["user_id"]) else None

    def totp_setup(self, user=None, email=None, grant_code=None, current_code=None) -> tuple[str, dict]:
        reason = ""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            grant = None
            if user:
                user_id = user["id"]
                if db.execute("SELECT 1 FROM team_totp WHERE user_id=?", (user_id,)).fetchone():
                    step, reason = self._check_stored_code(db, user_id, current_code)
            else:
                grant = self._valid_grant(db, email, grant_code)
                if not grant:
                    raise DomainError("El código de registro no es válido o venció.", 401)
                user_id = grant["user_id"]
                if grant["purpose"] == "enroll" and db.execute("SELECT 1 FROM team_totp WHERE user_id=?", (user_id,)).fetchone():
                    raise DomainError("Esta cuenta ya tiene Google Authenticator. Solicita un código de recuperación.", 409)
            if not reason:
                account = db.execute("SELECT email FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
                if not account:
                    raise DomainError("Usuario no encontrado.", 404)
                secret, ticket = totp.new_secret(), secrets.token_urlsafe(32)
                nonce, cipher = self._seal(secret, user_id)
                db.execute("DELETE FROM team_totp_setups WHERE user_id=? OR expires_at<?", (user_id, stamp()))
                db.execute("INSERT INTO team_totp_setups VALUES(?,?,?,?,?,?)",
                           (token_hash(ticket), user_id, grant["id"] if grant else None, nonce, cipher, later(minutes=TOTP_SETUP_MINUTES)))
        if reason:
            self._raise_code_error(reason)
        uri = totp.otpauth_uri(secret, account["email"])
        return ticket, {"secret": totp.display_secret(secret), "otpauth_uri": uri, "qr": totp.qr_data_uri(uri), "digits": totp.DIGITS, "period": totp.PERIOD}

    def totp_confirm(self, ticket, code, session_user=None) -> dict:
        if not ticket:
            raise DomainError("La configuración venció. Empieza de nuevo.", 401)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            setup = db.execute("SELECT * FROM team_totp_setups WHERE token_hash=? AND expires_at>?", (token_hash(ticket), stamp())).fetchone()
            if not setup or (session_user and setup["user_id"] != session_user["id"]) or (not session_user and not setup["grant_id"]):
                raise DomainError("La configuración venció. Empieza de nuevo.", 401)
            secret = self._open(setup["secret_nonce"], setup["secret_cipher"], setup["user_id"])
            step = totp.matching_step(secret, code)
            if step is None:
                raise DomainError("El código no es correcto. Revisa la hora de tu teléfono.", 401)
            current = stamp()
            if setup["grant_id"]:
                grant = db.execute("SELECT * FROM team_access_grants WHERE id=? AND consumed_at IS NULL AND expires_at>?", (setup["grant_id"], current)).fetchone()
                if not grant:
                    raise DomainError("El código de registro no es válido o venció.", 401)
                db.execute("UPDATE team_access_grants SET consumed_at=? WHERE id=?", (current, grant["id"]))
                if grant["purpose"] == "recovery":
                    db.execute("DELETE FROM sessions WHERE user_id=?", (setup["user_id"],))
                    db.execute("DELETE FROM team_mfa_challenges WHERE user_id=?", (setup["user_id"],))
                    self.audit(db, "team", grant["issued_by"], "team.recovery_completed", setup["user_id"])
            db.execute("""INSERT INTO team_totp(user_id,secret_nonce,secret_cipher,last_step,confirmed_at) VALUES(?,?,?,?,?)
                          ON CONFLICT(user_id) DO UPDATE SET secret_nonce=excluded.secret_nonce,secret_cipher=excluded.secret_cipher,
                          last_step=excluded.last_step,failed_attempts=0,locked_until=NULL,confirmed_at=excluded.confirmed_at""",
                       (setup["user_id"], setup["secret_nonce"], setup["secret_cipher"], step, current))
            db.execute("DELETE FROM team_totp_setups WHERE user_id=?", (setup["user_id"],))
            self.audit(db, "team", setup["user_id"], "team.totp_enabled", setup["user_id"])
        return {"totp_enabled": True}

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
        db.execute("INSERT INTO team_access_grants VALUES(?,?,?,?,?,?,?,?,?)", (uid(), user_id, purpose, token_hash(code), issuer, reason, expires, None, current))
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
            db.execute("UPDATE team_roles SET team_role=?,updated_at=? WHERE user_id=?", (role, stamp(), user_id))
            self.audit(db, "team", actor["id"], f"team.role_set.{role}", user_id)
        return {"id": user_id, "team_role": role}
