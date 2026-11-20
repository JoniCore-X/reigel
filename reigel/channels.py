"""Official messaging adapters, authenticated inbound webhooks and guarded AI.

Credentials are read from the environment. Configured is never synonymous with
connected or delivered. Only text/private conversations are supported.
References: https://core.telegram.org/bots/api
https://www.postman.com/meta/whatsapp-business-platform/request/8gvd47s/send-text-message
https://www.postman.com/meta/messenger-platform-api/documentation/iyp204x/messenger-platform-api
https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api
"""
from __future__ import annotations

import hashlib
import hmac
import asyncio
import json
import os
import re
import sqlite3
import time
import unicodedata
import uuid
import weakref
from datetime import datetime, timezone

import httpx
from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

from . import assistant

MAX_BODY = 256 * 1024
MAX_TEXT = 4000
_reply_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
META_CHANNELS = {"whatsapp", "messenger", "instagram"}
CONFIG = {
    "whatsapp": ("WhatsApp", ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "META_APP_SECRET", "META_VERIFY_TOKEN", "META_GRAPH_VERSION"], "/webhooks/meta"),
    "telegram": ("Telegram", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET"], "/webhooks/telegram"),
    "instagram": ("Instagram", ["INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_ACCOUNT_ID", "META_APP_SECRET", "META_VERIFY_TOKEN", "META_GRAPH_VERSION"], "/webhooks/meta"),
    "messenger": ("Messenger", ["MESSENGER_PAGE_ACCESS_TOKEN", "MESSENGER_PAGE_ID", "META_APP_SECRET", "META_VERIFY_TOKEN", "META_GRAPH_VERSION"], "/webhooks/meta"),
    "ai": ("IA local · Ollama", ["REIGEL_LOCAL_MODEL"], None),
}


def integration_status() -> list[dict]:
    result = []
    for channel, (name, keys, webhook) in CONFIG.items():
        if channel in META_CHANNELS:
            result.append({"id": channel, "name": name, "status": "blocked_cost_policy", "configured": False, "missing": [], "webhook": webhook, "detail": "Envíos bloqueados: no se garantiza gratuidad total de este servicio externo."})
            continue
        if channel == "ai":
            result.append({"id": "ai", "name": name, "status": "local_check_required", "configured": assistant.configured(), "missing": [], "webhook": None, "detail": "Solo Ollama en esta computadora. Disponibilidad real en Automatización. Los borradores requieren revisión; en modo IA de un canal permitido la respuesta se envía sin revisión previa."})
            continue
        missing = [key for key in keys if not os.getenv(key, "").strip()]
        result.append({"id": channel, "name": name, "status": "not_configured" if missing else "configured_unverified",
                       "configured": not missing, "missing": missing, "webhook": webhook,
                       "detail": "Necesita configuración del servidor." if missing else "Configurado; falta verificar una conversación real."})
    result.insert(0, {"id": "web", "name": "Chat web · R.E.I.G.E.L.", "status": "local", "configured": True, "missing": [], "webhook": None, "detail": "Motor comercial y agenda propios. Sin API externa ni cargos por mensaje."})
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _schema(store):
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS channel_preferences (conversation_id TEXT PRIMARY KEY REFERENCES conversations(id), opted_out INTEGER NOT NULL DEFAULT 0)")


