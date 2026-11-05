"""Same-origin HTTP contracts. Secrets never cross the administrative API boundary."""

from __future__ import annotations

import hashlib
import asyncio
import logging
import json
import os
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .core import ROOT, DomainError, Store, calendar_file, site_origin, text

COOKIE = "powersolar_session"
CHAT_COOKIE = "reigel_webchat"


def load_environment(path=None):
    """Read simple KEY=value dotenv configuration without overriding process values."""
    path = Path(path or ROOT / ".env")
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key.replace("_", "a").isalnum() or not key or key[0].isdigit():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


class RateLimiter:
    def __init__(self):
        self.buckets = defaultdict(deque)

    def check(self, request, key, maximum, seconds):
        client = request.client.host if request.client else "unknown"
        current = time.monotonic()
        # Bound memory for opportunistic public traffic; do not trust X-Forwarded-For.
        if len(self.buckets) > 10000:
            stale = [k for k, v in self.buckets.items() if not v or v[-1] < current - 3600]
            for candidate in stale:
                self.buckets.pop(candidate, None)
            if len(self.buckets) > 10000:
                raise DomainError("Demasiadas solicitudes. Vuelve a intentarlo más tarde.", 429)
        bucket = self.buckets[(key, client)]
        while bucket and bucket[0] < current - seconds:
            bucket.popleft()
        if len(bucket) >= maximum:
            raise DomainError("Demasiadas solicitudes. Vuelve a intentarlo más tarde.", 429)
        bucket.append(current)

    def clear(self, request, key):
        client = request.client.host if request.client else "unknown"
        self.buckets.pop((key, client), None)


async def payload(request):
    if "application/json" not in request.headers.get("content-type", "").lower():
        raise DomainError("La solicitud debe usar JSON.", 415)
    try:
        value = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise DomainError("El contenido de la solicitud no es válido.", 422) from None
    if not isinstance(value, dict):
        raise DomainError("La solicitud debe contener un objeto.", 422)
    return value


