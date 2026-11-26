"""Provider transports are mocked explicitly; no test sends an external message."""
import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reigel import assistant, channels
from reigel.core import Store
from team_auth import allow, login as team_login

REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def clear_credentials(monkeypatch):
    for _, keys, _ in channels.CONFIG.values():
        for key in keys:
            monkeypatch.delenv(key, raising=False)
    channels._reply_locks.clear()


@pytest.fixture
def server(tmp_path):
    app = FastAPI()
    app.state.store = Store(tmp_path / "channels-test.db")
    channels.register_routes(app)
    return app, TestClient(app)


def configure(monkeypatch, channel):
    for key in channels.CONFIG[channel][1]:
        value = {"META_GRAPH_VERSION": "v26.0", "TELEGRAM_BOT_TOKEN": "123456:TestToken",
                 "WHATSAPP_PHONE_NUMBER_ID": "888", "MESSENGER_PAGE_ID": "777", "INSTAGRAM_ACCOUNT_ID": "666",
                 "OPENAI_MODEL": "test-model"}.get(key, "test-secret")
        monkeypatch.setenv(key, value)


def transport(monkeypatch, handler):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs))


def run(coroutine):
    return asyncio.run(coroutine)


def telegram(update=1, text="Hola", timestamp=None):
    return {"update_id": update, "message": {"date": timestamp or int(time.time()), "text": text,
            "chat": {"id": 1234, "type": "private"}, "from": {"id": 1234, "first_name": "Prueba", "is_bot": False}}}


def post_telegram(client, payload):
    return client.post("/webhooks/telegram", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"})


def whatsapp(message_id="wamid.test", text="Hola", phone_id="888", timestamp=None):
    return {"object": "whatsapp_business_account", "entry": [{"id": "account", "changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": phone_id}, "contacts": [{"wa_id": "1234", "profile": {"name": "Prueba"}}],
        "messages": [{"id": message_id, "from": "1234", "type": "text", "text": {"body": text}, "timestamp": str(timestamp or int(time.time()))}]}}]}]}


def post_meta(client, payload):
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
    return client.post("/webhooks/meta", content=raw, headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"})


def first_conversation(app):
    with app.state.store.connect() as db:
        return dict(db.execute("SELECT * FROM conversations LIMIT 1").fetchone())


def test_config_status_does_not_claim_live_or_reveal_secrets(monkeypatch):
    assert all(x["status"] in {"not_configured", "blocked_cost_policy", "local", "local_check_required"} for x in channels.integration_status())
    configure(monkeypatch, "telegram")
    row = next(x for x in channels.integration_status() if x["id"] == "telegram")
    assert row["status"] == "configured_unverified" and row["configured"]
    assert "test-secret" not in json.dumps(channels.integration_status())


def test_unconfigured_send_fails_closed():
    assert run(channels.send_message("whatsapp", "1234", "Hola"))["status"] == "failed"


@pytest.mark.parametrize("destination", ["https://evil.test", "../messages", "", "123;hello", "-234"])
def test_destinations_are_provider_identifiers(monkeypatch, destination):
    configure(monkeypatch, "telegram")
    assert run(channels.send_message("telegram", destination, "Hola"))["status"] == "failed"


@pytest.mark.parametrize("channel", ["telegram"])
def test_official_outbound_payloads_and_provider_acceptance(monkeypatch, channel):
    configure(monkeypatch, channel)
    seen = []
    def handler(request):
        seen.append(request)
        payload = json.loads(request.content)
        if channel == "telegram":
            assert request.url.host == "api.telegram.org" and request.url.path.endswith("/sendMessage")
            assert payload == {"chat_id": "1234", "text": "Hola"}
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})
        if channel == "whatsapp":
            assert request.url.path == "/v26.0/888/messages"
            assert payload["messaging_product"] == "whatsapp" and payload["to"] == "1234" and payload["text"]["body"] == "Hola"
            return httpx.Response(200, json={"messages": [{"id": "wamid.sent"}]})
        assert payload["recipient"] == {"id": "1234"} and payload["message"]["text"] == "Hola"
        assert request.url.host == ("graph.instagram.com" if channel == "instagram" else "graph.facebook.com")
        if channel == "messenger":
            assert payload["messaging_type"] == "RESPONSE"
        return httpx.Response(200, json={"message_id": "provider.sent"})
    transport(monkeypatch, handler)
    result = run(channels.send_message(channel, "1234", "Hola"))
    assert result["status"] == "sent" and result["provider_id"] and len(seen) == 1


