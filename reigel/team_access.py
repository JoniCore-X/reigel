"""Who may hold a Team Caguas account: an owner-controlled email allowlist.

Two layers decide whether an email may be created as a team user, log in or
keep a session:

1. The allowlist (``team_allowed_emails``). This is a real security control:
   only the owner adds or removes entries, and removing one revokes that
   person's sessions immediately.
2. The "Power Solar" naming rule. With the rule on (the default), an allowed
   email must contain "powersolar" in its local part or domain. This is an
   ORGANIZATIONAL FILTER, NOT A SECURITY CONTROL: anyone can create a mailbox
   whose name contains "powersolar". The real controls are the allowlist and
   the mandatory Google Authenticator code (see identity.py).

Lockout protection: the owner account cannot be removed from the list, the
owner's email is re-allowed on every start, and the naming rule never blocks
the owner account.
"""

from __future__ import annotations

import logging
import os

from .core import DomainError, email_address, stamp, uid

ENV_KEY = "REIGEL_TEAM_ALLOWED_EMAILS"
RULE_KEY = "team_email_name_rule"
NAME_MARK = "powersolar"
MAX_EMAILS = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS team_allowed_emails (
 email TEXT PRIMARY KEY, source TEXT NOT NULL CHECK(source IN ('env','owner','owner_account')),
 added_by TEXT, created_at TEXT NOT NULL, removed_at TEXT, removed_by TEXT
);
"""

RULE_NOTICE = ("La regla «Power Solar» es un filtro organizativo, no un control de seguridad: cualquiera puede crear un correo "
               "que contenga «powersolar». Lo que protege el acceso es la lista de correos autorizados y Google Authenticator.")


def normalize(value) -> str:
    """Trim and lowercase; reject anything that is not a plausible address."""
    return email_address(value, required=True)


def matches_name(email: str) -> bool:
    local, _, domain = (email or "").lower().partition("@")
    return NAME_MARK in local or NAME_MARK in domain


def _audit(db, actor_id, action, entity=None):
    db.execute("INSERT INTO audit_events VALUES(?,?,?,?,?)", (uid(), actor_id, action, entity, stamp()))


def name_rule_on(db) -> bool:
    row = db.execute("SELECT value FROM settings WHERE key=?", (RULE_KEY,)).fetchone()
    return not row or row["value"] != "0"


def listed(db, email: str) -> bool:
    return bool(db.execute("SELECT 1 FROM team_allowed_emails WHERE email=? AND removed_at IS NULL", ((email or "").lower(),)).fetchone())


def is_allowed(db, email: str, *, owner: bool = False) -> bool:
    """Allowlist first; the naming filter applies to everyone except the owner account."""
    if not listed(db, email):
        return False
    return owner or not name_rule_on(db) or matches_name(email)


def env_emails(environ=None) -> list[str]:
    raw = (environ if environ is not None else os.environ).get(ENV_KEY, "")
    found, skipped = [], 0
    for item in raw.split(","):
        if not item.strip():
            continue
        try:
            email = normalize(item)
        except DomainError:
            skipped += 1
            continue
        if email not in found:
            found.append(email)
    if skipped:
        # Never log the values themselves: they are personal data.
        logging.getLogger(__name__).warning("%s contiene %d entrada(s) no válida(s) que se ignoraron.", ENV_KEY, skipped)
    return found[:MAX_EMAILS]


def ensure_owner_allowed(db) -> None:
    """The active owner's email is always on the list (lockout protection)."""
    for row in db.execute("SELECT id,lower(email) email FROM users WHERE is_owner=1 AND active=1").fetchall():
        current = db.execute("SELECT removed_at FROM team_allowed_emails WHERE email=?", (row["email"],)).fetchone()
        if current and current["removed_at"] is None:
            continue
        db.execute("""INSERT INTO team_allowed_emails(email,source,added_by,created_at) VALUES(?,?,?,?)
                      ON CONFLICT(email) DO UPDATE SET removed_at=NULL,removed_by=NULL""", (row["email"], "owner_account", None, stamp()))
        _audit(db, None, "team_access.owner_auto_allowed", row["id"])


def migrate_team_access(db, environ=None) -> None:
    """Additive and idempotent. The environment variable only adds emails that were never on the list;
    an email the owner removed is not re-added by a later start (the owner can add it again in /app)."""
    db.executescript(SCHEMA)
    db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (RULE_KEY, "1"))
    db.execute("INSERT OR IGNORE INTO schema_migrations VALUES('reigel_team_access_v1',?)", (stamp(),))
    for email in env_emails(environ):
        added = db.execute("INSERT OR IGNORE INTO team_allowed_emails(email,source,added_by,created_at) VALUES(?,?,?,?)",
                           (email, "env", None, stamp())).rowcount
        if added:
            _audit(db, None, "team_access.email_seeded", email)
    ensure_owner_allowed(db)


