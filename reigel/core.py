"""SQLite-backed domain rules. Bookings serialize availability and creation atomically."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

STAGES = ("nuevo", "contacto_pendiente", "contactado", "calificado", "cita", "cita_realizada",
          "propuesta_preparacion", "propuesta_presentada", "negociacion", "ganado", "perdido")
ROOT = Path(__file__).resolve().parents[1]


class DomainError(ValueError):
    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def now() -> datetime:
    return datetime.now(UTC)


def stamp() -> str:
    return now().isoformat()


def uid() -> str:
    return uuid.uuid4().hex


def text(value, field: str, *, limit: int = 200, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise DomainError(f"El campo {field} debe ser texto.", 422)
    value = value.strip()
    if (required and not value) or len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise DomainError(f"Revisa el campo {field}.", 422)
    return value


def email_address(value, *, required=False) -> str:
    value = text(value, "correo", limit=254, required=required).lower()
    if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise DomainError("Introduce un correo válido.", 422)
    return value


def zone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise DomainError("Zona horaria no válida.", 422) from None


def site_origin(value: str) -> str:
    """Validate an operator-supplied HTTPS origin, including parser/port errors."""
    if not value:
        return ""
    try:
        parsed = urlparse(value)
        port = parsed.port
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or any(c.isspace() for c in value) or (port is not None and port < 1)):
            raise ValueError()
    except (TypeError, ValueError):
        raise DomainError("La dirección pública debe ser un origen HTTPS válido, sin rutas, credenciales ni parámetros.", 422) from None
    return value.rstrip("/")


PASSWORDS = PasswordHasher()
_MISSING_HASH = None


def password_hash(password: str) -> str:
    if not isinstance(password, str) or len(password) < 12 or len(password) > 512:
        raise DomainError("Usa una contraseña de 12 a 512 caracteres.", 422)
    return PASSWORDS.hash(password)


def missing_password_hash() -> str:
    """Keep verification cost equal when an account does not exist."""
    global _MISSING_HASH
    if _MISSING_HASH is None:
        _MISSING_HASH = PASSWORDS.hash(secrets.token_urlsafe(24))
    return _MISSING_HASH


def password_matches(password: str, encoded: str) -> bool:
    try:
        if not isinstance(password, str) or len(password) > 512:
            return False
        if encoded.startswith("$argon2id$"):
            return PASSWORDS.verify(encoded, password)
        _, salt, digest = encoded.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), digest)
    except (ValueError, TypeError, Argon2Error, InvalidHashError):
        return False


def user_dict(row) -> dict:
    obj = dict(row)
    obj.pop("password_hash", None)
    obj["active"] = bool(obj["active"])
    obj["public_booking"] = bool(obj["public_booking"])
    obj["is_owner"] = bool(obj.get("is_owner", 0))
    obj["work_days"] = json.loads(obj["work_days"])
    return obj


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','advisor')),
 active INTEGER NOT NULL DEFAULT 1, public_booking INTEGER NOT NULL DEFAULT 0,
 timezone TEXT NOT NULL DEFAULT 'America/Puerto_Rico', work_start TEXT NOT NULL DEFAULT '09:00',
 work_end TEXT NOT NULL DEFAULT '17:00', work_days TEXT NOT NULL DEFAULT '[0,1,2,3,4]',
 duration_minutes INTEGER NOT NULL DEFAULT 30, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS leads (
 id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL DEFAULT '',
 municipality TEXT NOT NULL DEFAULT '',monthly_bill REAL,source TEXT NOT NULL DEFAULT 'manual',
 stage TEXT NOT NULL DEFAULT 'nuevo',advisor_id TEXT REFERENCES users(id),consent INTEGER NOT NULL DEFAULT 0,
 notes TEXT NOT NULL DEFAULT '',utm_source TEXT NOT NULL DEFAULT '',utm_medium TEXT NOT NULL DEFAULT '',
 utm_campaign TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
 id TEXT PRIMARY KEY,lead_id TEXT NOT NULL REFERENCES leads(id),advisor_id TEXT NOT NULL REFERENCES users(id),
 start_at TEXT NOT NULL,end_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'confirmed',source TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS appointments_advisor_time ON appointments(advisor_id,start_at,end_at);
CREATE INDEX IF NOT EXISTS leads_advisor ON leads(advisor_id);
CREATE TABLE IF NOT EXISTS conversations (
 id TEXT PRIMARY KEY,channel TEXT NOT NULL,external_id TEXT NOT NULL,contact_name TEXT NOT NULL,
 lead_id TEXT REFERENCES leads(id),advisor_id TEXT REFERENCES users(id),mode TEXT NOT NULL DEFAULT 'human',
 updated_at TEXT NOT NULL,UNIQUE(channel,external_id)
);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),direction TEXT NOT NULL,
 text TEXT NOT NULL,status TEXT NOT NULL,external_id TEXT,created_at TEXT NOT NULL,
 UNIQUE(conversation_id,external_id)
);
CREATE TABLE IF NOT EXISTS webhook_events (
 id TEXT PRIMARY KEY,channel TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
 id TEXT PRIMARY KEY,actor_id TEXT,action TEXT NOT NULL,entity_id TEXT,created_at TEXT NOT NULL
);
"""