def reply_permission(store, conversation) -> dict:
    """Validate opt-out and Meta's standard 24h window for human/AI replies."""
    _schema(store)
    conversation = dict(conversation)
    with store.connect() as db:
        if conversation["channel"] == "web":
            present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='web_chat_sessions'").fetchone()
            preference = db.execute("SELECT opted_out FROM web_chat_sessions WHERE conversation_id=?", (conversation["id"],)).fetchone() if present else None
            if preference and preference["opted_out"]:
                return {"allowed": False, "reason": "El cliente detuvo la atención. Solo él puede reanudarla escribiendo /start."}
        preference = db.execute("SELECT opted_out FROM channel_preferences WHERE conversation_id=?", (conversation["id"],)).fetchone()
        if preference and preference["opted_out"]:
            return {"allowed": False, "reason": "El contacto pidió no recibir mensajes. Debe iniciar de nuevo con /start."}
        if conversation["channel"] in META_CHANNELS:
            last = db.execute("SELECT created_at FROM messages WHERE conversation_id=? AND direction='inbound' ORDER BY created_at DESC LIMIT 1", (conversation["id"],)).fetchone()
            if not last:
                return {"allowed": False, "reason": "El contacto debe iniciar la conversación."}
            try:
                started = datetime.fromisoformat(last["created_at"].replace("Z", "+00:00"))
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            except (ValueError, TypeError):
                return {"allowed": False, "reason": "No se pudo verificar la ventana de respuesta."}
            if elapsed < -300 or elapsed >= 86400:
                return {"allowed": False, "reason": "La ventana de respuesta de 24 horas terminó. Espera un nuevo mensaje del contacto."}
    return {"allowed": True, "reason": ""}


async def send_message(channel: str, external_id: str, text: str) -> dict:
    """Single attempt only. A timeout/5xx can mean delivered: never auto-retry."""
    if channel in META_CHANNELS:
        return {"status": "failed", "error": "Envío bloqueado: el servicio no garantiza gratuidad total."}
    if channel not in CONFIG or channel == "ai":
        return {"status": "failed", "error": "Canal no compatible."}
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        return {"status": "failed", "error": "El mensaje debe tener entre 1 y 4000 caracteres."}
    if not isinstance(external_id, str) or not re.fullmatch(r"[0-9]{1,40}", external_id):
        return {"status": "failed", "error": "El destinatario no tiene un identificador válido para este canal."}
    missing = [key for key in CONFIG[channel][1] if not os.getenv(key, "").strip()]
    if missing:
        return {"status": "failed", "error": "El canal no está configurado en el servidor."}
    headers = {}
    if channel == "telegram":
        token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            return {"status": "failed", "error": "El token de Telegram no es válido."}
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": external_id, "text": text.strip()}
    else:
        version = os.environ["META_GRAPH_VERSION"].strip()
        if not re.fullmatch(r"v[0-9]{1,2}\.0", version):
            return {"status": "failed", "error": "META_GRAPH_VERSION debe tener formato vNN.0."}
        if channel == "whatsapp":
            owner = os.environ["WHATSAPP_PHONE_NUMBER_ID"].strip()
            token = os.environ["WHATSAPP_ACCESS_TOKEN"].strip()
            payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": external_id,
                       "type": "text", "text": {"body": text.strip(), "preview_url": False}}
        elif channel == "messenger":
            owner = os.environ["MESSENGER_PAGE_ID"].strip()
            token = os.environ["MESSENGER_PAGE_ACCESS_TOKEN"].strip()
            payload = {"recipient": {"id": external_id}, "messaging_type": "RESPONSE", "message": {"text": text.strip()}}
        else:
            owner = os.environ["INSTAGRAM_ACCOUNT_ID"].strip()
            token = os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()
            payload = {"recipient": {"id": external_id}, "message": {"text": text.strip()}}
        if not owner.isdecimal():
            return {"status": "failed", "error": "El identificador de la cuenta del canal no es válido."}
        host = "graph.instagram.com" if channel == "instagram" else "graph.facebook.com"
        url = f"https://{host}/{version}/{owner}/messages"
        headers["Authorization"] = "Bearer " + token
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=4), follow_redirects=False) as client:
            response = await client.post(url, json=payload, headers=headers)
    except (httpx.TimeoutException, httpx.NetworkError):
        return {"status": "uncertain", "error": "No se pudo confirmar la aceptación. Revisa el canal antes de reenviar para evitar duplicados."}
    except httpx.HTTPError:
        return {"status": "failed", "error": "No se pudo conectar con el canal."}
    if response.status_code >= 500:
        return {"status": "uncertain", "error": "El proveedor tuvo un error; no se reintentó el envío."}
    if response.status_code >= 300:
        return {"status": "failed", "error": "El proveedor rechazó el mensaje. Revisa permisos, destinatario y límites del canal."}
    try:
        data = response.json()
    except ValueError:
        return {"status": "uncertain", "error": "El proveedor devolvió una respuesta que no se pudo validar."}
    if not isinstance(data, dict):
        return {"status": "uncertain", "error": "El proveedor devolvió una respuesta que no se pudo validar."}
    if channel == "telegram":
        if data.get("ok") is not True:
            return {"status": "failed", "error": "Telegram no aceptó el mensaje."}
        telegram_result = data.get("result") if isinstance(data.get("result"), dict) else {}
        provider_id = str(telegram_result.get("message_id", ""))
    elif channel == "whatsapp":
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        first_message = messages[0] if messages and isinstance(messages[0], dict) else {}
        provider_id = str(first_message.get("id", ""))
    else:
        provider_id = str(data.get("message_id", ""))
    if not provider_id:
        return {"status": "uncertain", "error": "El proveedor no devolvió un identificador de aceptación."}
    return {"status": "sent", "provider_id": provider_id}


