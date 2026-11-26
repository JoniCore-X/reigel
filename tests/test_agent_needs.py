"""The need report: what the team receives when the chat cannot answer. Built from
rules, never from the model, because it is needed exactly when the model failed."""
import pytest
from fastapi.testclient import TestClient

from reigel.agent import needs
from reigel.api import create_app
from reigel.core import DomainError
from team_auth import allow, login as team_login

PASSWORD = "synthetic-password-needs"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.delenv("REIGEL_CHAT_AI", raising=False)
    app = create_app(tmp_path / "needs.db")
    store = app.state.store
    admin = store.create_user(
        {"name": "QA Admin", "email": "needs-admin@example.test", "password": PASSWORD, "role": "admin"},
        bootstrap=True)
    allow(store, admin, "needs-a@example.test", "needs-b@example.test")
    first = store.create_user(
        {"name": "QA Asesora", "email": "needs-a@example.test", "password": PASSWORD, "role": "advisor"}, admin)
    second = store.create_user(
        {"name": "QA Asesor", "email": "needs-b@example.test", "password": PASSWORD, "role": "advisor"}, admin)
    return app, store, admin, first, second


def login(client, person):
    assert team_login(client, person["email"], PASSWORD).status_code == 200


def conversation(store, advisor_id=None):
    from reigel.core import stamp, uid
    conversation_id = uid()
    with store.connect() as db:
        db.execute("INSERT INTO conversations(id,channel,external_id,contact_name,lead_id,advisor_id,mode,updated_at)"
                   " VALUES(?,'web',?,'Visitante',NULL,?,'ai',?)",
                   (conversation_id, uid(), advisor_id, stamp()))
    return conversation_id


def test_the_report_says_what_the_person_needs_not_only_that_someone_is_waiting():
    report = needs.build("no_knowledge", "Se me va la luz seguido y no sé si esto me sirve",
                         profile={"municipality": "Caguas", "priority": "apagones"})
    assert report["topic"] == "apagon"
    assert report["need"] == "Le preocupan las interrupciones del servicio."
    assert report["reason"] == "no_knowledge"
    assert {item["label"] for item in report["known"]} == {"Municipio", "Qué busca resolver"}
    assert "Importe de la factura" in report["missing"]


def test_the_question_is_stored_already_masked():
    report = needs.build("fallback", "Escríbeme a persona@example.test o al 787-555-0100, vivo en la calle Luna 5")
    assert "persona@example.test" not in report["question"]
    assert "555" not in report["question"]
    assert "omitid" in report["question"]


def test_whoever_asks_for_a_person_is_not_filed_as_an_unclassified_doubt():
    plain = needs.build("human_requested", "Quiero hablar con una persona")
    assert plain["need"] == "Pidió hablar con una persona del equipo."
    with_topic = needs.build("human_requested", "Quiero hablar con alguien, se me va la luz a cada rato")
    assert with_topic["need"] == ("Pidió hablar con una persona del equipo."
                                  " Le preocupan las interrupciones del servicio.")


def test_asking_for_a_person_or_being_blocked_is_urgent():
    assert needs.build("human_requested", "Quiero hablar con alguien")["urgency"] == "high"
    assert needs.build("blocked_by_policy", "¿Cuánto me va a costar?")["urgency"] == "high"
    assert needs.build("model_unavailable", "Tengo una duda")["urgency"] == "low"
    assert needs.build("fallback", "Tengo una duda")["urgency"] == "normal"


def test_a_visitor_already_asking_for_the_next_step_is_treated_as_urgent():
    calm = needs.build("fallback", "Tengo una duda sobre el techo")
    ready = needs.build("fallback", "Tengo una duda sobre el techo", asked_next_step=True)
    assert calm["urgency"] == "normal" and ready["urgency"] == "high"


def test_the_everyday_puerto_rican_phrasing_is_recognised():
    """«se me va la luz» es como se dice aquí; el patrón solo cubría «se va la luz»."""
    for phrase in ("Se me va la luz a cada rato", "se nos fue la luz otra vez", "se va la luz"):
        assert needs.build("fallback", phrase)["topic"] == "apagon", phrase


def test_when_several_topics_match_the_more_relevant_one_wins():
    """`learning.topic_of` ordena por relevancia comercial; el techo (1,0) pesa más que
    el apagón (0,9). Con empate gana el tema declarado antes en `suggestions.TOPICS`."""
    roof = needs.build("fallback", "Se me va la luz y no sé si el techo aguanta")
    assert roof["topic"] == "techo"
    assert roof["need"] == "Su duda gira sobre el techo y dónde irían los equipos."
    tie = needs.build("fallback", "Se me va la luz y quiero baterías")
    assert tie["topic"] == "apagon"


def test_an_unknown_reason_or_route_is_refused():
    with pytest.raises(DomainError):
        needs.build("porque_si", "Hola")
    with pytest.raises(DomainError):
        needs.build("fallback", "Hola", route="telepatia")
    with pytest.raises(DomainError):
        needs.build("fallback", "")


def test_repeating_the_same_topic_raises_the_urgency_instead_of_piling_reports(workspace):
    app, store, admin, first, second = workspace
    thread = conversation(store)
    first_report = needs.record(store, thread, needs.build("fallback", "¿El techo aguanta?"))
    assert first_report["urgency"] == "normal" and first_report["repeats"] == 1
    again = needs.record(store, thread, needs.build("fallback", "Insisto, ¿y el techo?"))
    assert again["id"] == first_report["id"]
    assert again["repeats"] == 2 and again["urgency"] == "high"
    assert len(needs.listed(store, admin)["reports"]) == 1