def test_ambiguous_timeout_is_not_retried_or_reported_sent(monkeypatch):
    configure(monkeypatch, "telegram")
    attempts = []
    def handler(request):
        attempts.append(request)
        raise httpx.ReadTimeout("test timeout", request=request)
    transport(monkeypatch, handler)
    result = run(channels.send_message("telegram", "1234", "Hola"))
    assert result["status"] == "uncertain" and len(attempts) == 1


@pytest.mark.parametrize("code,payload,status", [(500, {}, "uncertain"), (403, {}, "failed"), (200, {}, "uncertain"), (200, {"ok": False}, "failed")])
def test_provider_errors_are_honest(monkeypatch, code, payload, status):
    configure(monkeypatch, "telegram")
    # Missing Telegram ok means rejected, whereas a successful response with missing ID is uncertain.
    if code == 200 and payload == {}:
        payload = {"ok": True, "result": {}}
    transport(monkeypatch, lambda request: httpx.Response(code, json=payload))
    assert run(channels.send_message("telegram", "1234", "Hola"))["status"] == status


def test_draft_is_local_only_with_no_tools(monkeypatch):
    monkeypatch.setenv("REIGEL_LOCAL_MODEL", "test-model")
    seen = []
    def handler(request):
        seen.append(request)
        assert request.url.host == "127.0.0.1" and request.url.port == 11434
        body = json.loads(request.content)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {}})
        assert request.url.path == "/api/chat"
        assert body["model"] == "test-model" and body["stream"] is False
        assert "tools" not in body and "Authorization" not in request.headers
        assert body["messages"][-1]["content"] == "Explica el proceso"
        return httpx.Response(200, json={"done": True, "message": {"content": "Podemos evaluar tu consumo y coordinar una orientación."}})
    transport(monkeypatch, handler)
    assert "evaluar" in run(assistant.draft("Explica el proceso", {"name": "Power Solar"}))
    assert len(seen) == 2


def test_draft_uses_bounded_configuration_and_sanitized_recent_history(monkeypatch):
    monkeypatch.setenv("REIGEL_LOCAL_MODEL", "test-model")
    monkeypatch.setenv("REIGEL_LOCAL_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("REIGEL_LOCAL_NUM_CTX", "3072")
    monkeypatch.setenv("REIGEL_LOCAL_NUM_PREDICT", "300")
    monkeypatch.setenv("REIGEL_LOCAL_TEMPERATURE", "0.1")
    captured = {}

    def handler(request):
        body = json.loads(request.content)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {}})
        captured.update(body)
        return httpx.Response(200, json={
            "done": True,
            "message": {"content": "Podemos coordinar una evaluación."},
        })

    transport(monkeypatch, handler)
    history = [
        {"direction": "inbound", "text": f"mensaje antiguo {index}"}
        for index in range(4)
    ]
    history.extend([
        {
            "direction": "inbound",
            "text": "Mi correo es cliente@example.test y mi teléfono es +1 (787) 555-1234",
        },
        {"direction": "outbound", "text": "Último turno revisado"},
    ])

    run(assistant.draft("Explica el proceso", {}, history=history))

    assert captured["options"] == {
        "temperature": 0.1,
        "num_predict": 300,
        "num_ctx": 3072,
    }
    history_messages = captured["messages"][1:-1]
    assert len(history_messages) == 6
    serialized = json.dumps(history_messages, ensure_ascii=False)
    assert "cliente@example.test" not in serialized
    assert "555-1234" not in serialized
    assert all(len(item["content"]) <= 850 for item in history_messages)
    assert all("contenido no confiable" in item["content"] for item in history_messages)


def test_local_model_outage_fails_clearly_without_remote_fallback(monkeypatch):
    monkeypatch.setenv("REIGEL_LOCAL_MODEL", "test-model")
    destinations = []

    def unavailable(request):
        destinations.append(request.url.host)
        raise httpx.ConnectError("local model offline", request=request)

    transport(monkeypatch, unavailable)

    with pytest.raises(RuntimeError, match="Ollama local"):
        run(assistant.draft("Explica el proceso", {}))

    assert destinations == ["127.0.0.1"]


def test_local_model_configuration_rejects_out_of_range_values(monkeypatch):
    monkeypatch.setenv("REIGEL_LOCAL_NUM_CTX", "100000")

    with pytest.raises(ValueError, match="REIGEL_LOCAL_NUM_CTX"):
        assistant._generation_settings()


def test_cloud_model_alias_is_blocked_before_generation(monkeypatch):
    monkeypatch.setenv("REIGEL_LOCAL_MODEL", "test-model")
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"remote_host": "https://ollama.com", "remote_model": "paid"})
    transport(monkeypatch, handler)
    with pytest.raises(ValueError):
        run(assistant.draft("Hola", {}))
    assert len(seen) == 1