def _normalize_text(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.strip().lower()) if unicodedata.category(c) != "Mn")


def _opt_out(text: str) -> bool:
    clean = re.sub(r"[.!¡¿?]", "", _normalize_text(text)).strip()
    return clean in {"stop", "/stop", "baja", "cancelar mensajes", "no me escriban", "no me escribas", "no mas mensajes", "no quiero mas mensajes", "unsubscribe", "parar", "salir"} or bool(
        re.search(r"\b(darme de baja|darme la baja|dejen? de (?:escribir|contactar)|no me (?:contact|escrib)|no (?:quiero|deseo) (?:recibir )?(?:mas )?mensajes|elimin[ae] (?:mis )?datos)\b", clean))


def _human_requested(text: str) -> bool:
    return bool(re.search(r"\b(?:hablar|comunicarme|comunicar|contactar)\b.{0,30}\b(?:humano|persona|asesor|agente)\b", _normalize_text(text)))


def _event_timestamp(value, *, milliseconds=False) -> str | None:
    try:
        timestamp = float(value) / (1000 if milliseconds else 1)
        # Late Meta webhooks cannot reopen the 24-hour reply window.
        if timestamp > time.time() + 300 or timestamp < 0:
            return None
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _meta_events(payload: dict) -> list[dict]:
    events = []
    object_type = payload.get("object")
    for entry in payload.get("entry", [])[:100]:
        if not isinstance(entry, dict):
            continue
        if object_type == "whatsapp_business_account":
            for change in entry.get("changes", [])[:100]:
                value = change.get("value", {}) if isinstance(change, dict) else {}
                if str(value.get("metadata", {}).get("phone_number_id", "")) != os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip():
                    continue
                contacts = {str(c.get("wa_id", "")): str(c.get("profile", {}).get("name", "Contacto"))[:120]
                            for c in value.get("contacts", []) if isinstance(c, dict)}
                for message in value.get("messages", [])[:100]:
                    if not isinstance(message, dict) or message.get("type") != "text":
                        continue
                    sender = str(message.get("from", ""))
                    events.append({"channel": "whatsapp", "external_id": sender, "external_message_id": str(message.get("id", "")),
                                   "text": message.get("text", {}).get("body", ""), "contact_name": contacts.get(sender, "Contacto de WhatsApp"),
                                   "created_at": _event_timestamp(message.get("timestamp"))})
        elif object_type in {"page", "instagram"}:
            channel = "instagram" if object_type == "instagram" else "messenger"
            expected = os.getenv("INSTAGRAM_ACCOUNT_ID" if channel == "instagram" else "MESSENGER_PAGE_ID", "").strip()
            if str(entry.get("id", "")) != expected:
                continue
            for event in entry.get("messaging", [])[:100]:
                if not isinstance(event, dict):
                    continue
                message = event.get("message", {})
                if not isinstance(message, dict) or message.get("is_echo") or not message.get("text"):
                    continue
                if str(event.get("recipient", {}).get("id", "")) != expected:
                    continue
                events.append({"channel": channel, "external_id": str(event.get("sender", {}).get("id", "")),
                               "external_message_id": str(message.get("mid", "")), "text": message.get("text", ""),
                               "contact_name": "Contacto de " + CONFIG[channel][0], "created_at": _event_timestamp(event.get("timestamp"), milliseconds=True)})
    return events


