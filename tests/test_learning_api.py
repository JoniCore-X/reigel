"""Aprendizaje (tramo B): rutas, permisos en servidor, captura de huecos y banco desde /app."""
import time

import pytest
from fastapi.testclient import TestClient

from reigel import ai_chat, api, learning_eval
from team_auth import allow, login as team_login

PASSWORD = "synthetic-password-learning-api"
GOOD_ANSWER = (
    "Ese trabajo lo hace el equipo de Power Solar. El equipo revisa la estructura del techo y su "
    "pendiente antes de proponer nada. Si quieres esa evaluación, pídela en «Citas y equipo»."
)
ROOF = "¿Qué debo revisar si mi techo es de madera y de baja pendiente?"


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.delenv("REIGEL_CHAT_AI", raising=False)
    app = api.create_app(tmp_path / "learning-api.db")
    store = app.state.store
    admin = store.create_user({"name": "QA Admin", "email": "la-admin@example.test", "password": PASSWORD, "role": "admin"}, bootstrap=True)
    allow(store, admin, "la-advisor@example.test")
    advisor = store.create_user({"name": "QA Asesor", "email": "la-advisor@example.test", "password": PASSWORD, "role": "advisor"}, admin)
    return app, admin, advisor


def login(client, person):
    response = team_login(client, person["email"], PASSWORD)
    assert response.status_code == 200, response.text


def test_queue_is_built_by_create_app_and_migrated_additively(system):
    app, *_ = system
    with app.state.store.connect() as db:
        tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"learning_gaps", "learning_proposals", "learning_eval_cases", "learning_eval_runs"} <= tables


def test_routes_enforce_team_access_and_admin_decisions(system):
    app, admin, advisor = system
    gap = app.state.learning.record_gap("ia", "blocked", ROOF)
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/learning/gaps").status_code == 401
        assert anonymous.get("/api/learning/eval").status_code == 401
    with TestClient(app) as adviser, TestClient(app) as manager:
        login(adviser, advisor)
        login(manager, admin)
        listing = adviser.get("/api/learning/gaps").json()
        assert [item["id"] for item in listing["gaps"]] == [gap["id"]] and listing["can_review"] is False
        assert manager.get("/api/learning/gaps").json()["can_review"] is True
        created = adviser.post(f"/api/learning/gaps/{gap['id']}/proposals",
                               json={"proposed_answer": GOOD_ANSWER, "source_note": "Criterio del titular."})
        assert created.status_code == 201
        proposal = created.json()["proposal"]
        for path in (f"/api/learning/proposals/{proposal['id']}/approve", f"/api/learning/proposals/{proposal['id']}/reject",
                     f"/api/learning/gaps/{gap['id']}/reject", f"/api/learning/gaps/{gap['id']}/resolve"):
            assert adviser.post(path, json={}).status_code == 403, path
        assert adviser.post("/api/learning/eval", json={}).status_code == 403
        assert manager.post(f"/api/learning/proposals/{proposal['id']}/archive", json={}).status_code == 404
        hostile = manager.post(f"/api/learning/proposals/{proposal['id']}/approve", json={},
                               headers={"Origin": "https://evil.example"})
        assert hostile.status_code == 403
        approved = manager.post(f"/api/learning/proposals/{proposal['id']}/approve", json={"note": "Revisado."})
        assert approved.status_code == 200 and approved.json()["proposal"]["status"] == "approved"
        assert adviser.get(f"/api/learning/gaps/{gap['id']}/proposals").json()["proposals"][0]["status"] == "approved"
        assert manager.post(f"/api/learning/gaps/{gap['id']}/resolve", json={}).status_code == 200


def test_approval_through_the_api_is_refused_when_validators_fail(system):
    app, admin, advisor = system
    gap = app.state.learning.record_gap("chat", "fallback", "¿Cuánto cuesta?")
    with TestClient(app) as manager:
        login(manager, admin)
        proposal = manager.post(f"/api/learning/gaps/{gap['id']}/proposals",
                                json={"proposed_answer": "Cuesta 15,000 dólares.", "source_note": "prueba"}).json()["proposal"]
        refused = manager.post(f"/api/learning/proposals/{proposal['id']}/approve", json={})
        assert refused.status_code == 422 and refused.json()["detail"].startswith("No se puede aprobar:")


def test_staff_can_flag_a_redacted_question_and_flags_are_rate_limited(system):
    app, _, advisor = system
    with TestClient(app) as adviser:
        login(adviser, advisor)
        flagged = adviser.post("/api/learning/gaps", json={"route": "ia", "question": "Me llamo Ana Ruiz, 787-555-0101: ¿quién instala?"})
        assert flagged.status_code == 201
        assert flagged.json()["gap"]["reason"] == "staff_flag"
        assert "Ana" not in flagged.json()["gap"]["question"] and "555" not in flagged.json()["gap"]["question"]
        assert adviser.post("/api/learning/gaps", json={"route": "web", "question": "x"}).status_code == 422
        codes = {adviser.post("/api/learning/gaps", json={"route": "ia", "question": f"pregunta {chr(97 + n % 26)}"}).status_code
                 for n in range(70)}
        assert 429 in codes


def test_ia_blocked_reply_is_captured_without_visitor_data(system, monkeypatch):
    app, admin, _ = system
    monkeypatch.setenv("REIGEL_CHAT_AI", "ollama")
    monkeypatch.setenv("REIGEL_CHAT_MODEL", "test-model")

    async def fake_stream(history, incoming, verified="", reviewed=()):
        yield "Reservaste una cita para una evaluación."

    monkeypatch.setattr(ai_chat, "stream_workspace", fake_stream)
    with TestClient(app) as visitor:
        visitor.get("/api/ia/bootstrap")
        conversation = visitor.post("/api/ia/conversations", json={}).json()["conversation"]
        response = visitor.post(f"/api/ia/conversations/{conversation['id']}/messages",
                                json={"text": "Soy Pedro Díaz, pedro@example.test. Quiero reservar una cita."})
        assert "event: replace" in response.text
    gaps = app.state.learning.list(admin)["gaps"]
    assert [(gap["route"], gap["reason"]) for gap in gaps] == [("ia", "blocked")]
    stored = gaps[0]["question"]
    assert "Pedro" not in stored and "pedro@" not in stored and conversation["id"] not in str(gaps[0])


