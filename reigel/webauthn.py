"""Server-side WebAuthn verification for discoverable, user-verified passkeys."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from .core import DomainError

ES256, RS256 = -7, -257
FLAG_UP, FLAG_UV, FLAG_AT, FLAG_ED = 0x01, 0x04, 0x40, 0x80
MAX_FIELD = 16384


def invalid() -> DomainError:
    return DomainError("No se pudo verificar la llave de acceso.", 401)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def from_b64url(value) -> bytes:
    if not isinstance(value, str) or not value or len(value) > MAX_FIELD:
        raise invalid()
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        raise invalid() from None


def cbor_decode(data: bytes, offset: int = 0, depth: int = 0):
    """Decode the definite-length CBOR subset used by WebAuthn."""
    if depth > 8 or offset >= len(data):
        raise invalid()
    head = data[offset]
    offset += 1
    major, info = head >> 5, head & 31
    if info < 24:
        length = info
    elif info in {24, 25, 26, 27}:
        size = 1 << (info - 24)
        if offset + size > len(data):
            raise invalid()
        length = int.from_bytes(data[offset:offset + size], "big")
        offset += size
    else:
        raise invalid()
    if major == 0:
        return length, offset
    if major == 1:
        return -1 - length, offset
    if major in {2, 3}:
        if offset + length > len(data):
            raise invalid()
        raw = data[offset:offset + length]
        offset += length
        if major == 2:
            return raw, offset
        try:
            return raw.decode(), offset
        except UnicodeDecodeError:
            raise invalid() from None
    if major == 4:
        if length > 64:
            raise invalid()
        items = []
        for _ in range(length):
            item, offset = cbor_decode(data, offset, depth + 1)
            items.append(item)
        return items, offset
    if major == 5:
        if length > 64:
            raise invalid()
        mapping = {}
        for _ in range(length):
            key, offset = cbor_decode(data, offset, depth + 1)
            if not isinstance(key, (int, str)) or key in mapping:
                raise invalid()
            mapping[key], offset = cbor_decode(data, offset, depth + 1)
        return mapping, offset
    if major == 7 and info in {20, 21, 22}:
        return {20: False, 21: True, 22: None}[info], offset
    raise invalid()


def public_key(cose: bytes):
    key, end = cbor_decode(cose)
    if end != len(cose) or not isinstance(key, dict):
        raise invalid()
    try:
        if key.get(1) == 2 and key.get(3) == ES256 and key.get(-1) == 1:
            x, y = key[-2], key[-3]
            if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == len(y) == 32):
                raise invalid()
            return ES256, ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()).public_key()
        if key.get(1) == 3 and key.get(3) == RS256:
            n, e = int.from_bytes(key[-1], "big"), int.from_bytes(key[-2], "big")
            if n.bit_length() < 2048 or e != 65537:
                raise invalid()
            return RS256, rsa.RSAPublicNumbers(e, n).public_key()
    except (KeyError, TypeError, ValueError):
        raise invalid() from None
    raise invalid()


def parse_authenticator_data(data: bytes, *, attested: bool) -> dict:
    if len(data) < 37:
        raise invalid()
    flags = data[32]
    parsed = {"rp_hash": data[:32], "flags": flags, "sign_count": int.from_bytes(data[33:37], "big")}
    offset = 37
    if bool(flags & FLAG_AT) != attested:
        raise invalid()
    if attested:
        if len(data) < offset + 18:
            raise invalid()
        length = int.from_bytes(data[offset + 16:offset + 18], "big")
        offset += 18
        if not 16 <= length <= 1023 or offset + length > len(data):
            raise invalid()
        parsed["credential_id"] = data[offset:offset + length]
        offset += length
        _, end = cbor_decode(data, offset)
        parsed["public_key"] = data[offset:end]
        offset = end
    if flags & FLAG_ED:
        _, offset = cbor_decode(data, offset)
    if offset != len(data):
        raise invalid()
    return parsed


def _client_data(raw: bytes, kind: str, challenge_hash: str, origin: str) -> None:
    try:
        client = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise invalid() from None
    if not isinstance(client, dict) or client.get("type") != kind or client.get("origin") != origin or client.get("crossOrigin") is True:
        raise invalid()
    actual = hashlib.sha256(from_b64url(client.get("challenge"))).hexdigest()
    if not hmac.compare_digest(actual, challenge_hash):
        raise invalid()


def _common(parsed: dict, rp_id: str) -> None:
    expected = hashlib.sha256(rp_id.encode()).digest()
    if not hmac.compare_digest(parsed["rp_hash"], expected):
        raise invalid()
    if not parsed["flags"] & FLAG_UP or not parsed["flags"] & FLAG_UV:
        raise invalid()


def _response(credential) -> dict:
    if not isinstance(credential, dict) or credential.get("type") != "public-key":
        raise invalid()
    response = credential.get("response")
    if not isinstance(response, dict) or credential.get("id") != credential.get("rawId"):
        raise invalid()
    return response


def verify_registration(credential, challenge_hash: str, rp_id: str, origin: str) -> dict:
    response = _response(credential)
    _client_data(from_b64url(response.get("clientDataJSON")), "webauthn.create", challenge_hash, origin)
    attestation, end = cbor_decode(from_b64url(response.get("attestationObject")))
    if not isinstance(attestation, dict) or end != len(from_b64url(response.get("attestationObject"))):
        raise invalid()
    # The ceremony requests attestation "none"; other statements are not trusted.
    if attestation.get("fmt") != "none" or attestation.get("attStmt") != {} or not isinstance(attestation.get("authData"), bytes):
        raise invalid()
    parsed = parse_authenticator_data(attestation["authData"], attested=True)
    _common(parsed, rp_id)
    if not hmac.compare_digest(parsed["credential_id"], from_b64url(credential.get("rawId"))):
        raise invalid()
    public_key(parsed["public_key"])
    transports = response.get("transports", [])
    allowed = {"usb", "nfc", "ble", "internal", "hybrid", "smart-card"}
    clean = [item for item in transports if item in allowed] if isinstance(transports, list) else []
    return {"credential_id": b64url(parsed["credential_id"]), "public_key": parsed["public_key"], "sign_count": parsed["sign_count"], "transports": clean[:6]}


def verify_assertion(credential, stored_key: bytes, stored_count: int, user_handle: str, challenge_hash: str, rp_id: str, origin: str) -> int:
    response = _response(credential)
    client_raw = from_b64url(response.get("clientDataJSON"))
    _client_data(client_raw, "webauthn.get", challenge_hash, origin)
    data = from_b64url(response.get("authenticatorData"))
    parsed = parse_authenticator_data(data, attested=False)
    _common(parsed, rp_id)
    handle = response.get("userHandle")
    if not isinstance(handle, str) or not hmac.compare_digest(handle, user_handle):
        raise invalid()
    algorithm, key = public_key(stored_key)
    signed = data + hashlib.sha256(client_raw).digest()
    signature = from_b64url(response.get("signature"))
    try:
        if algorithm == ES256:
            key.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
        else:
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError):
        raise invalid() from None
    count = parsed["sign_count"]
    if (count or stored_count) and count <= stored_count:
        raise DomainError("Esta llave de acceso fue bloqueada por seguridad. Contacta a un administrador.", 401)
    return count