def _store_event(store, event: dict) -> tuple[str, str] | None:
    channel, sender, text = event["channel"], event["external_id"], event["text"]
    if not re.fullmatch(r"[0-9]{1,40}", sender) or not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        return None
    message_id = event.get("external_message_id", "")
    if not isinstance(message_id, str) or not message_id or len(message_id) > 512 or not event.get("created_at"):
        return None
    _schema(store)
    # Event IDs do not retain phone numbers or provider payloads.
    event_id = hashlib.sha256(f"{channel}:{message_id}".encode()).hexdigest()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT id FROM webhook_events WHERE id=?", (event_id,)).fetchone():
            return None
        db.execute("INSERT INTO webhook_events(id,channel,status,created_at) VALUES(?,?,?,?)", (event_id, channel, "stored", _now()))
        conversation = db.execute("SELECT * FROM conversations WHERE channel=? AND external_id=?", (channel, sender)).fetchone()
        if conversation:
            conversation_id = conversation["id"]
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), conversation_id))
        else:
            conversation_id = uuid.uuid4().hex
            available = db.execute("SELECT u.id FROM users u LEFT JOIN conversations c ON c.advisor_id=u.id "
                                   "WHERE u.active=1 AND u.public_booking=1 GROUP BY u.id "
                                   "ORDER BY COUNT(c.id),u.created_at,u.id LIMIT 1").fetchone()
            advisor_id = available["id"] if available else None
            db.execute("INSERT INTO conversations(id,channel,external_id,contact_name,lead_id,advisor_id,mode,updated_at) VALUES(?,?,?,?,NULL,?,'human',?)",
                       (conversation_id, channel, sender, event.get("contact_name", "Contacto")[:120], advisor_id, _now()))
        db.execute("INSERT INTO messages(id,conversation_id,direction,text,status,external_id,created_at) VALUES(?,?,'inbound',?,'received',?,?)",
                   (uuid.uuid4().hex, conversation_id, text.strip(), message_id, event["created_at"]))
        if _opt_out(text):
            db.execute("INSERT INTO channel_preferences(conversation_id,opted_out) VALUES(?,1) ON CONFLICT(conversation_id) DO UPDATE SET opted_out=1", (conversation_id,))
            db.execute("UPDATE conversations SET mode='human' WHERE id=?", (conversation_id,))
        elif _human_requested(text):
            db.execute("UPDATE conversations SET mode='human' WHERE id=?", (conversation_id,))
        elif _normalize_text(text) == "/start":
            db.execute("INSERT INTO channel_preferences(conversation_id,opted_out) VALUES(?,0) ON CONFLICT(conversation_id) DO UPDATE SET opted_out=0", (conversation_id,))
    return conversation_id, event_id


async def _respond(store, conversation_id: str, event_id: str, incoming_text: str):
    """An acknowledged inbound message stays visible even if AI/provider fail."""
    lock = _reply_locks.setdefault(conversation_id, asyncio.Lock())
    async with lock:
        await _respond_locked(store, conversation_id, event_id, incoming_text)


