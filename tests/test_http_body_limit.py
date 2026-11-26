"""Reject oversized streamed requests before consuming the remaining body."""

import asyncio
import json

import httpx
import pytest

from reigel import api


@pytest.fixture
def isolated_app(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "load_environment", lambda: None)
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.setenv("SITE_URL", "")
    monkeypatch.setenv("REIGEL_ALLOWED_HOSTS", "")
    app = api.create_app(tmp_path / "body-limit.sqlite3")
    app.state.store.create_user({
        "name": "Body limit test",
        "email": "body-limit@example.test",
        "password": "Body-limit-test-2026!",
        "role": "admin",
    }, bootstrap=True)
    return app


def test_chunked_body_stops_at_first_chunk_over_limit(isolated_app):
    async def exercise():
        consumed = 0

        async def body():
            nonlocal consumed
            for _ in range(32):
                consumed += 1
                yield b" " * 32768

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=isolated_app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/auth/login", content=body(),
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code == 413
        assert consumed == 3
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]

    asyncio.run(exercise())


@pytest.mark.parametrize("body_size", [65535, 65536])
def test_valid_chunked_json_is_replayed_intact(isolated_app, body_size):
    async def exercise():
        value = json.dumps({
            "email": "body-limit@example.test",
            "password": "Body-limit-test-2026!",
        }).encode()
        value += b" " * (body_size - len(value))

        async def body():
            for offset in range(0, len(value), 8192):
                yield value[offset:offset + 8192]

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=isolated_app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/auth/login", content=body(),
                headers={"Content-Type": "application/json"},
            )
            # The replayed body reached the password check: a correct password
            # yields only the mandatory Google Authenticator enrollment step.
            assert response.status_code == 200
            assert response.json() == {"mfa_required": True, "enrollment_required": True}
            cookie = response.headers["set-cookie"].lower()
            assert "reigel_team_enroll=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
            assert "powersolar_session=" not in cookie
            assert (await client.get("/api/auth/me")).status_code == 401

    asyncio.run(exercise())
