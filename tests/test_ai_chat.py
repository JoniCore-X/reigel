"""The optional local model is mocked explicitly; no test runs inference or uses a cloud key."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from reigel import ai_chat, api
from reigel.core import Store
from reigel.webchat import WebChat

REAL_ASYNC_CLIENT = httpx.AsyncClient


class Knowledge:
    def public_status(self):
        return {"freshness": "unavailable", "sources": []}

    def answer(self, query):
        return None

    def answer_technical(self, query):
        return None


def run(coro):
    return asyncio.run(coro)


def transport(monkeypatch, handler):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs))


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("REIGEL_CHAT_AI", "ollama")
    monkeypatch.setenv("REIGEL_CHAT_MODEL", "test-model")
    monkeypatch.delenv("REIGEL_CHAT_TIMEOUT_SECONDS", raising=False)


@pytest.fixture
def chat(tmp_path):
    store = Store(tmp_path / "ai-chat.db")
    service = WebChat(store, Knowledge())
    token, _ = service.start()
    return service, store, token


def test_reply_uses_only_local_ollama_without_tools_or_credentials(configured, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.host == "127.0.0.1" and request.url.port == 11434
        assert "Authorization" not in request.headers
        body = json.loads(request.content)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {}})
        assert request.url.path == "/api/chat"
        assert body["model"] == "test-model" and body["stream"] is False
        assert "tools" not in body
        system = body["messages"][0]["content"]
        assert "No prometas" in system and "No confirmes" in system
        assert "cliente@example.test" not in json.dumps(body["messages"], ensure_ascii=False)
        return httpx.Response(200, json={
            "done": True,
            "message": {"content": "Entiendo tu preocupación por el ruido. ¿Qué te gustaría aclarar primero?"},
        })

    transport(monkeypatch, handler)
    answer = run(ai_chat.reply(
        "Me preocupa el ruido de los equipos",
        [{"direction": "inbound", "text": "Mi correo es cliente@example.test"}],
        {"priority": "factura", "municipality": "Caguas"},
        "Power Solar ofrece soluciones solares para hogares.",
    ))
    assert "ruido" in answer
    assert len(seen) == 2


def test_technical_questions_never_reach_the_model(configured, monkeypatch):
    def handler(request):
        raise AssertionError("technical questions stay in the deterministic motor")

    transport(monkeypatch, handler)
    for text in (
        "¿Los paneles funcionan cuando está nublado?",
        "¿Puedo poner paneles si vivo en un apartamento?",
        "¿Qué pasa si se va la luz y tengo baterías?",
    ):
        assert run(ai_chat.reply(text, [], {})) is None


def test_conversational_question_reaches_the_model(configured, monkeypatch):
    def handler(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {}})
        return httpx.Response(200, json={
            "done": True,
            "message": {"content": "Entiendo tu preocupación. ¿Qué te gustaría aclarar primero?"},
        })

    transport(monkeypatch, handler)
    assert run(ai_chat.reply("Me preocupa el ruido", [], {})) == "Entiendo tu preocupación. ¿Qué te gustaría aclarar primero?"


def test_technical_drafts_need_a_verified_source(configured):
    draft = "Los paneles solares generan energía durante el día."
    with pytest.raises(ValueError):
        ai_chat.validate_reply(draft)
    assert ai_chat.validate_reply(draft, verified=True) == draft


def test_topic_mentions_pass_but_technical_claims_do_not(configured):
    assert ai_chat.validate_reply("Puedo orientarte sobre energía solar. ¿Qué necesitas saber?")
    for draft in (
        "Esa batería puede alimentar tu nevera toda la noche.",
        "La instalación requiere permisos del municipio.",
        "El inversor convierte la corriente de los paneles.",
    ):
        with pytest.raises(ValueError):
            ai_chat.validate_reply(draft)


def test_remote_cloud_alias_is_refused(configured, monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"remote_host": "https://ollama.com", "remote_model": "paid"})

    transport(monkeypatch, handler)
    assert run(ai_chat.reply("Hola", [], {})) is None


def test_model_outage_returns_none_without_remote_fallback(configured, monkeypatch):
    destinations = []

    def handler(request):
        destinations.append(request.url.host)
        raise httpx.ConnectError("offline", request=request)

    transport(monkeypatch, handler)
    assert run(ai_chat.reply("Hola", [], {})) is None
    assert destinations == ["127.0.0.1"]


def test_disabled_gateway_makes_no_request(monkeypatch):
    monkeypatch.delenv("REIGEL_CHAT_AI", raising=False)

    def handler(request):
        raise AssertionError("disabled gateway must not call the model")

    transport(monkeypatch, handler)
    assert ai_chat.enabled() is False
    assert run(ai_chat.reply("Hola", [], {})) is None


@pytest.mark.parametrize("draft", [
    "Tu ahorro será de 30 por ciento.",
    "La cita está confirmada para mañana.",
    "Hola [Nombre], podemos revisar tu caso.",
    "Consulta https://example.test para más información.",
    "Financiamiento aprobado sin revisar tu caso.",
])
def test_unsafe_drafts_are_rejected(configured, monkeypatch, draft):
    def handler(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {}})
        return httpx.Response(200, json={"done": True, "message": {"content": draft}})

    transport(monkeypatch, handler)
    assert run(ai_chat.reply("Tengo una duda", [], {})) is None
    with pytest.raises(ValueError):
        ai_chat.validate_reply(draft)


def test_build_messages_sanitizes_and_limits_history(configured, monkeypatch):
    monkeypatch.setenv("REIGEL_CHAT_HISTORY", "3")
    history = [
        {"direction": "inbound", "text": f"mensaje {index}"} for index in range(6)
    ]
    history.append({"direction": "inbound", "text": "Mi teléfono es +1 (787) 555-1234"})
    messages = ai_chat.build_messages("¿Y el tejado?", history, {}, None)
    reviewed = messages[1:-1]
    assert len(reviewed) == 3
    serialized = json.dumps(reviewed, ensure_ascii=False)
    assert "555-1234" not in serialized
    assert all("Historial no confiable" in item["content"] for item in reviewed)
    assert "Mensaje del visitante" in messages[-1]["content"]


def test_ai_brief_covers_only_unclassified_messages(chat):
    service, _, token = chat
    brief = service.ai_brief(token, "Tengo una duda sobre la lluvia y mi tejado", "brief-unknown-001")
    assert brief and brief["fingerprint"] and brief["verified"] == ""
    assert any("R.E.I.G.E.L." in item["text"] for item in brief["history"])
    assert service.ai_brief(token, "Quiero reservar una cita", "brief-booking-001") is None
    service.message(token, "/stop", "brief-stop-001")
    assert service.ai_brief(token, "Tengo otra duda sobre el tejado", "brief-unknown-002") is None


def test_model_reply_is_used_only_for_unknown_messages_and_matching_state(chat):
    service, _, token = chat
    text = "Tengo una duda sobre la lluvia y mi tejado"
    brief = service.ai_brief(token, text, "use-unknown-001")
    answer = service.message(
        token, text, "use-unknown-001",
        ai_reply="Puedo orientarte sobre eso. ¿Qué te preocupa del tejado?",
        ai_fingerprint=brief["fingerprint"],
    )
    assert answer["reply"] == "Puedo orientarte sobre eso. ¿Qué te preocupa del tejado?"

    booking = service.message(
        token, "Quiero reservar una cita", "use-booking-001",
        ai_reply="No debería usarse.", ai_fingerprint="stale",
    )
    assert "No debería" not in booking["reply"] and "cita" in booking["reply"].lower()

    stale = service.message(
        token, "Otra duda sobre el tejado", "use-stale-001",
        ai_reply="No debería usarse.", ai_fingerprint="stale",
    )
    assert "No debería" not in stale["reply"]


def test_duplicate_request_skips_the_model(chat, configured):
    service, _, token = chat
    text = "Tengo una duda sobre la lluvia"
    service.message(token, text, "duplicate-ai-001", ai_reply="Respuesta revisada. ¿Qué más quieres saber?", ai_fingerprint=None)
    assert service.ai_brief(token, text, "duplicate-ai-001") is None


def test_http_route_uses_model_only_when_configured(tmp_path, configured, monkeypatch):
    app = api.create_app(tmp_path / "ai-route.db")
    client = TestClient(app)
    client.get("/api/public/chat")
    calls = []

    async def fake_reply(incoming, history, profile, verified=None):
        calls.append(incoming)
        return "Puedo orientarte sobre ese tema. ¿Qué te gustaría aclarar primero?"

    monkeypatch.setattr(ai_chat, "reply", fake_reply)
    result = client.post("/api/public/chat", json={"text": "Tengo una duda sobre mi tejado", "request_id": "route-ai-001"})
    assert result.status_code == 200
    assert result.json()["reply"].startswith("Puedo orientarte")
    assert calls == ["Tengo una duda sobre mi tejado"]

    result = client.post("/api/public/chat", json={"text": "Quiero reservar una cita", "request_id": "route-ai-002"})
    assert result.status_code == 200
    assert "No debería" not in result.json()["reply"]
    assert len(calls) == 1


def test_http_route_falls_back_when_the_model_fails(tmp_path, configured, monkeypatch):
    app = api.create_app(tmp_path / "ai-route-fallback.db")
    client = TestClient(app)
    client.get("/api/public/chat")

    async def failed(*args, **kwargs):
        return None

    monkeypatch.setattr(ai_chat, "reply", failed)
    result = client.post("/api/public/chat", json={"text": "Tengo una duda sobre mi tejado", "request_id": "route-ai-003"})
    assert result.status_code == 200
    assert "tejado" not in result.json()["reply"]
    assert result.json()["reply"]
