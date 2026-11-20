"""The /ia workspace never calls a real model: stream_workspace is explicitly mocked."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from reigel import ai_chat, api
from reigel.ia_workspace import MAX_MESSAGES


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("REIGEL_CHAT_AI", "ollama")
    monkeypatch.setenv("REIGEL_CHAT_MODEL", "test-model")
    monkeypatch.delenv("REIGEL_CHAT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("REIGEL_IA_TIMEOUT_SECONDS", raising=False)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("REIGEL_CHAT_AI", raising=False)
    monkeypatch.setenv("REIGEL_ENV", "local")
    app = api.create_app(tmp_path / "ia.db")
    return TestClient(app)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("REIGEL_CHAT_AI", raising=False)
    monkeypatch.setenv("REIGEL_ENV", "local")
    return api.create_app(tmp_path / "ia-app.db")


def sse_events(text):
    events = []
    for block in text.split("\n\n"):
        event, data = "message", []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if data:
            events.append((event, json.loads("\n".join(data))))
    return events


def mock_stream(monkeypatch, pieces):
    seen = []

    async def fake_stream(history, incoming, verified=""):
        seen.append({"history": history, "incoming": incoming, "verified": verified})
        for piece in pieces:
            yield piece

    monkeypatch.setattr(ai_chat, "stream_workspace", fake_stream)
    return seen


def mock_stream_error(monkeypatch, error):
    async def fake_stream(history, incoming, verified=""):
        raise error
        yield ""  # pragma: no cover - keeps the function a generator

    monkeypatch.setattr(ai_chat, "stream_workspace", fake_stream)


def send(client, conversation_id, text):
    return client.post(f"/api/ia/conversations/{conversation_id}/messages", json={"text": text})


def test_page_bootstraps_a_temporary_visitor_session(client, configured):
    page = client.get("/ia")
    assert page.status_code == 200
    assert "/static/js/ia.js" in page.text
    assert page.headers["x-robots-tag"] == "noindex, nofollow"

    root = client.get("/")
    assert root.status_code == 200
    assert 'id="ia-shell"' in root.text
    assert root.headers["x-robots-tag"] == "noindex, nofollow"

    boot = client.get("/api/ia/bootstrap")
    assert boot.status_code == 200
    data = boot.json()
    assert data["owner"] == "visitor"
    assert data["user"] is None
    assert data["retention_days"] == 7
    assert data["conversations"] == []
    assert client.cookies.get("reigel_ia")
    cookie = boot.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Path=/api/ia" in cookie and "SameSite=strict" in cookie


def test_conversation_persists_streaming_reply_and_is_recoverable(client, app, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    created = client.post("/api/ia/conversations", json={})
    assert created.status_code == 200
    conversation = created.json()["conversation"]
    assert conversation["title"] == "Nueva conversación"

    seen = mock_stream(monkeypatch, ["Puedes ", "empezar por revisar ", "tu consumo mensual."])
    response = send(client, conversation["id"], "¿Por dónde empiezo con la energía solar?")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response.text)
    names = [name for name, _ in events]
    assert names[0] == "meta" and names[-1] == "done"
    assert "".join(data["text"] for name, data in events if name == "delta") == "Puedes empezar por revisar tu consumo mensual."
    assert seen[0]["incoming"] == "¿Por dónde empiezo con la energía solar?"
    assert seen[0]["history"] == []

    detail = client.get(f"/api/ia/conversations/{conversation['id']}").json()
    assert [item["role"] for item in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["status"] == "complete"
    assert detail["messages"][1]["content"] == "Puedes empezar por revisar tu consumo mensual."

    listing = client.get("/api/ia/conversations").json()["conversations"]
    assert [item["id"] for item in listing] == [conversation["id"]]
    assert listing[0]["title"].startswith("¿Por dónde empiezo")
    assert listing[0]["message_count"] == 2

    followup = client.post("/api/ia/conversations", json={}).json()["conversation"]
    assert followup["id"] != conversation["id"]


def test_history_is_sent_back_to_the_model(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    seen = mock_stream(monkeypatch, ["Primera respuesta."])
    send(client, conversation["id"], "Primera pregunta")
    seen.clear()

    async def second(history, incoming, verified=""):
        seen.append({"history": history, "incoming": incoming, "verified": verified})
        yield "Segunda respuesta."

    monkeypatch.setattr(ai_chat, "stream_workspace", second)
    send(client, conversation["id"], "Segunda pregunta")
    assert [item["role"] for item in seen[0]["history"]] == ["user", "assistant"]
    assert seen[0]["history"][0]["content"] == "Primera pregunta"


def test_separate_visitors_cannot_read_each_other(client, app, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream(monkeypatch, ["Respuesta privada."])
    send(client, conversation["id"], "Mensaje privado")
    visitor_cookie = client.cookies.get("reigel_ia")

    other = TestClient(app)
    other.get("/api/ia/bootstrap")
    assert other.cookies.get("reigel_ia") != visitor_cookie
    assert other.get(f"/api/ia/conversations/{conversation['id']}").status_code == 404
    assert other.post(
        f"/api/ia/conversations/{conversation['id']}/messages", json={"text": "Intruso"}
    ).status_code == 404
    assert other.get("/api/ia/conversations").json()["conversations"] == []


def test_authenticated_owner_keeps_history_across_sessions(app, configured, monkeypatch):
    with TestClient(app) as visitor:
        visitor.get("/api/ia/bootstrap")
        anon = visitor.post("/api/ia/conversations", json={}).json()["conversation"]
        mock_stream(monkeypatch, ["Hola."])
        send(visitor, anon["id"], "Sesión anónima")

    app.state.store.create_user(
        {"name": "Asesora IA", "email": "ia@example.test", "password": "correct-horse-test-42", "role": "advisor"},
        bootstrap=True,
    )
    first = TestClient(app)
    assert first.post("/api/auth/login", json={"email": "ia@example.test", "password": "correct-horse-test-42"}).status_code == 200
    boot = first.get("/api/ia/bootstrap").json()
    assert boot["owner"] == "user" and boot["user"]["name"] == "Asesora IA"
    assert boot["conversations"] == []
    conversation = first.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream(monkeypatch, ["Hola de nuevo."])
    send(first, conversation["id"], "Conversación de mi cuenta")

    second = TestClient(app)
    second.cookies.set("powersolar_session", first.cookies.get("powersolar_session"))
    boot = second.get("/api/ia/bootstrap").json()
    assert [item["id"] for item in boot["conversations"]] == [conversation["id"]]

    second.cookies.delete("powersolar_session")
    assert second.get(f"/api/ia/conversations/{conversation['id']}").status_code == 401


def test_stop_keeps_partial_and_regenerate_replaces_in_place(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream(monkeypatch, ["Texto inicial completo."])
    first = send(client, conversation["id"], "Cuéntame algo")
    assistant_id = [data for name, data in sse_events(first.text) if name == "meta"][0]["assistant_id"]
    before = client.get(f"/api/ia/conversations/{conversation['id']}").json()

    mock_stream(monkeypatch, ["Texto ", "regenerado ", "completo."])
    regenerated = client.post(
        f"/api/ia/conversations/{conversation['id']}/regenerate", json={"message_id": assistant_id}
    )
    assert regenerated.status_code == 200
    events = sse_events(regenerated.text)
    assert [name for name, _ in events][-1] == "done"
    assert events[0][1]["regenerate"] is True
    assert events[0][1]["assistant_id"] == assistant_id

    after = client.get(f"/api/ia/conversations/{conversation['id']}").json()
    assert len(after["messages"]) == len(before["messages"]) == 2
    assert after["messages"][1]["id"] == assistant_id
    assert after["messages"][1]["content"] == "Texto regenerado completo."


def test_regenerate_rejects_anything_but_the_last_reply(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream(monkeypatch, ["Uno."])
    ids = [data["assistant_id"] for name, data in sse_events(send(client, conversation["id"], "Primera").text) if name == "meta"]
    mock_stream(monkeypatch, ["Dos."])
    send(client, conversation["id"], "Segunda")
    response = client.post(
        f"/api/ia/conversations/{conversation['id']}/regenerate", json={"message_id": ids[0]}
    )
    assert response.status_code == 409


def test_unsafe_reply_is_replaced_and_persisted_as_rejected(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream(monkeypatch, ["El sistema cuesta $5,000 y queda garantizado."])
    response = send(client, conversation["id"], "¿Cuánto cuesta?")
    events = sse_events(response.text)
    names = [name for name, _ in events]
    assert "replace" in names and "done" not in names
    detail = client.get(f"/api/ia/conversations/{conversation['id']}").json()
    assert detail["messages"][1]["status"] == "rejected"
    assert detail["messages"][1]["content"] == ai_chat.SAFE_REPLACEMENT


def test_model_failure_returns_an_error_event_and_keeps_the_user_message(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream_error(monkeypatch, httpx.ConnectError("ollama down"))
    response = send(client, conversation["id"], "Hola")
    assert response.status_code == 200
    events = sse_events(response.text)
    assert [name for name, _ in events][-1] == "error"
    assert "Ollama" in events[-1][1]["detail"]
    detail = client.get(f"/api/ia/conversations/{conversation['id']}").json()
    assert [item["role"] for item in detail["messages"]] == ["user"]


def test_timeout_is_reported_as_such(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream_error(monkeypatch, httpx.TimeoutException("slow"))
    events = sse_events(send(client, conversation["id"], "Hola").text)
    assert events[-1][0] == "error"
    assert "tardó demasiado" in events[-1][1]["detail"]


def test_disabled_model_blocks_generation_but_not_history(client):
    client.get("/api/ia/bootstrap")
    boot = client.get("/api/ia/bootstrap").json()
    assert boot["model"]["enabled"] is False
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    assert send(client, conversation["id"], "Hola").status_code == 503
    assert client.post(
        f"/api/ia/conversations/{conversation['id']}/regenerate", json={"message_id": "x"}
    ).status_code == 503


def test_message_limit_closes_the_conversation(app, configured, monkeypatch):
    client = TestClient(app)
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    with app.state.store.connect() as db:
        for index in range(MAX_MESSAGES):
            db.execute(
                "INSERT INTO ai_messages VALUES(?,?,?,?,?,?)",
                (f"bulk-{index}", conversation["id"], "user", "texto", "complete", "2026-01-01T00:00:00+00:00"),
            )
    response = send(client, conversation["id"], "Uno más")
    assert response.status_code == 409
    assert "límite" in response.json()["detail"]


def test_blank_or_oversized_messages_are_rejected(client, configured):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    assert send(client, conversation["id"], "   ").status_code == 422
    assert send(client, conversation["id"], "x" * 4001).status_code == 422


def test_messages_require_the_visitor_session(client, configured):
    anonymous = TestClient(client.app)
    assert anonymous.get("/api/ia/conversations").status_code == 401
    assert anonymous.post("/api/ia/conversations", json={}).status_code == 401


# --- Output boundary: what reaches the client, what is stored, what returns to the model ---

UNSAFE = "$5,000"


def mock_stream_then_fail(monkeypatch, pieces, error):
    async def fake_stream(history, incoming, verified=""):
        for piece in pieces:
            yield piece
        raise error

    monkeypatch.setattr(ai_chat, "stream_workspace", fake_stream)


def delta_text(events):
    return "".join(data["text"] for name, data in events if name == "delta")


def stored_reply(client, conversation_id):
    messages = client.get(f"/api/ia/conversations/{conversation_id}").json()["messages"]
    return [item for item in messages if item["role"] == "assistant"]


def test_unsafe_single_chunk_is_never_streamed(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream(monkeypatch, ["El sistema cuesta $5,000 y queda garantizado."])
    response = send(client, conversation["id"], "¿Cuánto cuesta?")
    events = sse_events(response.text)
    assert [name for name, _ in events if name == "delta"] == []
    assert events[-1][0] == "replace"
    # The raw price may only appear nowhere in the stream body at all.
    assert UNSAFE not in response.text and "garantizado" not in response.text


def test_safe_sentences_stream_and_unsafe_tail_is_withheld(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream(monkeypatch, [
        "La energía solar ", "convierte luz en electricidad. ",
        "El sistema cuesta ", "$5,000 en total.",
    ])
    response = send(client, conversation["id"], "Explícame")
    events = sse_events(response.text)
    assert delta_text(events) == "La energía solar convierte luz en electricidad."
    assert UNSAFE not in response.text
    assert events[-1][0] == "replace"
    reply = stored_reply(client, conversation["id"])[0]
    assert reply["status"] == "rejected" and reply["content"] == ai_chat.SAFE_REPLACEMENT


def test_partial_after_error_keeps_only_validated_text(client, configured, monkeypatch):
    app = client.app
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream_then_fail(
        monkeypatch,
        ["Primera idea segura. ", "El sistema cuesta $5,000 y queda garantizado."],
        RuntimeError("synthetic stream failure"),
    )
    response = send(client, conversation["id"], "Hola")
    events = sse_events(response.text)
    assert events[-1][0] == "error"
    assert UNSAFE not in response.text
    assert delta_text(events) == "Primera idea segura."
    assert events[-1][1]["assistant"]["content"] == "Primera idea segura."

    reply = stored_reply(client, conversation["id"])[0]
    assert reply["status"] == "stopped" and reply["content"] == "Primera idea segura."
    assert not any(UNSAFE in item["content"] for item in app.state.ia.history(conversation["id"]))

    seen = mock_stream(monkeypatch, ["Sigo aquí."])
    send(client, conversation["id"], "Continúa")
    assert not any(UNSAFE in item["content"] for item in seen[0]["history"])


def test_error_before_any_validated_sentence_discards_the_reply(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream_then_fail(monkeypatch, ["El sistema cuesta $5,000 y"], httpx.ReadTimeout("slow"))
    response = send(client, conversation["id"], "Hola")
    events = sse_events(response.text)
    assert events[-1][0] == "error" and events[-1][1]["assistant"] is None
    assert UNSAFE not in response.text
    assert stored_reply(client, conversation["id"]) == []


def test_legacy_unsafe_partial_is_not_sent_back_to_the_model(client, configured, monkeypatch):
    app = client.app
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    with app.state.store.connect() as db:
        db.execute(
            "INSERT INTO ai_messages VALUES(?,?,?,?,?,?)",
            ("legacy-user", conversation["id"], "user", "Pregunta previa", "complete", "2026-01-01T00:00:00+00:00"),
        )
        db.execute(
            "INSERT INTO ai_messages VALUES(?,?,?,?,?,?)",
            ("legacy-partial", conversation["id"], "assistant", "El sistema cuesta $5,000 y queda",
             "stopped", "2026-01-01T00:00:01+00:00"),
        )
    seen = mock_stream(monkeypatch, ["Respuesta nueva."])
    send(client, conversation["id"], "Otra pregunta")
    assert [item["content"] for item in seen[0]["history"]] == ["Pregunta previa"]


def ollama_lines(monkeypatch, lines):
    real = httpx.AsyncClient

    def handler(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"details": {}})
        body = "".join(json.dumps(line) + "\n" for line in lines)
        return httpx.Response(200, content=body.encode())

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))


def collect(generator):
    import asyncio

    async def run():
        return [piece async for piece in generator]

    return asyncio.run(run())


def test_stream_without_done_signal_is_reported_as_truncated(configured, monkeypatch):
    ollama_lines(monkeypatch, [{"message": {"content": "Texto "}}, {"message": {"content": "cortado"}}])
    with pytest.raises(RuntimeError):
        collect(ai_chat.stream_workspace([], "Hola"))


# --- Public buttons ask whether /ia can answer before sending visitors there ---

@pytest.mark.parametrize("model, expected", [
    ({"enabled": True, "status": "available"}, True),
    ({"enabled": True, "status": "unavailable"}, False),
    ({"enabled": True, "status": "model_missing"}, False),
    ({"enabled": False, "status": "disabled"}, False),
])
def test_status_reports_whether_ia_can_answer(client, monkeypatch, model, expected):
    async def fake_status():
        return model

    monkeypatch.setattr(ai_chat, "status", fake_status)
    response = client.get("/api/ia/status")
    assert response.status_code == 200
    assert response.json() == {"available": expected}


def test_status_creates_no_visitor_session(client, monkeypatch):
    async def fake_status():
        return {"enabled": True, "status": "available", "model": "secreto-local"}

    monkeypatch.setattr(ai_chat, "status", fake_status)
    response = client.get("/api/ia/status")
    assert "set-cookie" not in response.headers
    assert "secreto-local" not in response.text
    with client.app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM ai_visitors").fetchone()[0] == 0


# --- The model-error notice stays visible at every width ---

def test_model_error_notice_is_never_hidden_by_css():
    import re
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "frontend" / "css" / "ia.css").read_text(encoding="utf-8")
    blocks = re.findall(r"([^{}]*\.ia-disclaimer[^{}]*)\{([^{}]*)\}", css)
    assert blocks
    for selector, body in blocks:
        assert not re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", body), selector.strip()
        size = re.search(r"font-size\s*:\s*(\d+)px", body)
        assert not size or int(size.group(1)) >= 11, selector.strip()


def test_model_error_notice_is_in_the_page(client):
    assert "puede equivocarse" in client.get("/ia").text


# --- Privacy: /ia has no consent flow, so contact data is hidden before it is stored ---

CONTACT_TEXT = "Escríbeme a persona.ficticia@example.test o llama al (787) 555-0100, mi factura ronda 150."


def test_contact_data_is_hidden_before_storing(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    seen = mock_stream(monkeypatch, ["Gracias por escribir."])
    response = send(client, conversation["id"], CONTACT_TEXT)
    assert "example.test" not in response.text and "555-0100" not in response.text

    detail = client.get(f"/api/ia/conversations/{conversation['id']}").json()
    stored = detail["messages"][0]["content"]
    assert "example.test" not in stored and "555-0100" not in stored
    assert "[correo omitido]" in stored and "[teléfono omitido]" in stored
    assert "ronda 150" in stored  # short figures that are not contacts stay
    assert "example.test" not in detail["conversation"]["title"]
    listing = client.get("/api/ia/conversations").json()["conversations"][0]
    assert "555-0100" not in listing["title"] + listing["preview"]

    assert "example.test" not in seen[0]["incoming"] and "555-0100" not in seen[0]["incoming"]
    with client.app.state.store.connect() as db:
        raw = " ".join(row[0] for row in db.execute("SELECT content FROM ai_messages").fetchall())
        titles = " ".join(row[0] for row in db.execute("SELECT title FROM ai_conversations").fetchall())
    assert "example.test" not in raw + titles and "555-0100" not in raw + titles


def test_contact_data_is_hidden_for_authenticated_owners_too(app, configured, monkeypatch):
    app.state.store.create_user(
        {"name": "Cuenta IA", "email": "privada@example.test", "password": "correct-horse-test-42", "role": "advisor"},
        bootstrap=True,
    )
    client = TestClient(app)
    client.post("/api/auth/login", json={"email": "privada@example.test", "password": "correct-horse-test-42"})
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream(monkeypatch, ["Recibido."])
    send(client, conversation["id"], CONTACT_TEXT)
    stored = client.get(f"/api/ia/conversations/{conversation['id']}").json()["messages"][0]["content"]
    assert "example.test" not in stored and "555-0100" not in stored


def test_redaction_never_pushes_a_message_past_the_model_limit(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    seen = mock_stream(monkeypatch, ["Recibido."])
    dense = ("a@b.co " * 600)[:4000]
    response = send(client, conversation["id"], dense)
    assert response.status_code == 200
    assert len(seen[0]["incoming"]) <= 4000


def test_ia_tells_visitors_not_to_share_contact_data(client):
    page = client.get("/ia").text
    assert "oculta" in page and "correo" in page and "teléfono" in page


# --- Message limit: a turn (question + reply) fits whole or is refused ---

def fill(app, conversation_id, count):
    with app.state.store.connect() as db:
        for index in range(count):
            db.execute(
                "INSERT INTO ai_messages VALUES(?,?,?,?,?,?)",
                (f"fill-{index}", conversation_id, "user", "texto", "complete", "2026-01-01T00:00:00+00:00"),
            )


def stored_count(app, conversation_id):
    with app.state.store.connect() as db:
        return db.execute("SELECT count(*) FROM ai_messages WHERE conversation_id=?", (conversation_id,)).fetchone()[0]


def test_turn_that_would_exceed_the_limit_is_refused_without_writes(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    fill(client.app, conversation["id"], MAX_MESSAGES - 1)
    mock_stream(monkeypatch, ["Respuesta."])
    response = send(client, conversation["id"], "Mensaje número doscientos")
    assert response.status_code == 409
    assert "límite" in response.json()["detail"]
    assert stored_count(client.app, conversation["id"]) == MAX_MESSAGES - 1


def test_last_complete_turn_reaches_the_limit_exactly(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    fill(client.app, conversation["id"], MAX_MESSAGES - 2)
    mock_stream(monkeypatch, ["Respuesta."])
    assert sse_events(send(client, conversation["id"], "Último turno").text)[-1][0] == "done"
    assert stored_count(client.app, conversation["id"]) == MAX_MESSAGES
    assert send(client, conversation["id"], "Uno más").status_code == 409
    assert stored_count(client.app, conversation["id"]) == MAX_MESSAGES


def test_concurrent_turns_cannot_overrun_the_limit(client, configured):
    from concurrent.futures import ThreadPoolExecutor

    from reigel.core import DomainError

    client.get("/api/ia/bootstrap")
    owner = {"kind": "visitor", "id": client.app.state.ia.visitor(client.cookies.get("reigel_ia"))}
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    fill(client.app, conversation["id"], MAX_MESSAGES - 2)

    def attempt(index):
        try:
            client.app.state.ia.begin_turn(owner, conversation["id"], f"Pestaña {index}")
            return "ok"
        except DomainError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count("ok") == 1 and results.count(409) == 3
    assert stored_count(client.app, conversation["id"]) == MAX_MESSAGES


# --- Visitor retention: seven days from the last activity, in the database and the browser ---

def visitor_row(app):
    with app.state.store.connect() as db:
        return dict(db.execute("SELECT expires_at,last_seen_at FROM ai_visitors").fetchone())


def age_visitor(app, expires_at, last_seen_at="2020-01-01T00:00:00+00:00"):
    with app.state.store.connect() as db:
        db.execute("UPDATE ai_visitors SET expires_at=?,last_seen_at=?", (expires_at, last_seen_at))


def assert_renewed(app, response, token):
    from datetime import UTC, datetime, timedelta

    row = visitor_row(app)
    expires = datetime.fromisoformat(row["expires_at"])
    now = datetime.now(UTC)
    assert now + timedelta(days=7) - timedelta(minutes=1) < expires <= now + timedelta(days=7)
    assert row["last_seen_at"] > "2020-01-01T00:00:00+00:00"
    cookie = response.headers.get("set-cookie", "")
    assert f"reigel_ia={token}" in cookie and "Max-Age=604800" in cookie
    assert "HttpOnly" in cookie and "Path=/api/ia" in cookie and "SameSite=strict" in cookie


def soon():
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(hours=1)).isoformat()


def test_opening_ia_renews_visitor_retention_and_cookie(client, configured):
    client.get("/api/ia/bootstrap")
    token = client.cookies.get("reigel_ia")
    age_visitor(client.app, soon())
    response = client.get("/api/ia/bootstrap")
    assert response.json()["owner"] == "visitor"
    assert_renewed(client.app, response, token)
    assert client.cookies.get("reigel_ia") == token


def test_sending_a_message_renews_visitor_retention_and_cookie(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    token = client.cookies.get("reigel_ia")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    age_visitor(client.app, soon())
    mock_stream(monkeypatch, ["Respuesta breve."])
    response = send(client, conversation["id"], "Hola")
    assert sse_events(response.text)[-1][0] == "done"
    assert_renewed(client.app, response, token)


def test_reading_history_does_not_count_as_activity(client, configured):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    expiry = soon()
    age_visitor(client.app, expiry)
    response = client.get(f"/api/ia/conversations/{conversation['id']}")
    assert response.status_code == 200
    assert visitor_row(client.app)["expires_at"] == expiry
    assert "set-cookie" not in response.headers


def test_expired_visitor_is_not_revived(client, configured):
    client.get("/api/ia/bootstrap")
    token = client.cookies.get("reigel_ia")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    age_visitor(client.app, "2020-01-02T00:00:00+00:00")
    response = client.get("/api/ia/bootstrap")
    assert client.cookies.get("reigel_ia") != token
    assert response.json()["conversations"] == []
    assert client.get(f"/api/ia/conversations/{conversation['id']}").status_code == 404


def test_authenticated_owner_gets_no_visitor_cookie(app, configured):
    app.state.store.create_user(
        {"name": "Cuenta IA", "email": "cuenta@example.test", "password": "correct-horse-test-42", "role": "advisor"},
        bootstrap=True,
    )
    client = TestClient(app)
    client.post("/api/auth/login", json={"email": "cuenta@example.test", "password": "correct-horse-test-42"})
    response = client.get("/api/ia/bootstrap")
    assert response.json()["owner"] == "user"
    assert "reigel_ia" not in response.headers.get("set-cookie", "")


QUANTITATIVE_CLAIMS = [
    # Reproduced in audit_ia_evidence.py: both passed before the quantity policy.
    "Con un sistema solar puedes ahorrar 80% en tu factura.",
    "La bateria te da 24 horas de respaldo.",
    # Same claims without digits.
    "Podrías ahorrar ochenta por ciento de lo que pagas.",
    "La batería dura veinticuatro horas.",
    "Tu factura bajaría a la mitad.",
    "Con un buen diseño reduces el consumo de la red en dos tercios.",
    "Recuperas la inversión en cinco años.",
    "Durante un apagón, una batería puede mantener dos o tres equipos.",
    # Any digit, even educational: the policy admits no quantities.
    "Un panel de 400 W genera bastante energía.",
    "Un kilovatio hora equivale a 1000 vatios durante una hora.",
    # Absolute promises with an implicit quantity.
    "Con paneles tu factura queda en cero.",
    "Así eliminas por completo tu factura de luz.",
    "Nunca más pagarás la luz.",
    "Lograrás independencia energética total.",
    "Tendrás autonomía ilimitada durante los apagones.",
    "El sistema se paga solo.",
]


@pytest.mark.parametrize("claim", QUANTITATIVE_CLAIMS)
def test_workspace_validator_rejects_quantitative_promises(claim):
    with pytest.raises(ValueError):
        ai_chat.validate_workspace_reply(claim, verified=False)
    with pytest.raises(ValueError):
        ai_chat.validate_workspace_reply(claim, verified=True)


@pytest.mark.parametrize("text", [
    "La energía solar convierte la luz en electricidad mediante celdas fotovoltaicas.",
    "Hay dos o tres aspectos que conviene revisar con el equipo.",
    "Hay tres pasos: revisar el consumo, evaluar el techo y diseñar el sistema.",
    "Durante un apagón, una batería puede respaldar equipos seleccionados.",
    "Puedes respaldar los cuartos que más uses; el equipo evalúa la capacidad necesaria.",
    "Te recomiendo revisar tus facturas de los últimos meses antes de la evaluación.",
    "El ahorro depende de tu consumo, tu tarifa y el diseño; el equipo puede evaluarlo.",
    "Una batería puede respaldar equipos seleccionados durante un apagón; la duración depende de la capacidad y el consumo.",
    "No significa que toda la casa funcione indefinidamente.",
    "Un inversor transforma la corriente continua en corriente alterna.",
])
def test_workspace_validator_keeps_qualitative_explanations(text):
    assert ai_chat.validate_workspace_reply(text, verified=False) == text


def test_quantitative_promise_mid_stream_is_withheld(client, configured, monkeypatch):
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    mock_stream(monkeypatch, [
        "La energía solar aprovecha la luz del día. ",
        "Con un sistema solar puedes ahorrar 80% en tu factura.",
    ])
    response = send(client, conversation["id"], "¿Me conviene?")
    events = sse_events(response.text)
    assert delta_text(events) == "La energía solar aprovecha la luz del día."
    assert "80%" not in response.text
    assert events[-1][0] == "replace"


def test_workspace_prompt_states_the_quantity_policy():
    prompt = ai_chat.workspace_instructions()
    assert "números" in prompt and "porcentajes" in prompt


def test_stream_with_done_signal_completes(configured, monkeypatch):
    ollama_lines(monkeypatch, [{"message": {"content": "Texto "}}, {"message": {"content": "completo."}, "done": True}])
    assert collect(ai_chat.stream_workspace([], "Hola")) == ["Texto ", "completo."]