async def _respond_locked(store, conversation_id: str, event_id: str, incoming_text: str):
    with store.connect() as db:
        conversation = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        history = [dict(row) for row in db.execute("SELECT direction,text FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 10", (conversation_id,)).fetchall()][::-1]
    if not conversation or conversation["mode"] != "ai" or not reply_permission(store, conversation)["allowed"]:
        return
    status = "human_required"
    try:
        reply = await assistant.draft(incoming_text, store.settings(), history=history[:-1])
        # Re-check handover/opt-out immediately before dispatch.
        with store.connect() as db:
            current = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not current or current["mode"] != "ai" or not reply_permission(store, current)["allowed"]:
            return
        result = await send_message(current["channel"], current["external_id"], reply)
        status = "replied" if result["status"] == "sent" else "human_required"
        with store.connect() as db:
            db.execute("INSERT INTO messages(id,conversation_id,direction,text,status,external_id,created_at) VALUES(?,?,'outbound',?,?,?,?)",
                       (uuid.uuid4().hex, conversation_id, reply, result["status"], result.get("provider_id"), _now()))
            if status != "replied":
                db.execute("UPDATE conversations SET mode='human' WHERE id=?", (conversation_id,))
    except (ValueError, RuntimeError, httpx.HTTPError):
        with store.connect() as db:
            db.execute("UPDATE conversations SET mode='human' WHERE id=?", (conversation_id,))
    finally:
        with store.connect() as db:
            db.execute("UPDATE webhook_events SET status=? WHERE id=?", (status, event_id))


async def _read_payload(request: Request) -> tuple[bytes, dict]:
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BODY:
            raise HTTPException(413, "La notificación excede el tamaño permitido.")
    try:
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "La notificación no tiene un formato válido.") from None
    return bytes(data), payload


def register_routes(app):
    @app.get("/webhooks/meta", response_class=PlainTextResponse)
    async def verify_meta(request: Request):
        token = os.getenv("META_VERIFY_TOKEN", "").strip()
        if not token:
            raise HTTPException(503, "El webhook de Meta no está configurado.")
        provided = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")
        if request.query_params.get("hub.mode") != "subscribe" or not hmac.compare_digest(provided, token) or not re.fullmatch(r"[0-9]{1,100}", challenge):
            raise HTTPException(403, "La verificación de Meta fue rechazada.")
        return challenge

    @app.post("/webhooks/meta")
    async def meta_webhook(request: Request, background_tasks: BackgroundTasks):
        secret = os.getenv("META_APP_SECRET", "").strip()
        if not secret:
            raise HTTPException(503, "El webhook de Meta no está configurado.")
        raw, payload = await _read_payload(request)
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        signature = request.headers.get("x-hub-signature-256", "")
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(403, "La firma de la notificación no es válida.")
        stored = 0
        try:
            events = _meta_events(payload)
        except (TypeError, AttributeError):
            raise HTTPException(400, "La notificación no tiene un formato válido.") from None
        for event in events:
            result = _store_event(request.app.state.store, event)
            if result:
                stored += 1
                background_tasks.add_task(_respond, request.app.state.store, *result, event["text"])
        return {"ok": True, "stored": stored}

    @app.post("/webhooks/telegram")
    async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
        secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
        if not secret or not os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
            raise HTTPException(503, "El webhook de Telegram no está configurado.")
        provided = request.headers.get("x-telegram-bot-api-secret-token", "")
        if not hmac.compare_digest(provided, secret):
            raise HTTPException(403, "La notificación de Telegram no es auténtica.")
        _, payload = await _read_payload(request)
        message = payload.get("message", {})
        if not isinstance(message, dict) or not isinstance(message.get("chat", {}), dict):
            raise HTTPException(400, "La notificación no tiene un formato válido.")
        if not isinstance(message.get("from", {}), dict):
            raise HTTPException(400, "La notificación no tiene un formato válido.")
        if message.get("chat", {}).get("type") != "private" or message.get("from", {}).get("is_bot"):
            return {"ok": True, "stored": 0}
        sender = message.get("from", {})
        event = {"channel": "telegram", "external_id": str(message.get("chat", {}).get("id", "")),
                 "external_message_id": str(payload.get("update_id", "")), "text": message.get("text", ""),
                 "contact_name": str(sender.get("first_name", "Contacto de Telegram"))[:120], "created_at": _event_timestamp(message.get("date"))}
        result = _store_event(request.app.state.store, event)
        if result:
            background_tasks.add_task(_respond, request.app.state.store, *result, event["text"])
        return {"ok": True, "stored": 1 if result else 0}
