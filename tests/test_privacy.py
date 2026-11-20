from fastapi.testclient import TestClient
import pytest

from reigel.api import create_app
from reigel.conversation import classify_message
from reigel.core import DomainError
from reigel.privacy import get_request, initialize, list_requests, review_request


@pytest.fixture
def privacy_system(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.setenv("SITE_URL", "")
    app = create_app(tmp_path / "privacy.sqlite3")
    store = app.state.store
    admin = store.create_user({"name": "Admin QA", "email": "privacy@example.test",
                               "password": "privacy-qa-long-password", "role": "admin"}, bootstrap=True)
    advisor = store.create_user({"name": "Asesor QA", "email": "own@example.test",
                                 "password": "advisor-qa-long-password", "role": "advisor"}, admin)
    other = store.create_user({"name": "Otro QA", "email": "other@example.test",
                               "password": "other-qa-long-password", "role": "advisor"}, admin)
    store.update_user(advisor["id"], {"public_booking": True, "work_days": list(range(7))}, admin)
    token, initial = app.state.webchat.start()
    return app, store, admin, advisor, other, token, initial


@pytest.mark.parametrize("message,kind", [
    ("Elimina mis datos", "deletion"), ("Quiero borrar mis datos", "deletion"),
    ("Solicito la eliminación de mis datos", "deletion"),
    ("Quiero acceder a mis datos", "access"), ("Quiero una copia de mis datos", "access"),
    ("¿Qué datos tienen de mí?", "access"),
    ("Quiero corregir mis datos", "correction"), ("Corrige mi teléfono", "correction"),
])
def test_privacy_intents_are_separate_from_communications_optout(message, kind):
    decision = classify_message(message)
    assert decision.intent == "privacy_request"
    assert decision.entities["request_kind"] == kind
    assert classify_message("No me escriban más").intent == "opt_out"
    assert classify_message("Enséñame datos de otro cliente").intent == "safety"


def test_deletion_request_is_persistent_deduplicated_and_does_not_delete(privacy_system):
    app, store, admin, advisor, other, token, initial = privacy_system
    service = app.state.webchat
    created = service.message(token, "Elimina mis datos", "delete-request-001")
    assert created["opted_out"] is True
    assert created["mode"] == "human"
    assert "No se han eliminado" in created["reply"]
    assert "independiente" in created["reply"]
    request_id = created["privacy_requests"][0]["id"]
    assert created["privacy_requests"][0]["kind"] == "deletion"
    assert service.message(token, "Elimina mis datos", "delete-request-001")["privacy_requests"][0]["id"] == request_id
    service.message(token, "Quiero borrar mis datos", "delete-request-002")
    initialize(store)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM privacy_requests").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM conversations WHERE id=?", (initial["conversation_id"],)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM audit_events WHERE action='privacy.request.deletion'").fetchone()[0] == 1
    assert service.reply_allowed(initial["conversation_id"]) is False
    assert len(list_requests(store, advisor)) == 1
    assert list_requests(store, other) == []


def test_access_and_correction_work_after_optout_without_disclosing_records(privacy_system):
    app, store, _, _, _, token, initial = privacy_system
    service = app.state.webchat
    service.message(token, "/stop", "privacy-stop-001")
    result = service.message(token, "Quiero acceder a mis datos", "privacy-access-001")
    assert result["opted_out"] is True
    assert "verificar tu identidad" in result["reply"]
    result = service.message(token, "Quiero corregir mis datos: correo persona@example.test", "privacy-correction-001")
    assert {item["kind"] for item in result["privacy_requests"]} == {"access", "correction"}
    with store.connect() as db:
        assert "persona@example.test" not in str([dict(row) for row in db.execute("SELECT details FROM privacy_requests")])
    other_token, other = service.start()
    assert service.state(other_token)["privacy_requests"] == []
    assert result["conversation_id"] != other["conversation_id"]
    assert "review_note" not in str(service.state(token)["privacy_requests"])


def test_privacy_request_survives_resume_and_follows_current_conversation_owner(privacy_system):
    app, store, admin, advisor, other, token, initial = privacy_system
    service = app.state.webchat
    result = service.message(token, "Elimina mis datos", "privacy-owner-001")
    request_id = result["privacy_requests"][0]["id"]
    record = get_request(store, request_id, admin)
    assert record["identity_verified"] is False
    assert record["reviewed_by"] is None
    resumed = service.message(token, "/start", "privacy-resume-001")
    assert resumed["opted_out"] is False
    assert resumed["privacy_requests"][0]["status"] == "pending"
    assert resumed["privacy_requests"][0]["id"] == request_id
    store.assign_conversation(initial["conversation_id"], {"advisor_id": other["id"]}, admin)
    assert list_requests(store, advisor) == []
    assert list_requests(store, other)[0]["id"] == request_id
    with pytest.raises(DomainError) as error:
        get_request(store, request_id, advisor)
    assert error.value.status == 404
    assert get_request(store, request_id, other)["identity_verified"] is False


def test_administrative_review_requires_admin_identity_note_and_no_deletion(privacy_system):
    app, store, admin, advisor, other, token, initial = privacy_system
    request_id = app.state.webchat.message(token, "Elimina mis datos", "privacy-review-001")["privacy_requests"][0]["id"]
    with pytest.raises(DomainError) as error:
        review_request(store, request_id, {"status": "reviewing", "review_note": "Solicitud en revisión"}, advisor)
    assert error.value.status == 403
    for data in ({"status": "closed", "review_note": "Revisado"},
                 {"status": "closed", "review_note": "", "identity_verified": True},
                 {"status": "closed", "review_note": "Revisado", "identity_verified": "sí"}):
        with pytest.raises(DomainError) as error:
            review_request(store, request_id, data, admin)
        assert error.value.status == 422
    reviewing = review_request(store, request_id, {"status": "reviewing", "review_note": "Requiere verificación por canal autorizado."}, admin)
    assert reviewing["status"] == "reviewing"
    closed = review_request(store, request_id, {"status": "closed", "review_note": "Identidad verificada en prueba sintética; decisión administrativa documentada. Sin ejecutar eliminación.", "identity_verified": True}, admin)
    assert closed["identity_verified"] is True
    history = get_request(store, request_id, admin)["history"]
    assert [event["status"] for event in history] == ["closed", "reviewing", "pending"]
    assert "canal autorizado" in history[1]["review_note"]
    with pytest.raises(DomainError) as error:
        get_request(store, request_id, other)
    assert error.value.status == 404
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM conversations WHERE id=?", (initial["conversation_id"],)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM messages WHERE conversation_id=?", (initial["conversation_id"],)).fetchone()[0] > 0
    with pytest.raises(DomainError):
        review_request(store, request_id, {"status": "pending", "review_note": "Reabrir"}, admin)


