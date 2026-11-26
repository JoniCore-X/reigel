"""Test-only helpers for the mandatory Team Caguas access checks (synthetic accounts only).

Every team login needs an allowed email and Google Authenticator. Tests about
other features use these helpers to pass those checks through the real HTTP
flow: the first login enrolls a fresh authenticator via the QR endpoints (with a
one-time invitation code issued the same way scripts/team_recovery.py does), later
logins send a code computed from the secret captured at enrollment.
"""
from __future__ import annotations

import base64
import sqlite3
import time

from reigel import totp

_SECRETS: dict[tuple[str, str], bytes] = {}


def allow(store, owner, *emails, name_rule=False):
    """The owner allows synthetic emails. Unless asked, the naming filter is turned off,
    because these fixtures predate the "powersolar" convention."""
    if not name_rule:
        store.set_team_name_rule(False, owner)
    for email in emails:
        store.allow_team_email(email, owner)


def decode(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def fresh_code(path, email, secret) -> str:
    """A code the server has not consumed yet. If the three-step window of this
    test account is used up, rewind its replay marker (test databases only)."""
    current = int(time.time() // totp.PERIOD)
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT t.last_step,u.id FROM team_totp t JOIN users u ON u.id=t.user_id WHERE u.email=? COLLATE NOCASE", (email,)).fetchone()
        step = max(row[0] + 1, current)
        if step > current + 1:
            db.execute("UPDATE team_totp SET last_step=? WHERE user_id=?", (current - 1, row[1]))
            step = current
    return totp.code_at(secret, step)


def invitation(app, email) -> str:
    """A fresh invitation code for a synthetic account (server-side, like the local script)."""
    return app.state.identity.local_grant(email, "prueba sintética", "enroll")["code"]


def login(client, email, password, invitation_code=None):
    """Password, then enrollment (first time) or the current code; returns the last response."""
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    if response.status_code != 200:
        return response
    path, key = client.app.state.store.path, (client.app.state.store.path, email.lower())
    if response.json().get("enrollment_required"):
        code = invitation_code or invitation(client.app, email)
        setup = client.post("/api/team-identity/totp/enroll", json={"invitation_code": code})
        assert setup.status_code == 200, setup.text
        secret = decode(setup.json()["setup"]["secret"])
        _SECRETS[key] = secret
        return client.post("/api/team-identity/totp/enroll/confirm", json={"code": totp.code_at(secret, int(time.time() // totp.PERIOD))})
    return client.post("/api/team-identity/totp/login", json={"code": fresh_code(path, email, _SECRETS[key])})


def secret_for(store, email) -> bytes:
    return _SECRETS[(store.path, email.lower())]
