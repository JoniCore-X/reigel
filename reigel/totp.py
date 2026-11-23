"""RFC 6238 one-time codes compatible with Google Authenticator."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import quote, urlencode

import segno

PERIOD = 30
DIGITS = 6
WINDOW = 1
ISSUER = "R.E.I.G.E.L. Team"


def new_secret() -> bytes:
    return secrets.token_bytes(20)


def display_secret(secret: bytes) -> str:
    return base64.b32encode(secret).decode().rstrip("=")


def otpauth_uri(secret: bytes, account: str) -> str:
    query = urlencode({"secret": display_secret(secret), "issuer": ISSUER, "algorithm": "SHA1", "digits": DIGITS, "period": PERIOD}, quote_via=quote)
    return f"otpauth://totp/{quote(ISSUER)}:{quote(account)}?{query}"


def qr_data_uri(uri: str) -> str:
    return segno.make(uri, error="m", micro=False).svg_data_uri(scale=6, border=4, dark="#000", light="#fff")


def code_at(secret: bytes, step: int) -> str:
    digest = hmac.new(secret, step.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
    return f"{value % 10 ** DIGITS:0{DIGITS}d}"


def matching_step(secret: bytes, code, last_step: int = -1, at: float | None = None) -> int | None:
    """Return the accepted time step, rejecting any step already consumed."""
    if not isinstance(code, str):
        return None
    clean = re.sub(r"\s", "", code)
    if not re.fullmatch(rf"\d{{{DIGITS}}}", clean):
        return None
    current = int((time.time() if at is None else at) // PERIOD)
    accepted = None
    for step in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(code_at(secret, step), clean) and step > last_step and accepted is None:
            accepted = step
    return accepted