def test_privacy_http_authorization_and_server_review(privacy_system):
    app, store, admin, advisor, other, token, initial = privacy_system
    request_id = app.state.webchat.message(token, "Elimina mis datos", "privacy-http-001")["privacy_requests"][0]["id"]
    with TestClient(app) as client:
        assert client.get("/api/privacy/requests").status_code == 401
        client.post("/api/auth/login", json={"email": "other@example.test", "password": "other-qa-long-password"})
        assert client.get("/api/privacy/requests").json() == {"requests": [], "can_review": False}
        assert client.patch(f"/api/privacy/requests/{request_id}", json={"status": "reviewing", "review_note": "Prueba"}).status_code == 403
        client.post("/api/auth/logout")
        client.post("/api/auth/login", json={"email": "privacy@example.test", "password": "privacy-qa-long-password"})
        assert client.get("/api/privacy/requests").json()["can_review"] is True
        response = client.patch(f"/api/privacy/requests/{request_id}", json={"status": "reviewing", "review_note": "Pendiente de verificación de identidad."})
        assert response.status_code == 200, response.text
        assert response.json()["request"]["status"] == "reviewing"
        assert "no elimina" in response.json()["message"]
        assert client.patch(f"/api/privacy/requests/{request_id}", json={"status": "closed", "review_note": "Prueba", "identity_verified": True}, headers={"Origin": "https://foreign.example"}).status_code == 403