def test_draft_rejects_invented_booking_completion(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={} if request.url.path == "/api/show" else {"done": True, "message": {"content": "Tu cita está confirmada para mañana."}})
    transport(monkeypatch, handler)
    with pytest.raises(RuntimeError):
        run(assistant.draft("Confirma una cita que no existe", {}))


@pytest.mark.parametrize("draft", [
    "Hola [Nombre del Cliente], entendemos tu pregunta.",
    "Hola [NOMBRE], podemos revisar las condiciones.",
    "Para confirmar, consulta la fecha: pendiente.",
])
def test_draft_rejects_unfilled_customer_placeholders(draft):
    with pytest.raises(RuntimeError, match="marcadores sin completar"):
        assistant.validate_draft(draft)


@pytest.mark.parametrize("channel", ["whatsapp", "instagram", "messenger"])
def test_non_free_channel_blocked_even_with_credentials(monkeypatch, channel):
    configure(monkeypatch, channel)
    def unexpected(request):
        raise AssertionError("Paid/uncertain pricing channels must not make network requests")
    transport(monkeypatch, unexpected)
    assert run(channels.send_message(channel, "1234", "Hola"))["status"] == "failed"
    row = next(x for x in channels.integration_status() if x["id"] == channel)
    assert row["status"] == "blocked_cost_policy" and not row["configured"]


def test_webhooks_reject_missing_configuration(server):
    _, client = server
    assert client.post("/webhooks/meta", json={}).status_code == 503
    assert client.post("/webhooks/telegram", json={}).status_code == 503


def test_meta_verification_and_signature_are_required(server, monkeypatch):
    configure(monkeypatch, "whatsapp")
    _, client = server
    assert client.get("/webhooks/meta?hub.mode=subscribe&hub.verify_token=test-secret&hub.challenge=12345").text == "12345"
    assert client.get("/webhooks/meta?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=12345").status_code == 403
    assert client.post("/webhooks/meta", json=whatsapp(), headers={"X-Hub-Signature-256": "sha256=wrong"}).status_code == 403


def test_meta_stores_once_and_filters_unowned_account(server, monkeypatch):
    configure(monkeypatch, "whatsapp")
    app, client = server
    assert post_meta(client, whatsapp(phone_id="wrong" )).json()["stored"] == 0
    assert post_meta(client, whatsapp()).json()["stored"] == 1
    assert post_meta(client, whatsapp()).json()["stored"] == 0
    with app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
        assert db.execute("SELECT mode FROM conversations").fetchone()[0] == "human"


def test_telegram_auth_and_private_chat_filter(server, monkeypatch):
    configure(monkeypatch, "telegram")
    _, client = server
    assert client.post("/webhooks/telegram", json=telegram()).status_code == 403
    group = telegram()
    group["message"]["chat"]["type"] = "group"
    assert post_telegram(client, group).json()["stored"] == 0


def test_telegram_idempotency(server, monkeypatch):
    configure(monkeypatch, "telegram")
    app, client = server
    assert post_telegram(client, telegram()).json()["stored"] == 1
    assert post_telegram(client, telegram()).json()["stored"] == 0
    with app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM webhook_events").fetchone()[0] == 1


def test_inbound_assigns_least_loaded_available_user_and_preserves_owner(server, monkeypatch):
    configure(monkeypatch, "telegram")
    app, client = server
    store = app.state.store
    owner = store.create_user({"name": "Asesor A", "email": "a@example.test", "password": "TestPassword-WithEntropy1", "role": "admin"}, bootstrap=True)
    allow(store, owner, "b@example.test")
    other = store.create_user({"name": "Asesor B", "email": "b@example.test", "password": "TestPassword-WithEntropy2", "role": "advisor"}, actor=owner)
    with store.connect() as db:
        db.execute("UPDATE users SET public_booking=1")
    post_telegram(client, telegram())
    initial = first_conversation(app)
    second = telegram(update=2)
    second["message"]["chat"]["id"] = 7654
    second["message"]["from"]["id"] = 7654
    post_telegram(client, second)
    with store.connect() as db:
        assignments = [row["advisor_id"] for row in db.execute("SELECT advisor_id FROM conversations")]
        assert set(assignments) == {owner["id"], other["id"]}
        db.execute("UPDATE users SET public_booking=0 WHERE id=?", (initial["advisor_id"],))
    post_telegram(client, telegram(update=3, text="Continúa mi conversación"))
    assert first_conversation(app)["advisor_id"] == initial["advisor_id"]