from .operations import OperationsMixin, migrate_operations


def default_db_path(db_path=None) -> str:
    """Resolve the database path without opening or creating anything."""
    runtime = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "PowerSolar"
    return str(db_path or os.environ.get("REIGEL_DB_PATH", runtime / "reigel.db"))


# Appointment codes people can read aloud and type: six characters from an
# alphabet without look-alikes (0/O, 1/I/L, 2/Z, 5/S, 8/B), shown as ABC-DEF.
REFERENCE_ALPHABET = "ACDEFGHJKMNPQRTUVWXY34679"
REFERENCE_LENGTH = 6


def new_reference(db):
    for _ in range(25):
        code = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(REFERENCE_LENGTH))
        if not db.execute("SELECT 1 FROM appointments WHERE reference=?", (code,)).fetchone():
            return code
    raise DomainError("No se pudo generar el código de la cita. Inténtalo de nuevo.", 503)


def format_reference(code):
    return f"{code[:3]}-{code[3:]}" if code else ""


def normalize_reference(value):
    """Accepts lower case, spaces and hyphens: 'k7m 4qx' -> 'K7M4QX'; anything else -> ''."""
    if not isinstance(value, str):
        return ""
    code = re.sub(r"[\s-]", "", value).upper()
    return code if len(code) == REFERENCE_LENGTH and all(ch in REFERENCE_ALPHABET for ch in code) else ""


def migrate_appointment_reference(db):
    """Additive: short appointment code; existing appointments receive one too."""
    columns = {row["name"] for row in db.execute("PRAGMA table_info(appointments)")}
    if "reference" not in columns:
        db.execute("ALTER TABLE appointments ADD COLUMN reference TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS appointments_reference ON appointments(reference) WHERE reference IS NOT NULL")
    for row in db.execute("SELECT id FROM appointments WHERE reference IS NULL").fetchall():
        db.execute("UPDATE appointments SET reference=? WHERE id=?", (new_reference(db), row["id"]))


def migrate_owner(db):
    """Additive: the platform owner is an admin flagged with is_owner.

    When no active owner exists, the oldest active admin becomes the owner, so an
    existing database keeps exactly one account with control over plans and admins.
    """
    columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
    if "is_owner" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN is_owner INTEGER NOT NULL DEFAULT 0")
    if not db.execute("SELECT 1 FROM users WHERE is_owner=1 AND active=1").fetchone():
        first = db.execute("SELECT id FROM users WHERE role='admin' AND active=1 ORDER BY created_at,id LIMIT 1").fetchone()
        if first:
            db.execute("UPDATE users SET is_owner=1 WHERE id=?", (first["id"],))


