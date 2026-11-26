"""Maintenance, cleaning, damage and emergencies get fixed replies, never model text."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from reigel import ai_chat, safety, suggestions
from reigel.api import create_app
from reigel.core import Store
from reigel.webchat import WebChat

from test_webchat import Knowledge


@pytest.mark.parametrize("text,topic", [
    ("Veo humo saliendo del inversor", "emergency"),
    ("Huele a quemado cerca de la batería", "emergency"),
    ("Hay un cable caído en el patio", "emergency"),
    ("¿Qué reviso después de una tormenta antes de volver a usar el sistema?", "storm"),
    ("¿Cómo limpio las placas?", "cleaning"),
    ("¿Cómo sé cuándo hay que limpiarlas?", "cleaning"),
    ("¿Puedo subir al techo a verlas?", "cleaning"),
    ("El inversor se dañó", "damage"),
    ("¿Qué pasa si el inversor se daña?", "damage"),
    ("Tengo una placa rota", "damage"),
    ("Mi batería no prende", "damage"),
    ("¿Cómo desconecto el inversor?", "damage"),
    ("¿Cuánto mantenimiento necesitan las placas?", "maintenance"),
])
def test_risky_messages_are_detected(text, topic):
    assert safety.classify(text) == topic


@pytest.mark.parametrize("text", [
    "¿Por qué el sistema no funciona en un apagón?",
    "¿Qué pasa con mis placas cuando se va la luz?",
    "¿Una batería puede mantener toda mi casa?",
    "¿Qué es la medición neta?",
    "Quiero limpiar mi historial",
    "Mi techo es pequeño",
    "¿Qué pasa si hay varios días nublados después de un huracán?",
])
def test_ordinary_questions_are_not_treated_as_emergencies(text):
    assert safety.classify(text) is None


def test_no_catalog_suggestion_is_captured_by_a_fixed_reply():
    assert [item.text for item in suggestions.CATALOG if safety.classify(item.text)] == []


def test_fixed_replies_never_instruct_hands_on_work():
    for topic in ("storm", "cleaning", "damage", "maintenance", "emergency"):
        text = safety._REPLIES[topic].format(handoff=safety.HANDOFF_IA)
        assert "técnico" in text or "911" in text
        assert not ai_chat._UNSAFE_DIY.search(ai_chat._plain(text)), text


def test_ia_answers_without_calling_the_model(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.setenv("REIGEL_CHAT_AI", "ollama")
    monkeypatch.setenv("REIGEL_CHAT_MODEL", "test-model")

    async def never(*_args, **_kwargs):
        raise AssertionError("The model must not be called")
        yield ""

    monkeypatch.setattr(ai_chat, "stream_workspace", never)
    client = TestClient(create_app(tmp_path / "safety.db"))
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]["id"]
    response = client.post(f"/api/ia/conversations/{conversation}/messages", json={"text": "¿Cómo limpio las placas?"})
    assert "event: done" in response.text and "No subas al techo" in response.text
    stored = client.get(f"/api/ia/conversations/{conversation}").json()["messages"][-1]
    assert stored["status"] == "complete" and "técnico" in stored["content"]


def test_coordination_chat_uses_the_same_fixed_reply(tmp_path):
    service = WebChat(Store(tmp_path / "chat.db"), Knowledge())
    token, _ = service.start()
    result = service.message(token, "Se dañó el inversor", "safety-chat-001")
    assert "No toques" in result["reply"] and "atención humana" in result["reply"]


def test_unreviewed_channel_reply_uses_the_fixed_text(tmp_path, monkeypatch):
    from reigel import assistant, channels
    from reigel.core import stamp

    store = Store(tmp_path / "channel.db")
    with store.connect() as db:
        db.execute("INSERT INTO conversations(id,channel,external_id,contact_name,mode,updated_at) VALUES('c','telegram','x','Persona','ai',?)", (stamp(),))
    sent = []

    async def never(*_args, **_kwargs):
        raise AssertionError("The model must not be called")

    async def capture(channel, external_id, text):
        sent.append(text)
        return {"status": "sent", "provider_id": "p"}

    monkeypatch.setattr(assistant, "draft", never)
    monkeypatch.setattr(channels, "send_message", capture)
    monkeypatch.setattr(channels, "reply_permission", lambda *_: {"allowed": True})
    asyncio.run(channels._respond_locked(store, "c", "event-1", "¿Cómo limpio las placas?"))
    assert len(sent) == 1 and "No subas al techo" in sent[0]

