"""Same-origin HTTP contracts. Secrets never cross the administrative API boundary."""

from __future__ import annotations

import hashlib
import asyncio
import logging
import json
import os
import re
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .core import ROOT, DomainError, Store, calendar_file, site_origin, text
from .ia_workspace import AIWorkspace, VISITOR_DAYS

COOKIE = "powersolar_session"
CHAT_COOKIE = "reigel_webchat"
IA_COOKIE = "reigel_ia"
# Raw document uploads in /ia: the only route whose body is streamed by the
# endpoint itself, so each owner's size limit applies before the file is read.
IA_ATTACHMENT_PATH = re.compile(r"/api/ia/conversations/[^/]+/attachments")


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

    def check(self, request, key, maximum, seconds, client=None):
        # ``client`` scopes a bucket to something other than the address (an
        # /ia visitor session, for instance); by default it is the address.
        if client is None:
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


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(db_path=None, *, load_env=None):
    # The project .env holds the operating configuration and credentials. Only
    # the default construction (main.py: no explicit database) reads it; an
    # explicit path means a test, preview or tool with its own configuration.
    # Pass load_env=True to opt in deliberately.
    if load_env is None:
        load_env = db_path is None
    if load_env:
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
    app.state.ia = AIWorkspace(app.state.store)
    # At most two PDF extraction workers at a time; others wait their turn.
    app.state.document_slots = asyncio.Semaphore(2)
    from .learning import LearningQueue
    # Additive, idempotent migration on this app's database; tests and previews
    # pass their own temporary path. The 90-day retention runs at most daily.
    app.state.learning = LearningQueue(app.state.store)
    app.state.learning.maybe_purge()
    app.state.learning_eval = {"task": None, "error": "", "started_at": None}
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
        frame_sources = "'self' https://docs.google.com" if request.url.path == "/contacto" else "'self'"
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
            attachment = request.method == "POST" and IA_ATTACHMENT_PATH.fullmatch(request.url.path)
            if attachment:
                from .documents import TEAM
                if "content-length" not in request.headers:
                    return JSONResponse({"detail": "Falta el tamaño del archivo."}, status_code=411, headers=headers)
                maximum = TEAM.max_bytes
            else:
                maximum = 1024 * 1024 if request.url.path.startswith("/webhooks/") else 65536
            if size > maximum:
                return JSONResponse({"detail": "La solicitud es demasiado grande."}, status_code=413, headers=headers)
            if not request.url.path.startswith("/webhooks/") and not attachment:
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > maximum:
                        return JSONResponse({"detail": "La solicitud es demasiado grande."}, status_code=413, headers=headers)
                    body.extend(chunk)
                # BaseHTTPMiddleware replays this bounded cache to the endpoint.
                request._body = bytes(body)
        response = await call_next(request)
        for key, value in headers.items():
            response.headers[key] = value
        if request.url.path.startswith("/api/") or request.url.path in {"/", "/app", "/ia"}:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    def actor(request: Request):
        return app.state.store.session_user(request.cookies.get(COOKIE))

    def record_gap(route, reason, question):
        """Learning capture never blocks or breaks a reply, and logs no content."""
        try:
            app.state.learning.record_gap(route, reason, question)
        except Exception:
            logging.getLogger(__name__).warning("No se pudo registrar un hueco de aprendizaje (%s, %s).", route, reason)

    def reviewed(question, route):
        """Approved team answers for the prompt, or {} so callers keep their old signature."""
        try:
            items = app.state.learning.reviewed_for(question, route)
        except Exception:
            items = []
        return {"reviewed": items} if items else {}

    def integrations():
        from .channels import integration_status
        values = integration_status()
        if getattr(app.state, "synthetic_preview", False):
            for item in values:
                if item.get("id") not in {"web", "ai"}:
                    item.update(configured=False, status="disabled_preview", detail="Deshabilitado en demostración sintética")
        return values

    from .identity_api import register_identity
    register_identity(app, production=production, team_cookie=COOKIE, team_actor=actor, payload=payload)

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
        if token is None:
            return app.state.team_mfa_response(user["mfa_user_id"])
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
    async def dashboard(period: str = "all", start: str = "", end: str = "", user=Depends(actor)):
        return app.state.store.operations_dashboard(user, period=period, start=start, end=end)

    @app.get("/api/leads")
    async def leads(q: str = "", stage: str = "", advisor_id: str = "", sort: str = "created_at", order: str = "desc", limit: int = 100, offset: int = 0, user=Depends(actor)):
        return app.state.store.query_leads(user, q=q, stage=stage, advisor_id=advisor_id, sort=sort, order=order, limit=limit, offset=offset)

    @app.post("/api/leads", status_code=201)
    async def create_lead(request: Request, user=Depends(actor)):
        return {"lead": app.state.store.create_lead(await payload(request), user)}

    @app.get("/api/leads/{lead_id}")
    async def lead(lead_id: str, user=Depends(actor)):
        return app.state.store.lead_detail(lead_id, user)

    @app.patch("/api/leads/{lead_id}")
    async def update_lead(lead_id: str, request: Request, user=Depends(actor)):
        return {"lead": app.state.store.update_lead(lead_id, await payload(request), user)}

    @app.post("/api/leads/{lead_id}/activities", status_code=201)
    async def create_activity(lead_id: str, request: Request, user=Depends(actor)):
        return {"activity": app.state.store.create_activity(lead_id, await payload(request), user)}

    @app.get("/api/tasks")
    async def tasks(status: str = "", lead_id: str = "", owner_id: str = "", limit: int = 100, offset: int = 0, user=Depends(actor)):
        return app.state.store.query_tasks(user, status=status, lead_id=lead_id, owner_id=owner_id, limit=limit, offset=offset)

    @app.get("/api/tasks/{task_id}")
    async def task(task_id: str, user=Depends(actor)):
        with app.state.store.connect() as db:
            return {"task": app.state.store._task(db, task_id, user)}

    @app.post("/api/tasks", status_code=201)
    async def create_task(request: Request, user=Depends(actor)):
        return {"task": app.state.store.save_task(await payload(request), user)}

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, request: Request, user=Depends(actor)):
        return {"task": app.state.store.save_task(await payload(request), user, task_id)}

    @app.get("/api/notifications")
    async def notifications(limit: int = 100, offset: int = 0, user=Depends(actor)):
        return app.state.store.list_notifications(user, limit=limit, offset=offset)

    @app.patch("/api/notifications/{notification_id}")
    async def notification(notification_id: str, request: Request, user=Depends(actor)):
        return {"notification": app.state.store.mark_notification(notification_id, await payload(request), user)}

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

    @app.post("/api/team/{user_id}/offboard")
    async def offboard_user(user_id: str, request: Request, user=Depends(actor)):
        return app.state.store.offboard_user(user_id, await payload(request), user)

    @app.get("/api/owner/plans")
    async def owner_plans(user=Depends(actor)):
        from .plans import overview
        app.state.store.require_owner(user)
        return overview(app.state.store.list_users())

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
        return {"appointment": app.state.store.update_appointment(appointment_id, await payload(request), user)}

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
        token = chat_token(request)
        from . import ai_chat
        brief = app.state.webchat.ai_brief(token, data.get("text"), data.get("request_id")) if ai_chat.enabled() else None
        ai_reply = None
        if brief:
            app.state.limiter.check(request, "chat_ai", 20, 60)
            ai_reply = await ai_chat.reply(brief["incoming"], brief["history"], brief["profile"], brief["verified"],
                                           **reviewed(brief["incoming"], "chat"))
        gaps = []
        result = app.state.webchat.message(
            token, data.get("text"), data.get("request_id"),
            ai_reply=ai_reply, ai_fingerprint=brief["fingerprint"] if brief else None, gaps=gaps,
        )
        if brief and ai_reply is None:
            # The model was asked and its draft was missing or withdrawn: the fallback was used.
            record_gap("chat", "fallback", brief["incoming"])
        else:
            for reason, question in gaps[:1]:
                record_gap("chat", reason, question)
        return result

    @app.post("/api/public/chat/book")
    async def public_chat_book(request: Request):
        app.state.limiter.check(request, "public_booking", 10, 3600)
        return app.state.webchat.book(chat_token(request), await payload(request))

    @app.post("/api/public/chat/human")
    def public_chat_human(request: Request):
        app.state.limiter.check(request, "chat_human", 20, 3600)
        return app.state.webchat.human(chat_token(request))

    def ia_owner(request, response=None):
        try:
            user = app.state.store.session_user(request.cookies.get(COOKIE))
        except DomainError:
            user = None
        if user:
            return app.state.ia.user_owner(user), user
        existing = app.state.ia.visitor(request.cookies.get(IA_COOKIE))
        if existing:
            if response is not None:
                renew_visitor(request, response)
            return {"kind": "visitor", "id": existing}, None
        if response is None:
            raise DomainError("Abre la conversación para iniciar una sesión temporal.", 401)
        key, token = app.state.ia.ensure_visitor()
        set_visitor_cookie(response, token)
        return {"kind": "visitor", "id": key}, None

    def set_visitor_cookie(response, token):
        response.set_cookie(
            IA_COOKIE, token, max_age=VISITOR_DAYS * 86400, httponly=True,
            secure=production, samesite="strict", path="/api/ia",
        )

    def renew_visitor(request, response):
        # Retention is seven days from the last activity: opening /ia
        # (bootstrap) or sending/regenerating a message. Reading history alone
        # does not extend it. The database expiry and the browser cookie move
        # together so neither outlives the other.
        token = request.cookies.get(IA_COOKIE)
        if app.state.ia.touch_visitor(token):
            set_visitor_cookie(response, token)
        return response

    def ia_events(request, owner, conversation, incoming, history, assistant, regenerate=False, document=None):
        async def events():
            from . import ai_chat, safety
            # Output boundary: model text reaches the client, the database and
            # later prompts only after the validator accepted it. The boundary
            # is ai_chat.WorkspaceOutput, shared with the question bank
            # (learning_eval.publish); text past `output.validated` is never
            # exposed or persisted.
            output = None
            previous = assistant["content"] if regenerate else ""
            saved = False
            counter = 0

            def persist(value, status):
                nonlocal saved
                saved = True
                return app.state.ia.finish_assistant(assistant["id"], value, status)

            def reject():
                record_gap("ia", "blocked", incoming)
                return persist(ai_chat.SAFE_REPLACEMENT, "rejected"), {
                    "detail": "La respuesta se retiró por seguridad y se muestra un mensaje alternativo.",
                }

            def preserve_partial(keep_empty=False):
                validated = output.validated.strip() if output else ""
                if validated:
                    return persist(validated, "stopped")
                if regenerate and previous:
                    return persist(previous, "complete")
                if keep_empty:
                    # An explicit stop before the first token keeps the turn so
                    # the visitor can regenerate it instead of retyping.
                    return persist("", "stopped")
                app.state.ia.discard_assistant(assistant["id"])
                return None

            try:
                yield sse("meta", {
                    "conversation": conversation,
                    "assistant_id": assistant["id"],
                    "regenerate": regenerate,
                })
                # Safety topics get a fixed reply and never reach the model.
                fixed = safety.reply_for(incoming)
                if fixed:
                    yield sse("delta", {"text": fixed})
                    item = persist(fixed, "complete")
                    yield sse("done", {
                        "assistant": item,
                        "conversation": app.state.ia.conversation_summary(owner, conversation["id"]),
                    })
                    return
                answer = app.state.knowledge.answer(incoming)
                verified = answer.get("text", "") if isinstance(answer, dict) else ""
                output = ai_chat.WorkspaceOutput(incoming, history, verified)
                # A document reaches the model only as delimited, untrusted data.
                extra = {"document": document} if document else {}
                stream = ai_chat.stream_workspace(ai_chat.safe_history(history), incoming, verified,
                                                  **reviewed(incoming, "ia"), **extra)
                try:
                    try:
                        async for piece in stream:
                            counter += 1
                            if counter % 8 == 0 and await request.is_disconnected():
                                preserve_partial(keep_empty=True)
                                return
                            text_ready = output.feed(piece)
                            if output.overflow:
                                break
                            if text_ready:
                                yield sse("delta", {"text": text_ready})
                    finally:
                        await stream.aclose()
                    tail, closing, final = output.finish()
                except ai_chat.WorkspaceRejected:
                    item, extra = reject()
                    yield sse("replace", {"assistant": item, **extra})
                    return
                if tail:
                    yield sse("delta", {"text": tail})
                # Fixed text, not model output: /ia cannot book, hand off or
                # register requests, so roof, installation, booking, handoff,
                # opt-out and privacy answers end by pointing to «Citas y equipo».
                if closing:
                    yield sse("delta", {"text": closing})
                item = persist(final, "complete")
                yield sse("done", {
                    "assistant": item,
                    "conversation": app.state.ia.conversation_summary(owner, conversation["id"]),
                })
            except asyncio.CancelledError:
                if not saved:
                    preserve_partial(keep_empty=True)
                raise
            except Exception as error:
                if not saved:
                    item = preserve_partial()
                else:
                    item = None
                record_gap("ia", "model_error", incoming)
                import httpx
                detail = (
                    "El modelo local tardó demasiado en responder. Inténtalo de nuevo."
                    if isinstance(error, httpx.TimeoutException)
                    else "No pudimos completar la respuesta con el modelo local. Revisa que Ollama esté en ejecución."
                )
                yield sse("error", {"detail": detail, "assistant": item})

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/ia/bootstrap")
    async def ia_bootstrap(request: Request, response: Response):
        from .ai_chat import status as chat_ai_status
        from .documents import limits_for
        app.state.limiter.check(request, "ia_bootstrap", 60, 60)
        app.state.ia.purge_expired_visitors()
        app.state.ia.purge_attachments()
        owner, user = ia_owner(request, response)
        return {
            "owner": owner["kind"],
            "user": {"name": user["name"]} if user else None,
            "retention_days": VISITOR_DAYS,
            "attachments": limits_for(owner).public(),
            "conversations": app.state.ia.list(owner),
            "model": await chat_ai_status(),
        }

    @app.get("/api/ia/status")
    async def ia_status(request: Request):
        # Lets public buttons decide between /ia and the deterministic chat
        # without creating a visitor session or touching any conversation.
        from .ai_chat import status as chat_ai_status
        app.state.limiter.check(request, "ia_status", 60, 60)
        model = await chat_ai_status()
        return {"available": bool(model.get("enabled")) and model.get("status") == "available"}

    @app.get("/api/ia/conversations")
    def ia_conversations(request: Request, q: str = ""):
        app.state.limiter.check(request, "ia_read", 120, 60)
        owner, _ = ia_owner(request)
        return {"conversations": app.state.ia.list(owner, q)}

    @app.patch("/api/ia/conversations/{conversation_id}")
    async def ia_rename(conversation_id: str, request: Request):
        app.state.limiter.check(request, "ia_manage", 60, 60)
        data = await payload(request)
        owner, _ = ia_owner(request)
        return {"conversation": app.state.ia.rename(owner, conversation_id, data.get("title"))}

    @app.delete("/api/ia/conversations/{conversation_id}")
    def ia_delete(conversation_id: str, request: Request):
        app.state.limiter.check(request, "ia_manage", 60, 60)
        owner, _ = ia_owner(request)
        return app.state.ia.delete(owner, conversation_id)

    @app.post("/api/ia/conversations")
    def ia_create(request: Request):
        app.state.limiter.check(request, "ia_create", 30, 3600)
        owner, _ = ia_owner(request)
        return {"conversation": app.state.ia.create(owner)}

    @app.get("/api/ia/suggestions")
    def ia_suggestions(request: Request, conversation_id: str = "", seen: str = ""):
        """Six suggestions for /ia. Context comes only from a conversation the caller owns."""
        from . import suggestions
        app.state.limiter.check(request, "ia_read", 120, 60)
        owner, _ = ia_owner(request)
        conversation_id = text(conversation_id, "conversación", limit=100)
        messages = app.state.ia.detail(owner, conversation_id)["messages"] if conversation_id else []
        seen_ids = [item for item in text(seen, "vistas", limit=4000).split(",") if item][:300]
        # Rotates as the conversation and the list of shown suggestions grow.
        seed = f"{conversation_id}:{len(messages)}:{len(seen_ids)}"
        picked = suggestions.select(messages, seen_ids, seed=seed)
        return {"suggestions": [{"id": item.id, "text": item.text, "category": item.category} for item in picked]}

    @app.get("/api/ia/conversations/{conversation_id}")
    def ia_conversation(conversation_id: str, request: Request):
        app.state.limiter.check(request, "ia_read", 120, 60)
        owner, _ = ia_owner(request)
        return app.state.ia.detail(owner, conversation_id)

    @app.post("/api/ia/conversations/{conversation_id}/attachments", status_code=201)
    async def ia_attach(conversation_id: str, request: Request):
        """Attach one document (PDF, .txt, .md) to the next message.

        Team accounts and /ia visitors alike, each with their own limits. The
        body is the raw file, read here in bounded chunks after the owner,
        conversation and rate limits are known; only redacted text is stored.
        """
        from . import documents
        owner, user = ia_owner(request)
        limits = documents.limits_for(owner)
        if owner["kind"] == "user":
            app.state.limiter.check(request, "ia_attach_user", 10, 3600, client=owner["id"])
        else:
            app.state.limiter.check(request, "ia_attach_session", 5, 3600, client=owner["id"])
            app.state.limiter.check(request, "ia_attach_session_day", 20, 86400, client=owner["id"])
            app.state.limiter.check(request, "ia_attach_ip", 5, 3600)
            app.state.limiter.check(request, "ia_attach_ip_day", 20, 86400)
        name = documents.file_name(request.headers.get("x-attachment-name"))
        documents.kind_for(name)
        app.state.ia.conversation_summary(owner, conversation_id)
        too_big = DomainError(f"El archivo supera el máximo de {limits.max_bytes // (1024 * 1024)} MB.", 413)
        try:
            declared = int(request.headers.get("content-length", ""))
        except ValueError:
            raise DomainError("Falta el tamaño del archivo.", 411) from None
        if declared > limits.max_bytes:
            raise too_big
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > limits.max_bytes:
                raise too_big
            body.extend(chunk)
        async with app.state.document_slots:
            document = await asyncio.to_thread(documents.extract, bytes(body), name, limits)
        del body
        app.state.ia.purge_attachments()
        attachment = app.state.ia.add_attachment(owner, conversation_id, document)
        with app.state.store.connect() as db:
            app.state.store.audit(db, user, "ia.attachment.added", attachment["id"])
        return {"attachment": attachment}

    @app.delete("/api/ia/conversations/{conversation_id}/attachments/{attachment_id}")
    def ia_detach(conversation_id: str, attachment_id: str, request: Request):
        app.state.limiter.check(request, "ia_manage", 60, 60)
        owner, user = ia_owner(request)
        result = app.state.ia.remove_attachment(owner, conversation_id, attachment_id)
        with app.state.store.connect() as db:
            app.state.store.audit(db, user, "ia.attachment.removed", result["removed"])
        return result

    @app.post("/api/ia/conversations/{conversation_id}/messages")
    async def ia_message(conversation_id: str, request: Request):
        from . import ai_chat
        app.state.limiter.check(request, "ia_message", 30, 60)
        app.state.limiter.check(request, "ia_generate", 10, 60)
        data = await payload(request)
        incoming = text(data.get("text"), "mensaje", limit=4000, required=True)
        if not ai_chat.enabled():
            raise DomainError("La IA local no está habilitada en este servidor.", 503)
        owner, _ = ia_owner(request)
        app.state.ia.purge_attachments()
        conversation, user_message, assistant = app.state.ia.begin_turn(
            owner, conversation_id, incoming, data.get("attachment_id") or None,
        )
        # The model and the knowledge lookup receive the stored text, with
        # contact data already hidden, never the raw request body.
        incoming = user_message["content"]
        history = app.state.ia.history(conversation["id"], exclude_id=user_message["id"])
        document = app.state.ia.document_for(conversation["id"])
        streaming = ia_events(request, owner, conversation, incoming, history, assistant, document=document)
        return renew_visitor(request, streaming) if owner["kind"] == "visitor" else streaming

    @app.post("/api/ia/conversations/{conversation_id}/regenerate")
    async def ia_regenerate(conversation_id: str, request: Request):
        from . import ai_chat
        app.state.limiter.check(request, "ia_regenerate", 10, 60)
        data = await payload(request)
        if not ai_chat.enabled():
            raise DomainError("La IA local no está habilitada en este servidor.", 503)
        owner, _ = ia_owner(request)
        conversation, assistant, incoming, history = app.state.ia.prepare_regeneration(
            owner, conversation_id, data.get("message_id")
        )
        document = app.state.ia.document_for(conversation["id"])
        streaming = ia_events(request, owner, conversation, incoming, history, assistant, regenerate=True,
                              document=document)
        return renew_visitor(request, streaming) if owner["kind"] == "visitor" else streaming

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
        from .ai_chat import status as chat_ai_status
        return {"engine": "motor_comercial_local", "chat": "active", "paid_apis": "blocked", "local_model": await model_status(), "chat_ai": await chat_ai_status(), "knowledge": app.state.knowledge.status(), "booking": {"timezone": app.state.store.settings()["timezone"], "public_advisors": sum(u["active"] and u["public_booking"] for u in app.state.store.list_users())}, "notice": "Chat y agenda propios. La actualización requiere Internet y el servidor encendido. Las ventas se concretan con una propuesta aceptada por el cliente."}

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
            if getattr(app.state, "synthetic_preview", False):
                raise DomainError("Los envíos externos están deshabilitados en la demostración sintética.", 503)
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

    # --- Aprendizaje: cola con aprobación humana (asesor propone, administrador decide) ---
    def learning_limit(request, user, key, maximum, seconds):
        app.state.limiter.check(request, f"learning_{key}", maximum, seconds)
        app.state.limiter.check(request, f"learning_{key}:{user['id']}", maximum, seconds)

    @app.get("/api/learning/gaps")
    def learning_gaps(request: Request, status: str = "", route: str = "", reason: str = "", topic: str = "",
                      limit: int = 100, offset: int = 0, user=Depends(actor)):
        learning_limit(request, user, "read", 240, 60)
        app.state.learning.maybe_purge()
        result = app.state.learning.list(user, status=status, route=route, reason=reason, topic=topic, limit=limit, offset=offset)
        return {**result, "can_review": user["role"] == "admin"}

    @app.get("/api/learning/gaps/{gap_id}/proposals")
    def learning_proposals(gap_id: str, request: Request, user=Depends(actor)):
        learning_limit(request, user, "read", 240, 60)
        return {"proposals": app.state.learning.proposals(user, text(gap_id, "hueco", limit=100))}

    @app.post("/api/learning/gaps", status_code=201)
    async def learning_flag(request: Request, user=Depends(actor)):
        learning_limit(request, user, "flag", 60, 3600)
        data = await payload(request)
        route = text(data.get("route"), "ruta", limit=10, required=True)
        question = text(data.get("question"), "pregunta", limit=2000, required=True)
        gap = app.state.learning.record_gap(route, "staff_flag", question, actor=user)
        if not gap:
            raise DomainError("La pregunta quedó vacía al ocultar los datos personales.", 422)
        return {"gap": gap}

    @app.post("/api/learning/gaps/{gap_id}/proposals", status_code=201)
    async def learning_propose(gap_id: str, request: Request, user=Depends(actor)):
        learning_limit(request, user, "propose", 60, 3600)
        return {"proposal": app.state.learning.propose(text(gap_id, "hueco", limit=100), await payload(request), user)}

    @app.post("/api/learning/proposals/{proposal_id}/{decision}")
    async def learning_decide(proposal_id: str, decision: str, request: Request, user=Depends(actor)):
        app.state.store.require_admin(user)
        learning_limit(request, user, "review", 120, 3600)
        data = await payload(request)
        proposal_id = text(proposal_id, "propuesta", limit=100)
        if decision == "approve":
            return {"proposal": app.state.learning.approve(proposal_id, user, data.get("note", ""))}
        if decision == "reject":
            return {"proposal": app.state.learning.reject(proposal_id, user, data.get("note", ""))}
        raise DomainError("Decisión no válida.", 404)

    @app.post("/api/learning/gaps/{gap_id}/{decision}")
    async def learning_gap_decision(gap_id: str, decision: str, request: Request, user=Depends(actor)):
        app.state.store.require_admin(user)
        learning_limit(request, user, "review", 120, 3600)
        data = await payload(request)
        gap_id = text(gap_id, "hueco", limit=100)
        if decision == "reject":
            app.state.learning.reject_gap(gap_id, user, data.get("note", ""))
        elif decision == "resolve":
            app.state.learning.resolve(gap_id, user)
        else:
            raise DomainError("Decisión no válida.", 404)
        return {"ok": True}

    def eval_state():
        job = app.state.learning_eval
        task = job["task"]
        return {"running": bool(task and not task.done()), "error": job["error"], "started_at": job["started_at"]}

    @app.get("/api/learning/eval")
    def learning_eval_latest(request: Request, user=Depends(actor)):
        learning_limit(request, user, "read", 240, 60)
        if user["role"] not in {"admin", "advisor"}:
            raise DomainError("Esta acción requiere una cuenta del equipo.", 403)
        return {"latest": app.state.learning.latest_run(), **eval_state(), "can_run": user["role"] == "admin"}

    @app.post("/api/learning/eval", status_code=202)
    async def learning_eval_run(request: Request, user=Depends(actor)):
        from . import ai_chat, learning_eval
        from .core import stamp
        app.state.store.require_admin(user)
        await payload(request)
        if eval_state()["running"]:
            raise DomainError("Ya hay una evaluación en curso. Espera a que termine.", 409)
        app.state.limiter.check(request, "learning_eval", 4, 3600)
        model = await ai_chat.status()
        if not model.get("enabled"):
            raise DomainError("La IA local no está habilitada en este servidor.", 503)
        if model.get("status") != "available":
            raise DomainError("El modelo local configurado no está disponible en Ollama. No se descarga ningún modelo.", 503)
        job = app.state.learning_eval
        job.update(error="", started_at=stamp())

        async def work():
            try:
                await learning_eval.run_bank(app.state.learning, app.state.knowledge, actor=user)
            except Exception:
                logging.getLogger(__name__).exception("No se pudo completar el banco de preguntas")
                job["error"] = "La evaluación no terminó. Revisa que Ollama siga en ejecución."

        job["task"] = asyncio.create_task(work())
        return {**eval_state(), "model": model.get("model")}

    from .channels import register_routes
    register_routes(app)
    from .energy import register_routes as register_energy_routes
    register_energy_routes(app, actor, payload)
    from .privacy import register_routes as register_privacy_routes
    register_privacy_routes(app, actor, payload)
    from .advisor_tools import register_routes as register_advisor_tools
    register_advisor_tools(app, actor, payload)
    from . import seo
    seo.register_routes(app)

    @app.get("/app", include_in_schema=False)
    async def workspace():
        return FileResponse(ROOT / "frontend" / "index.html")

    @app.get("/ia", include_in_schema=False)
    async def ai_workspace_page():
        return FileResponse(ROOT / "frontend" / "ia.html", headers={"X-Robots-Tag": "noindex, nofollow"})

    @app.get("/", include_in_schema=False)
    async def public_chat_page():
        # The root is the public conversation visitors reach first.
        return FileResponse(ROOT / "frontend" / "ia.html", headers={"X-Robots-Tag": "noindex, nofollow"})

    @app.get("/chat", include_in_schema=False)
    async def legacy_chat_page():
        return FileResponse(ROOT / "frontend" / "chat.html", headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
    return app