def revoke_access(db, email: str) -> int:
    """Close every session and pending sign-in step of the account that uses this email."""
    users = [row["id"] for row in db.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (email,))]
    for user_id in users:
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM team_mfa_challenges WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM team_enroll_challenges WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM team_totp_setups WHERE user_id=?", (user_id,))
        db.execute("UPDATE team_access_grants SET consumed_at=? WHERE user_id=? AND consumed_at IS NULL", (stamp(), user_id))
        _audit(db, None, "auth.sessions_revoked", user_id)
    return len(users)


class TeamAccessMixin:
    """Owner-only management of the allowlist and the naming rule."""

    def team_access(self, actor) -> dict:
        self.require_owner(actor)
        with self.connect() as db:
            rule = name_rule_on(db)
            owners = {row["email"] for row in db.execute("SELECT lower(email) email FROM users WHERE is_owner=1")}
            accounts = {row["email"]: row for row in db.execute(
                "SELECT lower(u.email) email,u.active,(t.user_id IS NOT NULL) totp FROM users u LEFT JOIN team_totp t ON t.user_id=u.id")}
            items = []
            for row in db.execute("SELECT email,source,created_at FROM team_allowed_emails WHERE removed_at IS NULL ORDER BY email"):
                account = accounts.get(row["email"])
                is_owner = row["email"] in owners
                items.append({"email": row["email"], "source": row["source"], "created_at": row["created_at"], "is_owner": is_owner,
                              "has_account": bool(account), "active": bool(account and account["active"]),
                              "totp_enrolled": bool(account and account["totp"]), "matches_name_rule": matches_name(row["email"]),
                              "blocked_by_name_rule": rule and not is_owner and not matches_name(row["email"])})
            return {"emails": items, "name_rule": rule, "name_mark": NAME_MARK, "notice": RULE_NOTICE}

    def allow_team_email(self, value, actor) -> dict:
        self.require_owner(actor)
        email = normalize(value)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if name_rule_on(db) and not matches_name(email):
                raise DomainError("Con la regla «Power Solar» activa, el correo debe contener «powersolar» en el nombre o en el dominio.", 422)
            row = db.execute("SELECT removed_at FROM team_allowed_emails WHERE email=?", (email,)).fetchone()
            if row and row["removed_at"] is None:
                raise DomainError("Ese correo ya está en la lista.", 409)
            if db.execute("SELECT count(*) FROM team_allowed_emails WHERE removed_at IS NULL").fetchone()[0] >= MAX_EMAILS:
                raise DomainError("La lista alcanzó el máximo de correos.", 409)
            db.execute("""INSERT INTO team_allowed_emails(email,source,added_by,created_at) VALUES(?,?,?,?)
                          ON CONFLICT(email) DO UPDATE SET source=excluded.source,added_by=excluded.added_by,
                          created_at=excluded.created_at,removed_at=NULL,removed_by=NULL""", (email, "owner", actor["id"], stamp()))
            _audit(db, actor["id"], "team_access.email_added", email)
        return self.team_access(actor)

    def remove_team_email(self, value, actor) -> dict:
        self.require_owner(actor)
        email = normalize(value)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE AND is_owner=1", (email,)).fetchone():
                raise DomainError("La cuenta del propietario no se puede quitar de la lista.", 409)
            removed = db.execute("UPDATE team_allowed_emails SET removed_at=?,removed_by=? WHERE email=? AND removed_at IS NULL",
                                 (stamp(), actor["id"], email)).rowcount
            if not removed:
                raise DomainError("Ese correo no está en la lista.", 404)
            _audit(db, actor["id"], "team_access.email_removed", email)
            revoke_access(db, email)
        return self.team_access(actor)

    def set_team_name_rule(self, enabled, actor) -> dict:
        self.require_owner(actor)
        if not isinstance(enabled, bool):
            raise DomainError("Valor no válido.", 422)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (RULE_KEY, "1" if enabled else "0"))
            _audit(db, actor["id"], f"team_access.name_rule.{int(enabled)}")
            if enabled:
                # Accounts that no longer pass the filter lose their sessions now, not at their next request.
                for row in db.execute("SELECT lower(email) email FROM users WHERE is_owner=0").fetchall():
                    if not matches_name(row["email"]):
                        revoke_access(db, row["email"])
        return self.team_access(actor)
