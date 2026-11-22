"""HTTP contracts for R.E.I.G.E.L. Identity. Customer and Team cookies never overlap."""

from __future__ import annotations

import hmac
from urllib.parse import urlparse

from fastapi import Depends, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .core import ROOT, DomainError
from .identity import Identity, csrf_for

CUSTOMER_COOKIE = "reigel_customer"
OAUTH_COOKIE = "reigel_oauth"
WEBAUTHN_COOKIE = "reigel_webauthn"


def register_identity(app, *, production, team_cookie, team_actor, payload):
    app.state.identity = Identity(app.state.store)
    app.state.oauth_transport = None
    identity = lambda: app.state.identity
    limit = lambda request, key, maximum, seconds: app.state.limiter.check(request, key, maximum, seconds)

    def origin_config(request):
        site = app.state.store.settings().get("site_url", "")
        if site:
            parsed = urlparse(site)
            return parsed.hostname, f"{parsed.scheme}://{parsed.netloc}"
        if not production and request.url.hostname == "localhost":
            return "localhost", str(request.base_url).rstrip("/")
        raise DomainError("Las llaves de acceso requieren un dominio HTTPS o localhost.", 503)

    def require_csrf(request, cookie):
        token = request.cookies.get(cookie, "")
        if not token or not hmac.compare_digest(request.headers.get("x-reigel-csrf", ""), csrf_for(token)):
            raise DomainError("La solicitud no pudo validarse. Recarga la página.", 403)

    def customer_actor(request: Request):
        return identity().session_customer(request.cookies.get(CUSTOMER_COOKIE))

    def customer_write(request: Request):
        customer = customer_actor(request)
        require_csrf(request, CUSTOMER_COOKIE)
        return customer

    def team_write(request: Request):
        user = team_actor(request)
        require_csrf(request, team_cookie)
        return user

    def with_customer_cookie(response, token):
        response.set_cookie(CUSTOMER_COOKIE, token, max_age=14 * 86400, httponly=True, secure=production, samesite="strict", path="/")
        return response

    def with_challenge(response, challenge_id):
        response.set_cookie(WEBAUTHN_COOKIE, challenge_id, max_age=300, httponly=True, secure=production, samesite="strict", path="/api/team-identity/passkeys")
        return response

    def clear_challenge(response):
        response.delete_cookie(WEBAUTHN_COOKIE, path="/api/team-identity/passkeys", httponly=True, secure=production, samesite="strict")
        return response

    def customer_body(token, customer):
        return {"customer": customer, "csrf": csrf_for(token)}

    def redirect_uri(request, provider):
        site = app.state.store.settings().get("site_url", "")
        base = site.rstrip("/") if site else str(request.base_url).rstrip("/")
        return f"{base}/api/customer/oauth/{provider}/callback"

    @app.get("/cuenta", include_in_schema=False)
    async def account_page():
        return FileResponse(ROOT / "frontend" / "account.html", headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"})

    @app.get("/app/acceso", include_in_schema=False)
    async def team_access_page():
        return FileResponse(ROOT / "frontend" / "team-access.html", headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"})

    @app.get("/api/customer/config")
    async def customer_config():
        delivery = identity().delivery
        return {"providers": identity().enabled_providers(), "verification": {"email": delivery.available("email"), "phone": delivery.available("phone")}}

    @app.post("/api/customer/register", status_code=201)
    async def customer_register(request: Request):
        limit(request, "customer_register", 10, 3600)
        token, customer = identity().register(await payload(request))
        return with_customer_cookie(JSONResponse(customer_body(token, customer), status_code=201), token)

    @app.post("/api/customer/login")
    async def customer_login(request: Request):
        limit(request, "customer_login_ip", 60, 900)
        data = await payload(request)
        account = data.get("identifier")
        key = "customer_login:" + (account.strip().casefold()[:254] if isinstance(account, str) else "")
        limit(request, key, 8, 900)
        token, customer = identity().login(account, data.get("password"))
        app.state.limiter.clear(request, key)
        return with_customer_cookie(JSONResponse(customer_body(token, customer)), token)

    @app.get("/api/customer/me")
    async def customer_me(request: Request, customer=Depends(customer_actor)):
        return customer_body(request.cookies.get(CUSTOMER_COOKIE), customer)

    @app.post("/api/customer/logout")
    async def customer_logout(request: Request, customer=Depends(customer_write)):
        identity().logout(request.cookies.get(CUSTOMER_COOKIE))
        response = JSONResponse({"ok": True})
        response.delete_cookie(CUSTOMER_COOKIE, path="/", httponly=True, secure=production, samesite="strict")
        return response

    @app.post("/api/customer/password")
    async def customer_password(request: Request, customer=Depends(customer_write)):
        limit(request, "customer_password", 6, 900)
        data = await payload(request)
        identity().change_password(customer, data.get("current_password"), data.get("new_password"), request.cookies.get(CUSTOMER_COOKIE))
        return {"ok": True}

    @app.post("/api/customer/verify/start")
    async def customer_verify_start(request: Request, customer=Depends(customer_write)):
        limit(request, "customer_verify_start", 5, 900)
        data = await payload(request)
        identity().start_verification(customer, data.get("identifier_id"))
        return {"ok": True}

    @app.post("/api/customer/verify/finish")
    async def customer_verify_finish(request: Request, customer=Depends(customer_write)):
        limit(request, "customer_verify_finish", 15, 900)
        data = await payload(request)
        return {"customer": identity().finish_verification(customer, data.get("identifier_id"), data.get("code"))}

    @app.post("/api/customer/recover/start", status_code=202)
    async def customer_recover_start(request: Request):
        limit(request, "customer_recover_start", 5, 900)
        data = await payload(request)
        identity().start_recovery(data.get("identifier"))
        return {"ok": True, "message": "Si el dato está verificado, recibirás un código."}

    @app.post("/api/customer/recover/finish")
    async def customer_recover_finish(request: Request):
        limit(request, "customer_recover_finish", 10, 900)
        data = await payload(request)
        identity().finish_recovery(data.get("identifier"), data.get("code"), data.get("new_password"))
        return {"ok": True}

    @app.get("/api/customer/entitlements")
    async def customer_entitlements(customer=Depends(customer_actor)):
        return {"items": identity().entitlements(customer)}

    @app.post("/api/customer/oauth/{provider}/start")
    async def customer_oauth_start(provider: str, request: Request):
        limit(request, "customer_oauth_start", 20, 900)
        data = await payload(request)
        mode = data.get("mode", "login")
        customer = customer_write(request) if mode == "link" else None
        url, binding = identity().oauth_start(provider, mode, customer, redirect_uri(request, provider))
        response = JSONResponse({"url": url})
        # Lax is required: the provider returns through a cross-site top-level navigation.
        response.set_cookie(OAUTH_COOKIE, binding, max_age=600, httponly=True, secure=production, samesite="lax", path="/api/customer/oauth")
        return response

    @app.get("/api/customer/oauth/{provider}/callback", include_in_schema=False)
    async def customer_oauth_callback(provider: str, request: Request):
        limit(request, "customer_oauth_callback", 30, 900)
        params = request.query_params
        try:
            token = await identity().oauth_callback(provider, params.get("code"), params.get("state"), request.cookies.get(OAUTH_COOKIE),
                                                     redirect_uri(request, provider), app.state.oauth_transport)
            response = RedirectResponse("/cuenta", status_code=303)
            if token:
                with_customer_cookie(response, token)
        except DomainError:
            response = RedirectResponse("/cuenta?error=oauth", status_code=303)
        response.delete_cookie(OAUTH_COOKIE, path="/api/customer/oauth", httponly=True, secure=production, samesite="lax")
        return response

    @app.delete("/api/customer/oauth/{provider}")
    async def customer_oauth_unlink(provider: str, customer=Depends(customer_write)):
        return {"customer": identity().unlink_provider(customer, provider)}

    @app.get("/api/team-identity/me")
    async def team_me(request: Request, user=Depends(team_actor)):
        return identity().team_profile(user) | {"csrf": csrf_for(request.cookies.get(team_cookie))}

    @app.post("/api/team-identity/passkeys/register/options")
    async def team_register_options(request: Request):
        limit(request, "team_passkey_register", 12, 900)
        data = await payload(request)
        rp_id, _ = origin_config(request)
        user = None
        if request.cookies.get(team_cookie) and not data.get("code"):
            user = team_write(request)
        challenge_id, options = identity().register_options(rp_id, "R.E.I.G.E.L. Team Access", user=user, email=data.get("email"), code=data.get("code"))
        return with_challenge(JSONResponse({"publicKey": options}), challenge_id)

    @app.post("/api/team-identity/passkeys/register/verify", status_code=201)
    async def team_register_verify(request: Request):
        limit(request, "team_passkey_register", 12, 900)
        data = await payload(request)
        rp_id, origin = origin_config(request)
        user = team_write(request) if request.cookies.get(team_cookie) and not data.get("with_code") else None
        passkey = identity().register_finish(request.cookies.get(WEBAUTHN_COOKIE, ""), data.get("credential"), data.get("label"), rp_id, origin, session_user=user)
        return clear_challenge(JSONResponse({"passkey": passkey}, status_code=201))

    @app.post("/api/team-identity/passkeys/login/options")
    async def team_login_options(request: Request):
        limit(request, "team_passkey_login", 30, 900)
        rp_id, _ = origin_config(request)
        challenge_id, options = identity().login_options(rp_id)
        return with_challenge(JSONResponse({"publicKey": options}), challenge_id)

    @app.post("/api/team-identity/passkeys/login/verify")
    async def team_login_verify(request: Request):
        limit(request, "team_passkey_login", 30, 900)
        data = await payload(request)
        rp_id, origin = origin_config(request)
        token, user = identity().login_finish(request.cookies.get(WEBAUTHN_COOKIE, ""), data.get("credential"), rp_id, origin)
        response = clear_challenge(JSONResponse({"user": user}))
        response.set_cookie(team_cookie, token, max_age=43200, httponly=True, secure=production, samesite="strict", path="/")
        return response

    @app.delete("/api/team-identity/passkeys/{device_id}")
    async def team_revoke_passkey(device_id: str, user=Depends(team_write)):
        identity().revoke_own_passkey(device_id, user)
        return {"ok": True}

    @app.get("/api/team-identity/devices/pending")
    async def team_pending_devices(user=Depends(team_actor)):
        return {"items": identity().pending_devices(user)}

    @app.post("/api/team-identity/devices/{device_id}/decision")
    async def team_device_decision(device_id: str, request: Request, user=Depends(team_write)):
        data = await payload(request)
        if not isinstance(data.get("approve"), bool):
            raise DomainError("Decisión no válida.", 422)
        return {"passkey": identity().decide_device(device_id, data["approve"], user)}

    @app.post("/api/team-identity/users/{user_id}/grant")
    async def team_issue_grant(user_id: str, request: Request, user=Depends(team_write)):
        limit(request, "team_grant", 12, 3600)
        data = await payload(request)
        return identity().issue_grant(user_id, data.get("purpose"), data.get("reason"), user)

    @app.put("/api/team-identity/users/{user_id}/role")
    async def team_set_role(user_id: str, request: Request, user=Depends(team_write)):
        data = await payload(request)
        return identity().set_team_role(user_id, data.get("role"), user)

    @app.put("/api/team-identity/policy")
    async def team_policy(request: Request, user=Depends(team_write)):
        data = await payload(request)
        return identity().set_passkey_policy(data.get("passkey_required"), user)