def test_a_different_topic_in_the_same_conversation_gets_its_own_report(workspace):
    app, store, admin, first, second = workspace
    thread = conversation(store)
    needs.record(store, thread, needs.build("fallback", "¿El techo aguanta?"))
    needs.record(store, thread, needs.build("fallback", "¿Y si se va la luz?"))
    topics = {report["topic"] for report in needs.listed(store, admin)["reports"]}
    assert topics == {"techo", "apagon"}


def test_the_queue_puts_the_urgent_ones_first(workspace):
    app, store, admin, first, second = workspace
    needs.record(store, conversation(store), needs.build("model_unavailable", "Una duda cualquiera"))
    needs.record(store, conversation(store), needs.build("fallback", "¿Y el inversor?"))
    needs.record(store, conversation(store), needs.build("human_requested", "Quiero hablar con alguien"))
    order = [report["urgency"] for report in needs.listed(store, admin)["reports"]]
    assert order == ["high", "normal", "low"]


def test_an_advisor_sees_the_unclaimed_ones_and_not_another_advisor_s(workspace):
    app, store, admin, first, second = workspace
    free = needs.record(store, conversation(store), needs.build("fallback", "¿El techo aguanta?"))
    mine = needs.record(store, conversation(store, first["id"]), needs.build("fallback", "¿Y el inversor?"))
    hers = needs.record(store, conversation(store, second["id"]), needs.build("fallback", "¿Y la medición?"))
    seen = {report["id"] for report in needs.listed(store, first)["reports"]}
    assert seen == {free["id"], mine["id"]}
    assert len(needs.listed(store, admin)["reports"]) == 3
    assert hers["id"] not in seen


def test_claiming_and_closing_a_report_leaves_the_trail(workspace):
    app, store, admin, first, second = workspace
    report = needs.record(store, conversation(store), needs.build("human_requested", "Quiero hablar con alguien"))
    claimed = needs.claim(store, report["id"], first)
    assert claimed["status"] == "claimed" and claimed["owner_id"] == first["id"]
    with pytest.raises(DomainError):
        needs.claim(store, report["id"], second)
    closed = needs.resolve(store, report["id"], {"resolution": "La llamé y coordinamos una orientación."}, first)
    assert closed["status"] == "resolved" and closed["resolution"].startswith("La llamé")
    assert needs.listed(store, admin)["reports"] == []
    with pytest.raises(DomainError):
        needs.resolve(store, report["id"], {"resolution": "otra vez"}, first)
    with store.connect() as db:
        actions = [row["action"] for row in db.execute("SELECT action FROM audit_events")]
    for expected in ("agent.need.record", "agent.need.claim", "agent.need.resolve"):
        assert expected in actions


def test_closing_needs_a_written_outcome(workspace):
    app, store, admin, first, second = workspace
    report = needs.record(store, conversation(store), needs.build("fallback", "¿El techo aguanta?"))
    with pytest.raises(DomainError):
        needs.resolve(store, report["id"], {}, admin)


def test_a_real_chat_that_cannot_answer_leaves_a_report(workspace):
    """End to end over HTTP: the visitor writes, the engine has no answer and the team
    receives what that person needs."""
    app, store, admin, first, second = workspace
    with TestClient(app) as visitor, TestClient(app) as manager:
        login(manager, admin)
        visitor.get("/api/public/chat")
        answer = visitor.post("/api/public/chat", json={
            "text": "Se me va la luz a cada rato y no sé si esto me sirve",
            "request_id": "need-chat-001"})
        assert answer.status_code == 200
        queue = manager.get("/api/needs").json()
        assert len(queue["reports"]) == 1, queue
        report = queue["reports"][0]
        assert report["route"] == "chat" and report["topic"] == "apagon"
        assert report["need"] == "Le preocupan las interrupciones del servicio."
        assert report["question"] and report["status"] == "open"
        assert "no lo redacta el modelo" in queue["notice"].lower() or "No lo redacta el modelo" in queue["notice"]


def test_asking_for_a_person_in_the_chat_reaches_the_queue_as_urgent(workspace):
    app, store, admin, first, second = workspace
    with TestClient(app) as visitor, TestClient(app) as manager:
        login(manager, admin)
        visitor.get("/api/public/chat")
        visitor.post("/api/public/chat", json={"text": "Quiero hablar con una persona",
                                               "request_id": "need-chat-002"})
        reports = manager.get("/api/needs").json()["reports"]
        assert [report["reason"] for report in reports] == ["human_requested"]
        assert reports[0]["urgency"] == "high"


def test_the_queue_travels_over_http_with_its_permissions(workspace):
    app, store, admin, first, second = workspace
    report = needs.record(store, conversation(store), needs.build("fallback", "¿El techo aguanta?"))
    with TestClient(app) as helper, TestClient(app) as other:
        login(helper, first)
        login(other, second)
        assert helper.post(f"/api/needs/{report['id']}/claim").json()["report"]["status"] == "claimed"
        assert other.post(f"/api/needs/{report['id']}/claim").status_code == 403
        assert other.post(f"/api/needs/{report['id']}/resolve",
                          json={"resolution": "Intento ajeno"}).status_code == 403
        assert helper.post(f"/api/needs/{report['id']}/resolve",
                           json={"resolution": "Contestada por teléfono."}).status_code == 200
        assert helper.get("/api/needs").json()["reports"] == []