def test_inactive_or_unpublished_advisors_are_not_autoassigned(server, monkeypatch):
    configure(monkeypatch, "telegram")
    app, client = server
    app.state.store.create_user({"name": "No disponible", "email": "private@example.test", "password": "TestPassword-WithEntropy1", "role": "admin"}, bootstrap=True)
    post_telegram(client, telegram())
    assert first_conversation(app)["advisor_id"] is None


@pytest.mark.parametrize("opt_out", ["STOP", "No me escriban", "Quiero darme de baja", "No quiero recibir más mensajes"])
def test_optout_is_persistent_and_blocks_dispatch(server, monkeypatch, opt_out):
    configure(monkeypatch, "telegram")
    app, client = server
    post_telegram(client, telegram(text=opt_out))
    conversation = first_conversation(app)
    assert conversation["mode"] == "human"
    assert channels.reply_permission(app.state.store, conversation)["allowed"] is False
    post_telegram(client, telegram(update=2, text="Hola otra vez"))
    assert channels.reply_permission(app.state.store, conversation)["allowed"] is False
    post_telegram(client, telegram(update=3, text="/start"))
    assert channels.reply_permission(app.state.store, conversation)["allowed"] is True


def test_late_webhook_does_not_reopen_meta_24h_window(server, monkeypatch):
    configure(monkeypatch, "whatsapp")
    app, client = server
    assert post_meta(client, whatsapp(timestamp=int(time.time()) - 90000)).json()["stored"] == 1
    permission = channels.reply_permission(app.state.store, first_conversation(app))
    assert permission["allowed"] is False and "24 horas" in permission["reason"]


def test_human_handover_prevents_ai_response(server, monkeypatch):
    configure(monkeypatch, "telegram")
    app, client = server
    post_telegram(client, telegram())
    conversation = first_conversation(app)
    with app.state.store.connect() as db:
        db.execute("UPDATE conversations SET mode='ai' WHERE id=?", (conversation["id"],))
    async def unexpected(*args, **kwargs):
        raise AssertionError("Handover must not call AI")
    monkeypatch.setattr(assistant, "draft", unexpected)
    assert post_telegram(client, telegram(update=2, text="Quiero hablar con una persona")).status_code == 200
    assert first_conversation(app)["mode"] == "human"


def test_explicit_ai_mode_dispatches_once_and_retains_provider_status(server, monkeypatch):
    configure(monkeypatch, "telegram")
    app, client = server
    post_telegram(client, telegram())
    conversation = first_conversation(app)
    with app.state.store.connect() as db:
        db.execute("UPDATE conversations SET mode='ai' WHERE id=?", (conversation["id"],))
    sent = []
    async def fake_draft(*args, **kwargs):
        return "Soy el asistente virtual de Power Solar. Puedes elegir una cita en la agenda."
    async def fake_send(*args):
        sent.append(args)
        return {"status": "sent", "provider_id": "test-provider-id"}
    monkeypatch.setattr(assistant, "draft", fake_draft)
    monkeypatch.setattr(channels, "send_message", fake_send)
    post_telegram(client, telegram(update=2, text="¿Cómo agendo?"))
    post_telegram(client, telegram(update=2, text="¿Cómo agendo?"))
    assert len(sent) == 1
    with app.state.store.connect() as db:
        row = db.execute("SELECT status,external_id FROM messages WHERE direction='outbound'").fetchone()
        assert row["status"] == "sent" and row["external_id"] == "test-provider-id"


def test_ai_failure_hands_back_to_human_without_fabricated_reply(server, monkeypatch):
    configure(monkeypatch, "telegram")
    app, client = server
    post_telegram(client, telegram())
    with app.state.store.connect() as db:
        db.execute("UPDATE conversations SET mode='ai'")
    async def failed(*args, **kwargs):
        raise RuntimeError("Provider rejected")
    monkeypatch.setattr(assistant, "draft", failed)
    post_telegram(client, telegram(update=2, text="Necesito ayuda"))
    assert first_conversation(app)["mode"] == "human"
    with app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM messages WHERE direction='outbound'").fetchone()[0] == 0


def test_body_size_and_json_shape_are_bounded(server, monkeypatch):
    configure(monkeypatch, "telegram")
    _, client = server
    headers = {"X-Telegram-Bot-Api-Secret-Token": "test-secret"}
    assert client.post("/webhooks/telegram", content="x" * (channels.MAX_BODY + 1), headers=headers).status_code == 413
    assert client.post("/webhooks/telegram", json=[], headers=headers).status_code == 400