def create_app(db_path=None):
    load_environment()
    production = os.environ.get("REIGEL_ENV", "local").lower() == "production"
    @asynccontextmanager
    async def lifespan(application):
        async def update_knowledge():
            while True:
                try:
                    await application.state.knowledge.refresh()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logging.getLogger(__name__).exception("No se pudo actualizar el conocimiento público")
                await asyncio.sleep(21600)
        # Tests and temporary previews have isolated databases and no implicit network.
        task = asyncio.create_task(update_knowledge()) if db_path is None else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="Power Solar · R.E.I.G.E.L.", version="1.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = Store(db_path)
    app.state.limiter = RateLimiter()
    from .knowledge import KnowledgeBase
    from .webchat import WebChat
    app.state.knowledge = KnowledgeBase(app.state.store)
    app.state.webchat = WebChat(app.state.store, app.state.knowledge)
    business = app.state.store.settings()
    environment_url = os.environ.get("SITE_URL", "").rstrip("/")
    if environment_url and environment_url != business.get("site_url"):
        # Deployment URL is controlled by the operator, not by untrusted requests.
        try:
            environment_url = site_origin(environment_url)
        except DomainError:
            raise RuntimeError("SITE_URL debe ser un origen HTTPS válido.") from None
        with app.state.store.connect() as db:
            db.execute("UPDATE settings SET value=? WHERE key='site_url'", (environment_url,))
    if production and not (environment_url or business.get("site_url", "")).startswith("https://"):
        raise RuntimeError("Producción requiere SITE_URL HTTPS y un proxy TLS correctamente configurado.")

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def input_error(request, exc):
        return JSONResponse({"detail": "Revisa los campos de la solicitud."}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        return JSONResponse({"detail": "No se pudo completar la operación. Inténtalo de nuevo."}, status_code=503)

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        frame_sources = "'self' https://docs.google.com" if request.url.path == "/" else "'self'"
        headers = {
            "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Content-Security-Policy": f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src {frame_sources}; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
        }
        if production:
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        site_url = app.state.store.settings().get("site_url", "")
        trusted = {"localhost", "127.0.0.1", "::1"}
        if db_path is not None:
            trusted.add("testserver")
        if site_url:
            trusted.add(urlparse(site_url).hostname)
        trusted.update(h.strip().lower() for h in os.environ.get("REIGEL_ALLOWED_HOSTS", "").split(",") if h.strip())
        if request.url.hostname not in trusted:
            return JSONResponse({"detail": "Servidor no autorizado."}, status_code=400, headers=headers)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = {str(request.base_url).rstrip("/")}
            if site_url:
                parsed = urlparse(site_url)
                expected.add(f"{parsed.scheme}://{parsed.netloc}")
            if origin and origin.rstrip("/") not in expected:
                return JSONResponse({"detail": "Origen de la solicitud no autorizado."}, status_code=403, headers=headers)
            try:
                size = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Solicitud no válida."}, status_code=400, headers=headers)
            maximum = 1024 * 1024 if request.url.path.startswith("/webhooks/") else 65536
            if size > maximum:
                return JSONResponse({"detail": "La solicitud es demasiado grande."}, status_code=413, headers=headers)
            if not request.url.path.startswith("/webhooks/") and len(await request.body()) > maximum:
                return JSONResponse({"detail": "La solicitud es demasiado grande."}, status_code=413, headers=headers)
        response = await call_next(request)
        for key, value in headers.items():
            response.headers[key] = value
        if request.url.path.startswith("/api/") or request.url.path == "/app":
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    def actor(request: Request):
        return app.state.store.session_user(request.cookies.get(COOKIE))

    def integrations():
        from .channels import integration_status
        return integration_status()

    @app.get("/health")
    async def health():
        with app.state.store.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": True}

    @app.post("/api/auth/login")
    async def login(request: Request):
        app.state.limiter.check(request, "login_ip", 100, 900)
        data = await payload(request)
        account = data.get("email", "")
        account = account.strip().casefold() if isinstance(account, str) else ""
        failure_key = "login:" + hashlib.sha256(account.encode()).hexdigest()
        app.state.limiter.check(request, failure_key, 8, 900)
        token, user = app.state.store.login(data.get("email"), data.get("password"))
        app.state.limiter.clear(request, failure_key)
        response = JSONResponse({"user": user})
        response.set_cookie(COOKIE, token, max_age=43200, httponly=True, secure=production, samesite="strict", path="/")
        return response

    @app.get("/api/auth/me")
    async def me(user=Depends(actor)):
        return {"user": user}

    @app.post("/api/auth/logout")
    async def logout(request: Request, user=Depends(actor)):
        app.state.store.logout(request.cookies.get(COOKIE))
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/", httponly=True, secure=production, samesite="strict")
        return response

    @app.post("/api/auth/password")
    async def change_password(request: Request, user=Depends(actor)):
        app.state.limiter.check(request, "password", 6, 900)
        data = await payload(request)
        app.state.store.change_password(data.get("current_password"), data.get("new_password"), user)
        response = JSONResponse({"ok": True, "message": "Contraseña actualizada. Inicia sesión de nuevo."})
        response.delete_cookie(COOKIE, path="/", httponly=True, secure=production, samesite="strict")
        return response

    @app.get("/api/dashboard")
    async def dashboard(user=Depends(actor)):
        return app.state.store.dashboard(user)

    @app.get("/api/leads")
    async def leads(user=Depends(actor)):
        return {"leads": app.state.store.list_leads(user)}

    @app.post("/api/leads", status_code=201)
    async def create_lead(request: Request, user=Depends(actor)):
        return {"lead": app.state.store.create_lead(await payload(request), user)}

    @app.get("/api/leads/{lead_id}")
    async def lead(lead_id: str, user=Depends(actor)):
        return {"lead": app.state.store.get_lead(lead_id, user), "appointments": app.state.store.list_appointments(user, lead_id)}

    @app.patch("/api/leads/{lead_id}")
    async def update_lead(lead_id: str, request: Request, user=Depends(actor)):
        return {"lead": app.state.store.update_lead(lead_id, await payload(request), user)}

    @app.get("/api/team")
    async def team(user=Depends(actor)):
        users = app.state.store.list_users()
        return {"users": users if user["role"] == "admin" else [u for u in users if u["id"] == user["id"]]}

    @app.post("/api/team", status_code=201)
    async def create_user(request: Request, user=Depends(actor)):
        return {"user": app.state.store.create_user(await payload(request), user)}

    @app.patch("/api/team/{user_id}")
    async def update_user(user_id: str, request: Request, user=Depends(actor)):
        return {"user": app.state.store.update_user(user_id, await payload(request), user)}

    @app.get("/api/settings")
    async def settings(user=Depends(actor)):
        return {"business": app.state.store.settings(), "integrations": integrations()}

    @app.patch("/api/settings")
    async def update_settings(request: Request, user=Depends(actor)):
        data = await payload(request)
        business = app.state.store.update_settings(data.get("business", data), user)
        return {"business": business, "integrations": integrations()}

    @app.get("/api/appointments")
    async def appointments(user=Depends(actor)):
        return {"appointments": app.state.store.list_appointments(user)}

    @app.post("/api/appointments", status_code=201)
    async def book(request: Request, user=Depends(actor)):
        return {"appointment": app.state.store.book(await payload(request), source="equipo", actor=user)}

    @app.patch("/api/appointments/{appointment_id}")
    async def cancel(appointment_id: str, request: Request, user=Depends(actor)):
        data = await payload(request)
        if data != {"status": "cancelled"}:
            raise DomainError("Solo se permite cancelar la cita.", 422)
        return {"appointment": app.state.store.cancel_appointment(appointment_id, user)}

    @app.get("/api/appointments/{appointment_id}/ics")
    async def download_calendar(appointment_id: str, user=Depends(actor)):
        appointment = app.state.store.get_appointment(appointment_id, user)
        return Response(calendar_file(appointment, app.state.store.settings()), media_type="text/calendar", headers={"Content-Disposition": f'attachment; filename="cita-{appointment["id"]}.ics"'})

    @app.get("/api/public/config")
    async def public_config():
        users = app.state.store.list_users()
        return {"business": app.state.store.settings(), "advisors": [{"id": u["id"], "name": u["name"]} for u in users if u["active"] and u["public_booking"]]}

    @app.get("/api/public/slots")
    async def public_slots(advisor_id: str, date: str, request: Request):
        app.state.limiter.check(request, "slots", 180, 60)
        return app.state.store.slots(advisor_id, date)

    @app.post("/api/public/leads", status_code=201)
    async def public_lead(request: Request):
        app.state.limiter.check(request, "public_intake", 30, 3600)
        lead = app.state.store.create_lead(await payload(request))
        return {"lead_id": lead["id"]}

    @app.post("/api/public/book", status_code=201)
    async def public_book(request: Request):
        app.state.limiter.check(request, "public_intake", 30, 3600)
        app.state.limiter.check(request, "public_booking", 10, 3600)
        appointment = app.state.store.book(await payload(request), source="web")
        return {"appointment": appointment, "message": "Tu cita quedó confirmada en la agenda de Power Solar."}

    def chat_token(request):
        token = request.cookies.get(CHAT_COOKIE)
        if not token:
            raise DomainError("Abre el chat para comenzar una conversación.", 401)
        return token

    @app.get("/api/public/chat")
    def public_chat(request: Request, response: Response):
        previous = request.cookies.get(CHAT_COOKIE)
        if previous:
            app.state.limiter.check(request, "chat_read", 120, 60)
            try:
                return app.state.webchat.state(previous)
            except DomainError:
                pass
        app.state.limiter.check(request, "chat_start", 60, 3600)
        token, state = app.state.webchat.start()
        response.set_cookie(CHAT_COOKIE, token, max_age=7*86400, httponly=True, secure=production, samesite="strict", path="/api/public/chat")
        return state

    @app.post("/api/public/chat")
    async def public_chat_message(request: Request):
        app.state.limiter.check(request, "chat_message", 60, 60)
        data = await payload(request)
        return app.state.webchat.message(chat_token(request), data.get("text"), data.get("request_id"))

    @app.post("/api/public/chat/book")
    async def public_chat_book(request: Request):
        app.state.limiter.check(request, "public_booking", 10, 3600)
        return app.state.webchat.book(chat_token(request), await payload(request))

    @app.post("/api/public/chat/human")
    def public_chat_human(request: Request):
        app.state.limiter.check(request, "chat_human", 20, 3600)
        return app.state.webchat.human(chat_token(request))

    @app.get("/api/knowledge")
    def knowledge(user=Depends(actor)):
        return app.state.knowledge.status()

    @app.post("/api/knowledge/refresh")
    async def refresh_knowledge(request: Request, user=Depends(actor)):
        app.state.store.require_admin(user)
        app.state.limiter.check(request, "knowledge_refresh", 6, 3600)
        return await app.state.knowledge.refresh(force=True)

    @app.get("/api/automation")
    async def automation(user=Depends(actor)):
        from .assistant import model_status
        return {"engine": "motor_comercial_local", "chat": "active", "paid_apis": "blocked", "local_model": await model_status(), "knowledge": app.state.knowledge.status(), "booking": {"timezone": app.state.store.settings()["timezone"], "public_advisors": sum(u["active"] and u["public_booking"] for u in app.state.store.list_users())}, "notice": "Chat y agenda propios. La actualización requiere Internet y el servidor encendido. Las ventas se concretan con una propuesta aceptada por el cliente."}

    @app.get("/api/conversations")
    async def conversations(user=Depends(actor)):
        return {"conversations": app.state.store.list_conversations(user)}

    @app.get("/api/conversations/{conversation_id}")
    async def conversation(conversation_id: str, user=Depends(actor)):
        return {"conversation": app.state.store.conversation(conversation_id, user), "messages": app.state.store.conversation_messages(conversation_id, user)}

    @app.patch("/api/conversations/{conversation_id}")
    async def assign_conversation(conversation_id: str, request: Request, user=Depends(actor)):
        return {"conversation": app.state.store.assign_conversation(conversation_id, await payload(request), user)}

    @app.post("/api/conversations/{conversation_id}/mode")
    async def conversation_mode(conversation_id: str, request: Request, user=Depends(actor)):
        from .channels import reply_permission
        data = await payload(request)
        current = app.state.store.conversation(conversation_id, user)
        if data.get("mode") == "ai":
            permission = reply_permission(app.state.store, current)
            if not permission["allowed"]:
                raise DomainError(permission["reason"], 409)
            ai = next((item for item in integrations() if item["id"] == "ai"), None)
            if current["channel"] != "web" and ai and not ai.get("configured"):
                raise DomainError("Configura el proveedor de IA antes de activarla.", 503)
        return {"conversation": app.state.store.set_conversation_mode(conversation_id, data.get("mode"), user)}

    @app.post("/api/conversations/{conversation_id}/messages")
    async def send(conversation_id: str, request: Request, user=Depends(actor)):
        from .channels import reply_permission, send_message
        data = await payload(request)
        value = text(data.get("text"), "mensaje", limit=4000, required=True)
        current = app.state.store.conversation(conversation_id, user)
        permission = reply_permission(app.state.store, current)
        if not permission["allowed"]:
            raise DomainError(permission["reason"], 409)
        # Human send pauses the bot so it cannot immediately answer over the advisor.
        app.state.store.set_conversation_mode(conversation_id, "human", user)
        if current["channel"] == "web":
            # Persisted locally; the visitor receives it by polling their own cookie-bound chat.
            result = {"status": "sent"}
        else:
            result = await send_message(current["channel"], current["external_id"], value)
        message = app.state.store.record_outbound(conversation_id, value, result, user)
        if result["status"] != "sent":
            code = 504 if result["status"] == "uncertain" else 502
            raise DomainError("No se pudo confirmar el envío. Revisa la conversación antes de volver a enviar." if code == 504 else "El proveedor no aceptó el mensaje. Revisa la conexión del canal.", code)
        return {"message": message}

    @app.get("/api/integrations")
    async def integration_list(user=Depends(actor)):
        return {"integrations": integrations()}

    @app.post("/api/assistant/draft")
    async def draft(request: Request, user=Depends(actor)):
        from .assistant import draft as make_draft
        app.state.limiter.check(request, "ai_draft", 30, 3600)
        data = await payload(request)
        prompt = text(data.get("prompt"), "instrucción", limit=3500, required=True)
        if data.get("lead_id"):
            lead_id = text(data["lead_id"], "contacto", limit=100, required=True)
            lead = app.state.store.get_lead(lead_id, user)
            # Purpose-limited business context; do not transmit contact details unnecessarily.
            prompt += f"\nContexto comercial: municipio {lead['municipality']}; etapa {lead['stage']}."
        try:
            business = app.state.store.settings()
            evidence = app.state.knowledge.answer(prompt)
            if evidence:
                business["verified_context"] = evidence["text"]
            value = await make_draft(prompt, business)
        except ValueError as exc:
            raise DomainError("El modelo local todavía no está disponible. Revisa Ollama y el modelo instalado.", 503) from None
        except RuntimeError:
            raise DomainError("El modelo local no generó un borrador verificable. Revisa la solicitud o usa las plantillas.", 502) from None
        return {"text": value, "engine": "ollama_local", "review_required": True}

    from .channels import register_routes
    register_routes(app)
    from . import seo
    seo.register_routes(app)

    @app.get("/app", include_in_schema=False)
    async def workspace():
        return FileResponse(ROOT / "frontend" / "index.html")

    @app.get("/", include_in_schema=False)
    async def landing():
        return seo.landing_response(app.state.store)

    app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
    return app