def test_ia_model_error_is_captured_and_the_reply_still_fails_cleanly(system, monkeypatch):
    app, admin, _ = system
    monkeypatch.setenv("REIGEL_CHAT_AI", "ollama")

    async def broken(history, incoming, verified="", reviewed=()):
        raise RuntimeError("sin modelo")
        yield ""  # pragma: no cover

    monkeypatch.setattr(ai_chat, "stream_workspace", broken)
    with TestClient(app) as visitor:
        visitor.get("/api/ia/bootstrap")
        conversation = visitor.post("/api/ia/conversations", json={}).json()["conversation"]
        response = visitor.post(f"/api/ia/conversations/{conversation['id']}/messages", json={"text": "¿Qué es un inversor?"})
        assert "event: error" in response.text
    assert app.state.learning.list(admin)["gaps"][0]["reason"] == "model_error"


def test_capture_failure_never_breaks_the_reply(system, monkeypatch):
    app, *_ = system
    monkeypatch.setenv("REIGEL_CHAT_AI", "ollama")

    async def fake_stream(history, incoming, verified="", reviewed=()):
        yield "Reservaste una cita."

    def explode(*_args, **_kwargs):
        raise RuntimeError("base ocupada")

    monkeypatch.setattr(ai_chat, "stream_workspace", fake_stream)
    monkeypatch.setattr(app.state.learning, "record_gap", explode)
    with TestClient(app) as visitor:
        visitor.get("/api/ia/bootstrap")
        conversation = visitor.post("/api/ia/conversations", json={}).json()["conversation"]
        response = visitor.post(f"/api/ia/conversations/{conversation['id']}/messages", json={"text": "Quiero una cita."})
        assert "event: replace" in response.text


def test_chat_fallback_is_captured_once(system):
    app, admin, _ = system
    with TestClient(app) as visitor:
        visitor.get("/api/public/chat")
        response = visitor.post("/api/public/chat", json={"text": "zxqv plorf", "request_id": "learning-fallback-1"})
        assert response.status_code == 200
    gaps = app.state.learning.list(admin)["gaps"]
    assert [(gap["route"], gap["reason"], gap["occurrences"]) for gap in gaps] == [("chat", "fallback", 1)]


def test_approved_answers_reach_the_model_as_reviewed_context(system, monkeypatch):
    app, admin, advisor = system
    monkeypatch.setenv("REIGEL_CHAT_AI", "ollama")
    queue = app.state.learning
    gap = queue.record_gap("ia", "blocked", ROOF)
    queue.approve(queue.propose(gap["id"], {"proposed_answer": GOOD_ANSWER, "source_note": "titular"}, advisor)["id"], admin)
    seen = []

    async def fake_stream(history, incoming, verified="", reviewed=()):
        seen.append(reviewed)
        yield "El equipo de Power Solar revisa la estructura del techo."

    monkeypatch.setattr(ai_chat, "stream_workspace", fake_stream)
    with TestClient(app) as visitor:
        visitor.get("/api/ia/bootstrap")
        conversation = visitor.post("/api/ia/conversations", json={}).json()["conversation"]
        visitor.post(f"/api/ia/conversations/{conversation['id']}/messages", json={"text": "Mi techo es de madera, ¿qué revisan?"})
    assert seen == [[{"question": gap["question"], "answer": GOOD_ANSWER}]]
    prompt = ai_chat.workspace_instructions("", seen[0])
    assert "Respuestas revisadas por el equipo de Power Solar" in prompt and GOOD_ANSWER in prompt


def test_admin_runs_the_bank_and_the_team_sees_the_latest_result(system, monkeypatch):
    app, admin, advisor = system
    monkeypatch.setenv("REIGEL_CHAT_AI", "ollama")

    async def available():
        return {"enabled": True, "status": "available", "local": True, "model": "test-model"}

    async def fake_bank(queue, knowledge=None, *, actor=None, progress=None):
        return queue.save_run(started_at="2026-11-25T12:00:00+00:00", model="test-model", route="ia",
                              results=[{"case_id": "techo_madera_baja_pendiente", "ok": True}], actor=actor)

    monkeypatch.setattr(ai_chat, "status", available)
    monkeypatch.setattr(learning_eval, "run_bank", fake_bank)
    with TestClient(app) as manager, TestClient(app) as adviser:
        login(manager, admin)
        login(adviser, advisor)
        assert adviser.get("/api/learning/eval").json()["latest"] is None
        started = manager.post("/api/learning/eval", json={})
        assert started.status_code == 202
        for _ in range(50):
            state = adviser.get("/api/learning/eval").json()
            if state["latest"] and not state["running"]:
                break
            time.sleep(0.05)
        assert state["latest"]["summary"] == "1 de 1 casos pasan." and state["can_run"] is False
        assert state["latest"]["created_by"] == admin["id"]
        codes = [manager.post("/api/learning/eval", json={}).status_code for _ in range(5)]
        assert 429 in codes


def test_bank_refuses_to_run_without_an_available_local_model(system, monkeypatch):
    app, admin, _ = system
    with TestClient(app) as manager:
        login(manager, admin)
        assert manager.post("/api/learning/eval", json={}).status_code == 503