class Store(OperationsMixin):
    def __init__(self, db_path=None):
        self.path = default_db_path(db_path)
        Path(self.path).resolve().parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            migrate_operations(db)
            migrate_owner(db)
            migrate_appointment_reference(db)
            from .identity import migrate_identity
            migrate_identity(db)
            defaults = {
                "name": "Power Solar", "timezone": "America/Puerto_Rico", "market": "Puerto Rico",
                "privacy_contact": "", "site_url": "",
            }
            for key, value in defaults.items():
                db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def audit(self, db, actor, action, entity_id=None):
        db.execute("INSERT INTO audit_events VALUES(?,?,?,?,?)", (uid(), actor and actor["id"], action, entity_id, stamp()))

    def settings(self):
        with self.connect() as db:
            return {r["key"]: r["value"] for r in db.execute("SELECT * FROM settings")}

    def update_settings(self, data, actor):
        self.require_admin(actor)
        allowed = {"name", "timezone", "market", "privacy_contact", "site_url"}
        if not isinstance(data, dict) or set(data) - allowed:
            raise DomainError("Configuración no válida.", 422)
        values = {key: text(value, key, limit=300, required=key in {"name", "timezone", "market"}) for key, value in data.items()}
        if "timezone" in values:
            zone(values["timezone"])
        if "site_url" in values:
            values["site_url"] = site_origin(values["site_url"])
        with self.connect() as db:
            for key, value in values.items():
                db.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
            self.audit(db, actor, "settings.update")
        return self.settings()

    @staticmethod
    def require_owner(actor):
        if not actor or actor.get("role") != "admin" or not actor.get("is_owner"):
            raise DomainError("Esta acción está reservada al propietario de R.E.I.G.E.L.", 403)

    @staticmethod
    def require_admin(actor):
        if not actor or actor["role"] != "admin":
            raise DomainError("Esta acción requiere una cuenta administradora.", 403)

    def list_users(self):
        with self.connect() as db:
            return [user_dict(r) for r in db.execute("SELECT * FROM users ORDER BY created_at,name")]

    def create_user(self, data, actor=None, bootstrap=False):
        if not bootstrap:
            self.require_admin(actor)
        name = text(data.get("name"), "nombre", required=True, limit=100)
        email = email_address(data.get("email"), required=True)
        role = data.get("role", "advisor")
        if not isinstance(role, str) or role not in {"admin", "advisor"}:
            raise DomainError("Rol no válido.", 422)
        if role == "admin" and not bootstrap:
            self.require_owner(actor)
        encoded = password_hash(data.get("password", ""))
        user_id = uid()
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if bootstrap and db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                    raise DomainError("Ya hay usuarios. Inicia sesión para administrar el equipo.", 409)
                db.execute("INSERT INTO users(id,name,email,password_hash,role,timezone,created_at,is_owner) VALUES(?,?,?,?,?,?,?,?)",
                           (user_id, name, email, encoded, role, self.settings()["timezone"], stamp(), int(bootstrap)))
                self.audit(db, actor, "user.create", user_id)
                return user_dict(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        except sqlite3.IntegrityError:
            raise DomainError("Ya existe una cuenta con ese correo.", 409) from None

    def update_user(self, user_id, data, actor):
        if actor["role"] != "admin" and actor["id"] != user_id:
            raise DomainError("No tienes acceso a esta cuenta.", 403)
        allowed = {"name", "active", "public_booking", "timezone", "work_start", "work_end", "work_days", "duration_minutes", "password"}
        if not isinstance(data, dict) or set(data) - allowed:
            raise DomainError("Campos de cuenta no válidos.", 422)
        if actor["role"] != "admin" and "active" in data:
            raise DomainError("Solo un administrador puede activar cuentas.", 403)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise DomainError("Cuenta no encontrada.", 404)
            old = user_dict(row)
            if "active" in data and old["is_owner"] and data["active"] is not True:
                raise DomainError("La cuenta del propietario no se puede desactivar.", 409)
            if "active" in data and old["role"] == "admin" and actor["id"] != user_id and not actor.get("is_owner"):
                raise DomainError("Solo el propietario puede activar o desactivar administradores.", 403)
            merged = {**old, **data}
            values = {}
            if "name" in data:
                values["name"] = text(data["name"], "nombre", limit=100, required=True)
            if "timezone" in data:
                zone(data["timezone"])
                values["timezone"] = data["timezone"]
            for key in ("active", "public_booking"):
                if key in data:
                    if not isinstance(data[key], bool):
                        raise DomainError("La activación debe ser sí o no.", 422)
                    values[key] = int(data[key])
            if not merged["active"] and old["role"] == "admin":
                admins = db.execute("SELECT count(*) FROM users WHERE active=1 AND role='admin'").fetchone()[0]
                if admins <= 1:
                    raise DomainError("Debe quedar al menos un administrador activo.", 409)
            for key in ("work_start", "work_end"):
                try:
                    if not re.fullmatch(r"\d{2}:\d{2}", merged[key]):
                        raise ValueError()
                    time.fromisoformat(merged[key])
                except (ValueError, TypeError):
                    raise DomainError("Usa un horario válido con formato HH:MM.", 422) from None
                if key in data:
                    values[key] = data[key]
            if merged["work_start"] >= merged["work_end"]:
                raise DomainError("El horario de cierre debe ser posterior al inicio.", 422)
            days = merged["work_days"]
            if not isinstance(days, list) or not days or any(type(d) is not int or d not in range(7) for d in days) or len(days) != len(set(days)):
                raise DomainError("Selecciona días de trabajo válidos.", 422)
            if "work_days" in data:
                values["work_days"] = json.dumps(sorted(days))
            duration = merged["duration_minutes"]
            if type(duration) is not int or duration not in {15, 30, 45, 60, 90, 120}:
                raise DomainError("La duración debe ser 15, 30, 45, 60, 90 o 120 minutos.", 422)
            if "duration_minutes" in data:
                values["duration_minutes"] = duration
            if "password" in data:
                values["password_hash"] = password_hash(data["password"])
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            for key, value in values.items():
                db.execute(f"UPDATE users SET {key}=? WHERE id=?", (value, user_id))
            if "active" in data and not data["active"]:
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self.audit(db, actor, "user.update", user_id)
            return user_dict(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def login(self, email, password):
        email = email_address(email, required=True)
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE AND active=1", (email,)).fetchone()
            encoded = row["password_hash"] if row else missing_password_hash()
            matched = password_matches(password, encoded)
            if not row or not matched:
                raise DomainError("Correo o contraseña incorrectos.", 401)
            from .identity import password_login_gate
            gate = password_login_gate(db, row["id"])
            if gate and gate != "totp":
                raise DomainError(gate, 403)
            if row["password_hash"].startswith("scrypt$"):
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash(password), row["id"]))
            if gate == "totp":
                # The password alone opens no session; the second factor must follow.
                return None, {"mfa_user_id": row["id"]}
            token = secrets.token_urlsafe(36)
            db.execute("DELETE FROM sessions WHERE expires_at<?", (stamp(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), row["id"], (now() + timedelta(hours=12)).isoformat()))
            self.audit(db, user_dict(row), "auth.login", row["id"])
            return token, user_dict(row)

    def session_user(self, token):
        if not token or len(token) > 200:
            raise DomainError("Inicia sesión para continuar.", 401)
        with self.connect() as db:
            row = db.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",
                             (hashlib.sha256(token.encode()).hexdigest(), stamp())).fetchone()
            if not row:
                raise DomainError("La sesión terminó. Vuelve a iniciar sesión.", 401)
            return user_dict(row)

    def logout(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256((token or "").encode()).hexdigest(),))

    def change_password(self, current_password, new_password, actor):
        encoded = password_hash(new_password)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT password_hash FROM users WHERE id=?", (actor["id"],)).fetchone()
            if not row or not password_matches(current_password, row["password_hash"]):
                raise DomainError("La contraseña actual no es correcta.", 401)
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, actor["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (actor["id"],))
            self.audit(db, actor, "auth.password", actor["id"])

    def normalize_lead(self, data, public=False):
        if not isinstance(data, dict):
            raise DomainError("Datos de contacto no válidos.", 422)
        if public and data.get("website"):
            raise DomainError("No se pudo procesar la solicitud.", 422)
        if public and data.get("consent") is not True:
            raise DomainError("Necesitamos tu autorización para contactarte y gestionar la cita.", 422)
        if "consent" in data and type(data["consent"]) is not bool:
            raise DomainError("El consentimiento debe ser sí o no.", 422)
        email = email_address(data.get("email"))
        phone = text(data.get("phone"), "teléfono", limit=40)
        if phone and (not re.fullmatch(r"[+()\d\s.\-]{7,40}", phone) or len(re.sub(r"\D", "", phone)) < 7):
            raise DomainError("Introduce un teléfono válido.", 422)
        if phone:
            digits = re.sub(r"\D", "", phone)
            # Puerto Rico uses NANP +1; normalize punctuation and local ten-digit numbers.
            if len(digits) == 10 and not phone.startswith("+"):
                digits = "1" + digits
            if not 7 <= len(digits) <= 15:
                raise DomainError("Introduce un teléfono válido con código de país.", 422)
            phone = "+" + digits
        if not email and not phone:
            raise DomainError("Introduce un correo o un teléfono para contactarte.", 422)
        bill = data.get("monthly_bill")
        if bill in (None, ""):
            bill = None
        else:
            try:
                if isinstance(bill, bool):
                    raise ValueError()
                bill = float(bill)
                if not (0 <= bill <= 100000):
                    raise ValueError()
            except (ValueError, TypeError):
                raise DomainError("La factura mensual debe estar entre 0 y 100000.", 422) from None
        source = text(data.get("source", "web" if public else "manual"), "origen", limit=60)
        source = source if source in {"web", "manual", "whatsapp", "telegram", "instagram", "messenger", "referido", "facebook", "google", "organic"} else "web" if public else "manual"
        return {
            "name": text(data.get("name"), "nombre", limit=100, required=True), "email": email, "phone": phone,
            "municipality": text(data.get("municipality"), "municipio", limit=100), "monthly_bill": bill,
            "consent": bool(data.get("consent", False)), "source": source,
            "utm_source": text(data.get("utm_source"), "utm_source", limit=120),
            "utm_medium": text(data.get("utm_medium"), "utm_medium", limit=120),
            "utm_campaign": text(data.get("utm_campaign"), "utm_campaign", limit=120),
        }

    def _insert_lead(self, db, data, advisor_id=None):
        lead_id = uid()
        timestamp = stamp()
        db.execute("""INSERT INTO leads(id,name,email,phone,municipality,monthly_bill,source,consent,advisor_id,utm_source,utm_medium,utm_campaign,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (lead_id, data["name"], data["email"], data["phone"], data["municipality"], data["monthly_bill"], data["source"], int(data["consent"]), advisor_id, data["utm_source"], data["utm_medium"], data["utm_campaign"], timestamp, timestamp))
        return lead_id

    def create_lead(self, data, actor=None):
        normalized = self.normalize_lead(data, public=actor is None)
        metadata = self._lead_metadata(data) if actor else {}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            advisor_id = data.get("advisor_id")
            if advisor_id is not None:
                advisor_id = text(advisor_id, "asesor", limit=100) or None
            if actor and actor["role"] != "admin":
                if advisor_id and advisor_id != actor["id"]:
                    raise DomainError("No puedes asignar contactos a otro asesor.", 403)
                advisor_id = actor["id"]
            if advisor_id:
                if not db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (advisor_id,)).fetchone():
                    raise DomainError("El asesor no está disponible.", 422)
            else:
                candidate = db.execute("""SELECT u.id,count(l.id) n FROM users u LEFT JOIN leads l ON l.advisor_id=u.id
                                        WHERE u.active=1 AND u.public_booking=1 GROUP BY u.id ORDER BY n,u.created_at LIMIT 1""").fetchone()
                advisor_id = candidate["id"] if candidate else None
            lead_id = self._insert_lead(db, normalized, advisor_id)
            for key, value in metadata.items():
                db.execute(f"UPDATE leads SET {key}=? WHERE id=?", (value, lead_id))
            self.audit(db, actor, "lead.create", lead_id)
            return self._lead(db, lead_id, actor, public=actor is None)

    @staticmethod
    def _scope(actor, alias=""):
        prefix = f"{alias}." if alias else ""
        return ("1=1", ()) if actor["role"] == "admin" else (f"{prefix}advisor_id=?", (actor["id"],))

    def _lead(self, db, lead_id, actor=None, public=False):
        query = "SELECT l.*,u.name advisor_name FROM leads l LEFT JOIN users u ON u.id=l.advisor_id WHERE l.id=?"
        args = (lead_id,)
        if actor and actor["role"] != "admin":
            query += " AND l.advisor_id=?"
            args += (actor["id"],)
        row = db.execute(query, args).fetchone()
        if not row:
            raise DomainError("Contacto no encontrado.", 404)
        if public:
            return {"id": row["id"]}
        obj = dict(row)
        obj["consent"] = bool(obj["consent"])
        return obj

    def get_lead(self, lead_id, actor):
        with self.connect() as db:
            return self._lead(db, lead_id, actor)

    def list_leads(self, actor):
        clause, args = self._scope(actor, "l")
        with self.connect() as db:
            rows = db.execute(f"SELECT l.*,u.name advisor_name FROM leads l LEFT JOIN users u ON u.id=l.advisor_id WHERE {clause} ORDER BY l.created_at DESC LIMIT 1000", args)
            return [{**dict(r), "consent": bool(r["consent"])} for r in rows]

    def update_lead(self, lead_id, data, actor):
        return self.edit_lead(lead_id, data, actor)

    def _advisor(self, db, advisor_id, public):
        row = db.execute("SELECT * FROM users WHERE id=? AND active=1", (advisor_id,)).fetchone()
        if not row or (public and not row["public_booking"]):
            raise DomainError("Este asesor no tiene agenda disponible.", 404)
        return user_dict(row)

    def _slots(self, db, advisor, day):
        tz = zone(advisor["timezone"])
        try:
            selected = date.fromisoformat(day)
        except (ValueError, TypeError):
            raise DomainError("Selecciona una fecha válida (AAAA-MM-DD).", 422) from None
        local_now = now().astimezone(tz)
        if selected < local_now.date() or selected > (local_now + timedelta(days=60)).date():
            return {"slots": [], "timezone": advisor["timezone"]}
        if selected.weekday() not in advisor["work_days"]:
            return {"slots": [], "timezone": advisor["timezone"]}
        start = datetime.combine(selected, time.fromisoformat(advisor["work_start"]), tz)
        end = datetime.combine(selected, time.fromisoformat(advisor["work_end"]), tz)
        delta = timedelta(minutes=advisor["duration_minutes"])
        booked = db.execute("SELECT start_at,end_at FROM appointments WHERE advisor_id=? AND status='confirmed' AND start_at<? AND end_at>?",
                            (advisor["id"], end.astimezone(UTC).isoformat(), start.astimezone(UTC).isoformat())).fetchall()
        busy = [(datetime.fromisoformat(r["start_at"]), datetime.fromisoformat(r["end_at"])) for r in booked]
        slots = []
        while start + delta <= end:
            finish = start + delta
            utc_start, utc_finish = start.astimezone(UTC), finish.astimezone(UTC)
            if utc_start >= now() + timedelta(hours=1) and not any(utc_start < b and utc_finish > a for a, b in busy):
                # Reject nonexistent/ambiguous wall times rather than book a shifted appointment.
                round_trip = utc_start.astimezone(tz)
                if round_trip.replace(tzinfo=None) == start.replace(tzinfo=None) and start.fold == 0:
                    slots.append({"start_at": start.isoformat(), "end_at": finish.isoformat()})
            start = finish
        return {"slots": slots, "timezone": advisor["timezone"]}

    def slots(self, advisor_id, day):
        with self.connect() as db:
            return self._slots(db, self._advisor(db, advisor_id, True), day)

    def _appointment(self, db, appointment_id, actor=None):
        row = db.execute("""SELECT a.*,l.name lead_name,u.name advisor_name FROM appointments a
                            JOIN leads l ON l.id=a.lead_id JOIN users u ON u.id=a.advisor_id WHERE a.id=?""", (appointment_id,)).fetchone()
        if not row or (actor and actor["role"] != "admin" and row["advisor_id"] != actor["id"]):
            raise DomainError("Cita no encontrada.", 404)
        if actor and actor["role"] != "admin":
            self._lead(db, row["lead_id"], actor)
        return dict(row)

    def book(self, data, source="web", actor=None):
        if not isinstance(data, dict):
            raise DomainError("Datos de cita no válidos.", 422)
        advisor_id = text(data.get("advisor_id"), "asesor", limit=100, required=True)
        try:
            selected = datetime.fromisoformat(data.get("start_at", ""))
            if selected.tzinfo is None or selected.utcoffset() is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise DomainError("La cita necesita fecha, hora y zona horaria válidas.", 422) from None
        public_data = self.normalize_lead(data, public=True) if actor is None else None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            advisor = self._advisor(db, advisor_id, actor is None)
            if actor and actor["role"] != "admin" and advisor_id != actor["id"]:
                raise DomainError("Solo puedes reservar en tu propia agenda.", 403)
            local = selected.astimezone(zone(advisor["timezone"]))
            available = self._slots(db, advisor, local.date().isoformat())["slots"]
            match = next((s for s in available if datetime.fromisoformat(s["start_at"]) == selected), None)
            if not match:
                raise DomainError("Ese horario ya no está disponible. Selecciona otro.", 409)
            begin = selected.astimezone(UTC).isoformat()
            finish = datetime.fromisoformat(match["end_at"]).astimezone(UTC).isoformat()
            if actor:
                lead_id = text(data.get("lead_id"), "contacto", limit=100, required=True)
                lead = self._lead(db, lead_id, actor)
                if not lead["consent"]:
                    raise DomainError("El contacto debe autorizar la gestión de su cita.", 422)
                if actor["role"] != "admin" and lead["advisor_id"] != advisor_id:
                    raise DomainError("No puedes reservar para otro asesor.", 403)
                self._transfer_lead(db, lead, advisor_id, actor)
                duplicate = db.execute("SELECT 1 FROM appointments WHERE lead_id=? AND status='confirmed' AND start_at<? AND end_at>?", (lead_id, finish, begin)).fetchone()
            else:
                # Match identities only for overlap protection, without exposing/reusing private CRM data.
                duplicate = db.execute("""SELECT 1 FROM appointments a JOIN leads l ON l.id=a.lead_id
                    WHERE a.status='confirmed' AND a.start_at<? AND a.end_at>?
                    AND ((?<>'' AND l.email=? COLLATE NOCASE) OR (?<>'' AND l.phone=?))""",
                    (finish, begin, public_data["email"], public_data["email"], public_data["phone"], public_data["phone"])).fetchone()
                lead_id = None
            if duplicate:
                raise DomainError("Ya existe una cita para este contacto en ese horario.", 409)
            if lead_id is None:
                lead_id = self._insert_lead(db, public_data, advisor_id)
            appointment_id = uid()
            db.execute("""INSERT INTO appointments(id,lead_id,advisor_id,start_at,end_at,status,source,created_at,reference)
                VALUES(?,?,?,?,?,?,?,?,?)""", (appointment_id, lead_id, advisor_id, begin, finish, "confirmed", source, stamp(), new_reference(db)))
            db.execute("UPDATE tasks SET owner_id=?,updated_at=? WHERE lead_id=? AND status='pending'", (advisor_id, stamp(), lead_id))
            db.execute("UPDATE leads SET stage='cita',advisor_id=?,updated_at=? WHERE id=?", (advisor_id, stamp(), lead_id))
            db.execute("UPDATE conversations SET advisor_id=? WHERE lead_id=?", (advisor_id, lead_id))
            self.audit(db, actor, "appointment.book", appointment_id)
            result = self._appointment(db, appointment_id, actor)
            if actor is None:
                return {key: result[key] for key in ("id", "reference", "start_at", "end_at", "advisor_name")}
            return result

    def list_appointments(self, actor, lead_id=None):
        clause, args = self._scope(actor, "a")
        if actor["role"] != "admin":
            clause += " AND l.advisor_id=?"
            args += (actor["id"],)
        if lead_id:
            clause += " AND a.lead_id=?"
            args += (lead_id,)
        with self.connect() as db:
            return [dict(r) for r in db.execute(f"""SELECT a.*,l.name lead_name,u.name advisor_name,coalesce(r.hours,24) reminder_hours FROM appointments a
                        JOIN leads l ON l.id=a.lead_id JOIN users u ON u.id=a.advisor_id
                        LEFT JOIN appointment_reminders r ON r.appointment_id=a.id
                        WHERE {clause} ORDER BY a.start_at DESC LIMIT 1000""", args)]

    def cancel_appointment(self, appointment_id, actor):
        return self.update_appointment(appointment_id, {"status": "cancelled"}, actor)

    def get_appointment(self, appointment_id, actor):
        with self.connect() as db:
            return self._appointment(db, appointment_id, actor)

    def dashboard(self, actor):
        return self.operations_dashboard(actor)

    def conversation(self, conversation_id, actor):
        with self.connect() as db:
            clause, args = self._scope(actor)
            row = db.execute(f"SELECT * FROM conversations WHERE id=? AND {clause}", (conversation_id, *args)).fetchone()
            if not row:
                raise DomainError("Conversación no encontrada.", 404)
            return dict(row)

    def list_conversations(self, actor):
        clause, args = self._scope(actor, "c")
        with self.connect() as db:
            return [dict(r) for r in db.execute(f"""SELECT c.*,(SELECT m.text FROM messages m WHERE m.conversation_id=c.id ORDER BY m.created_at DESC LIMIT 1) last_message
                FROM conversations c WHERE {clause} ORDER BY c.updated_at DESC LIMIT 500""", args)]

    def conversation_messages(self, conversation_id, actor):
        self.conversation(conversation_id, actor)
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at,id LIMIT 500", (conversation_id,))]

    def set_conversation_mode(self, conversation_id, mode, actor):
        if not isinstance(mode, str) or mode not in {"human", "ai"}:
            raise DomainError("Modo no válido.", 422)
        conversation = self.conversation(conversation_id, actor)
        with self.connect() as db:
            if mode == "ai" and conversation["lead_id"]:
                row = db.execute("SELECT consent FROM leads WHERE id=?", (conversation["lead_id"],)).fetchone()
                if not row or not row["consent"]:
                    raise DomainError("El contacto debe consentir la asistencia automática.", 422)
            db.execute("UPDATE conversations SET mode=?,updated_at=? WHERE id=?", (mode, stamp(), conversation_id))
            self.audit(db, actor, "conversation.mode", conversation_id)
        return self.conversation(conversation_id, actor)

    def assign_conversation(self, conversation_id, data, actor):
        self.require_admin(actor)
        if not isinstance(data, dict) or not data or set(data) - {"advisor_id", "lead_id"}:
            raise DomainError("Campos de asignación no válidos.", 422)
        current = self.conversation(conversation_id, actor)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lead_id = text(data.get("lead_id", current["lead_id"]), "contacto", limit=100) or None
            advisor_id = text(data.get("advisor_id", current["advisor_id"]), "asesor", limit=100) or None
            if lead_id:
                linked = self._lead(db, lead_id, actor)
                if "advisor_id" not in data:
                    advisor_id = linked["advisor_id"]
            if advisor_id and not db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (advisor_id,)).fetchone():
                raise DomainError("Asesor no disponible.", 422)
            if lead_id:
                self._transfer_lead(db, linked, advisor_id, actor)
                db.execute("UPDATE leads SET advisor_id=?,updated_at=? WHERE id=?", (advisor_id, stamp(), lead_id))
                if linked["advisor_id"] != advisor_id:
                    db.execute("INSERT INTO lead_history VALUES(?,?,?,?,?,?,?)", (uid(), lead_id, actor["id"], "advisor_id", linked["advisor_id"], advisor_id, stamp()))
                db.execute("UPDATE conversations SET advisor_id=?,mode='human',updated_at=? WHERE lead_id=?", (advisor_id, stamp(), lead_id))
            db.execute("UPDATE conversations SET advisor_id=?,lead_id=?,mode='human',updated_at=? WHERE id=?", (advisor_id, lead_id, stamp(), conversation_id))
            self.audit(db, actor, "conversation.assign", conversation_id)
        return self.conversation(conversation_id, actor)

    def record_outbound(self, conversation_id, text_value, result, actor):
        self.conversation(conversation_id, actor)
        with self.connect() as db:
            message_id = uid()
            db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)", (message_id, conversation_id, "outbound", text_value, result["status"], result.get("provider_id"), stamp()))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (stamp(), conversation_id))
            self.audit(db, actor, "message." + result["status"], message_id)
            return dict(db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone())


def calendar_file(appointment, business):
    def escape(value):
        return str(value).replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")

    def utc(value):
        return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Power Solar//R.E.I.G.E.L.//ES", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
             f"UID:{appointment['id']}@reigel.local", f"DTSTAMP:{now().strftime('%Y%m%dT%H%M%SZ')}",
             f"DTSTART:{utc(appointment['start_at'])}", f"DTEND:{utc(appointment['end_at'])}",
             "SUMMARY:" + escape(f"{business['name']} · {appointment['lead_name']}"),
             "DESCRIPTION:" + escape(f"Consulta solar con {appointment['advisor_name']}."),
             "STATUS:" + ("CANCELLED" if appointment["status"] == "cancelled" else "CONFIRMED"), "END:VEVENT", "END:VCALENDAR"]
    folded = []
    for line in lines:
        current = ""
        for char in line:
            if len((current + char).encode("utf-8")) > 73:
                folded.append(current)
                current = " " + char
            else:
                current += char
        folded.append(current)
    return "\r\n".join(folded) + "\r\n"
