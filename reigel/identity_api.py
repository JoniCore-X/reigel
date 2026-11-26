"""HTTP contracts for R.E.I.G.E.L. Identity. Customer and Team cookies never overlap."""

from __future__ import annotations

import hmac

from fastapi import Depends, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .core import ROOT, DomainError
from .identity import Identity, csrf_for

CUSTOMER_COOKIE = "reigel_customer"
OAUTH_COOKIE = "reigel_oauth"
MFA_COOKIE = "reigel_team_mfa"
ENROLL_COOKIE = "reigel_team_enroll"
TOTP_SETUP_COOKIE = "reigel_totp_setup"
TOTP_PATH = "/api/team-identity/totp"


def register_identity(app, *, production, team_cookie, team_actor, payload):
    app.state.identity = Identity(app.state.store)
    app.state.oauth_transport = None
    identity = lambda: app.state.identity
    limit = lambda request, key, maximum, seconds: app.state.limiter.check(request, key, maximum, seconds)

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

    def with_totp_cookie(response, name, value, seconds):
        response.set_cookie(name, value, max_age=seconds, httponly=True, secure=production, samesite="strict", path=TOTP_PATH)
        return response

    def clear_totp_cookie(response, name):
        response.delete_cookie(name, path=TOTP_PATH, httponly=True, secure=production, samesite="strict")
        return response

    def team_mfa_response(step):
        """A correct password only ever yields a second step; never the team session cookie."""
        if step["mfa"] == "enroll":
            ticket = identity().begin_enrollment(step["user_id"])
            response = JSONResponse({"mfa_required": True, "enrollment_required": True})
            return with_totp_cookie(clear_totp_cookie(response, MFA_COOKIE), ENROLL_COOKIE, ticket, 600)
        response = clear_totp_cookie(JSONResponse({"mfa_required": True}), ENROLL_COOKIE)
        return with_totp_cookie(response, MFA_COOKIE, identity().begin_mfa(step["user_id"]), 300)

    def with_team_session(response, token):
        response.set_cookie(team_cookie, token, max_age=43200, httponly=True, secure=production, samesite="strict", path="/")
        return response

    app.state.team_mfa_response = team_mfa_response

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

    @app.post("/api/team-identity/totp/login")
    async def team_totp_login(request: Request):
        limit(request, "team_totp_login", 20, 900)
        data = await payload(request)
        token, user = identity().totp_login(request.cookies.get(MFA_COOKIE), data.get("code"))
        return with_team_session(clear_totp_cookie(JSONResponse({"user": user}), MFA_COOKIE), token)

    @app.post("/api/team-identity/totp/enroll")
    async def team_totp_enroll(request: Request):
        """First login of an account without Google Authenticator: returns the QR."""
        limit(request, "team_totp_enroll", 12, 900)
        ticket, setup = identity().enrollment_setup(request.cookies.get(ENROLL_COOKIE))
        return with_totp_cookie(JSONResponse({"setup": setup}), TOTP_SETUP_COOKIE, ticket, 600)

    @app.post("/api/team-identity/totp/enroll/confirm")
    async def team_totp_enroll_confirm(request: Request):
        limit(request, "team_totp_enroll_confirm", 12, 900)
        data = await payload(request)
        token, user = identity().enrollment_confirm(request.cookies.get(ENROLL_COOKIE), request.cookies.get(TOTP_SETUP_COOKIE), data.get("code"))
        response = clear_totp_cookie(clear_totp_cookie(JSONResponse({"user": user}), ENROLL_COOKIE), TOTP_SETUP_COOKIE)
        return with_team_session(response, token)

    @app.post("/api/team-identity/totp/setup")
    async def team_totp_setup(request: Request):
        limit(request, "team_totp_setup", 12, 900)
        data = await payload(request)
        user = team_write(request) if not data.get("grant_code") else None
        ticket, setup = identity().totp_setup(user=user, email=data.get("email"), grant_code=data.get("grant_code"), current_code=data.get("current_code"))
        return with_totp_cookie(JSONResponse({"setup": setup}), TOTP_SETUP_COOKIE, ticket, 600)

    @app.post("/api/team-identity/totp/confirm")
    async def team_totp_confirm(request: Request):
        limit(request, "team_totp_confirm", 12, 900)
        data = await payload(request)
        user = team_write(request) if not data.get("with_grant") else None
        result = identity().totp_confirm(request.cookies.get(TOTP_SETUP_COOKIE), data.get("code"), session_user=user)
        return clear_totp_cookie(JSONResponse(result), TOTP_SETUP_COOKIE)

    # There is deliberately no route to turn Google Authenticator off. A lost
    # device is replaced only through an admin-issued recovery grant.

    @app.post("/api/team-identity/users/{user_id}/grant")
    async def team_issue_grant(user_id: str, request: Request, user=Depends(team_write)):
        limit(request, "team_grant", 12, 3600)
        data = await payload(request)
        return identity().issue_grant(user_id, data.get("purpose"), data.get("reason"), user)

    @app.put("/api/team-identity/users/{user_id}/role")
    async def team_set_role(user_id: str, request: Request, user=Depends(team_write)):
        data = await payload(request)
        return identity().set_team_role(user_id, data.get("role"), user)

    # Owner-only allowlist and "Power Solar" naming rule. Emails travel in the JSON
    # body, never in the URL. Every write needs the session CSRF value.
    store = lambda: app.state.store

    def owner_limits(request, user, key, maximum, seconds):
        limit(request, key, maximum, seconds)
        app.state.limiter.check(request, f"{key}:account", maximum, seconds, client=user["id"])

    @app.get("/api/team-access")
    async def team_access_overview(request: Request, user=Depends(team_actor)):
        owner_limits(request, user, "team_access_read", 120, 60)
        return store().team_access(user)

    @app.post("/api/team-access/emails")
    async def team_access_add(request: Request, user=Depends(team_write)):
        owner_limits(request, user, "team_access_write", 30, 3600)
        data = await payload(request)
        return store().allow_team_email(data.get("email"), user)

    @app.post("/api/team-access/emails/remove")
    async def team_access_remove(request: Request, user=Depends(team_write)):
        owner_limits(request, user, "team_access_write", 30, 3600)
        data = await payload(request)
        return store().remove_team_email(data.get("email"), user)

    @app.put("/api/team-access/name-rule")
    async def team_access_rule(request: Request, user=Depends(team_write)):
        owner_limits(request, user, "team_access_write", 30, 3600)
        data = await payload(request)
        return store().set_team_name_rule(data.get("enabled"), user)
