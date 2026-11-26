"""Call preparation and closing. The system never dials: it prepares the sheet, states
with what permission, and takes the outcome back. 'Do not call' beats everything after it."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from reigel.agent import calls, memory, needs
from reigel.api import create_app
from reigel.core import DomainError
from team_auth import allow, login as team_login

PASSWORD = "synthetic-password-calls"
NOW = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "calls.db")
    store = app.state.store
    admin = store.create_user(
        {"name": "QA Admin", "email": "calls-admin@example.test", "password": PASSWORD, "role": "admin"},
        bootstrap=True)
    allow(store, admin, "calls-a@example.test", "calls-b@example.test")
    advisor = store.create_user(
        {"name": "QA Asesora", "email": "calls-a@example.test", "password": PASSWORD, "role": "advisor"}, admin)
    other = store.create_user(
        {"name": "QA Asesor", "email": "calls-b@example.test", "password": PASSWORD, "role": "advisor"}, admin)
    store.update_user(advisor["id"], {"public_booking": True, "work_days": list(range(7))}, admin)
    lead = store.create_lead(
        {"name": "Prospecto sintético", "phone": "+17875550100", "consent": True,
         "municipality": "Caguas", "advisor_id": advisor["id"]}, admin)
    return app, store, admin, advisor, other, lead


def login(client, person):
    assert team_login(client, person["email"], PASSWORD).status_code == 200


def test_the_plan_says_the_system_does_not_dial(workspace):
    app, store, admin, advisor, other, lead = workspace
    sheet = calls.plan(store, lead["id"], advisor)
    assert "no marca" in sheet["notice"] and "una persona" in sheet["notice"]
    assert sheet["phone_on_file"] is True


def test_a_ticked_box_in_the_crm_is_not_written_consent(workspace):
    app, store, admin, advisor, other, lead = workspace
    allowed = calls.permission(store, lead["id"], advisor)
    assert allowed["allowed"] is True and allowed["basis"] == "lead_consent"
    assert "no una constancia específica" in allowed["notice"]
    recorded = calls.record_consent(
        store, lead["id"], {"kind": "written", "evidence": "Firmó la autorización en la visita."}, advisor)
    assert recorded["allowed"] is True and recorded["basis"] == "written"
    assert recorded["basis_label"] == "Autorización escrita"


def test_a_record_without_consent_is_not_callable(workspace):
    app, store, admin, advisor, other, lead = workspace
    silent = store.create_lead({"name": "Sin permiso", "phone": "+17875550199", "consent": False,
                                "advisor_id": advisor["id"]}, admin)
    verdict = calls.permission(store, silent["id"], advisor)
    assert verdict["allowed"] is False and verdict["basis"] == "none"
    assert calls.plan(store, silent["id"], advisor)["permission"]["allowed"] is False


def test_do_not_call_beats_an_earlier_written_consent(workspace):
    app, store, admin, advisor, other, lead = workspace
    calls.record_consent(store, lead["id"], {"kind": "written", "evidence": "Firmada en la visita."},
                         advisor, now=NOW - timedelta(days=2))
    refused = calls.record_consent(store, lead["id"], {"kind": "do_not_call", "evidence": "Lo pidió por teléfono."},
                                   advisor, now=NOW)
    assert refused["allowed"] is False and refused["basis"] == "do_not_call"
    assert "No la llames" in refused["notice"]
    assert len(refused["history"]) == 2, "la constancia anterior no se borra"
    assert calls.plan(store, lead["id"], advisor)["permission"]["allowed"] is False


def test_consent_can_be_given_again_after_a_refusal_and_the_latest_wins(workspace):
    app, store, admin, advisor, other, lead = workspace
    calls.record_consent(store, lead["id"], {"kind": "do_not_call", "evidence": "No quiere llamadas."},
                         advisor, now=NOW - timedelta(days=30))
    again = calls.record_consent(store, lead["id"], {"kind": "written", "evidence": "Volvió y autorizó por escrito."},
                                 advisor, now=NOW)
    assert again["allowed"] is True and again["basis"] == "written"


def test_the_kind_of_evidence_is_checked(workspace):
    app, store, admin, advisor, other, lead = workspace
    for broken in ({"kind": "telepatia", "evidence": "nada"}, {"kind": "written", "evidence": ""},
                   {"kind": "written"}, {"kind": "written", "evidence": "x", "extra": 1}):
        with pytest.raises(DomainError):
            calls.record_consent(store, lead["id"], broken, advisor)


def test_the_plan_pulls_together_the_record_the_memory_and_the_open_needs(workspace):
    app, store, admin, advisor, other, lead = workspace
    memory.record(store, lead["id"], {"subject": "motivo", "claim": "Le preocupan las interrupciones.",
                                      "source_kind": "lead_said", "confidence": 0.9}, advisor)
    memory.record(store, lead["id"], {"subject": "decisor", "claim": "Parece que decide su hija.",
                                      "source_kind": "inferred", "confidence": 0.3}, advisor)
    from reigel.core import stamp, uid
    conversation_id = uid()
    with store.connect() as db:
        db.execute("INSERT INTO conversations(id,channel,external_id,contact_name,lead_id,advisor_id,mode,updated_at)"
                   " VALUES(?,'web',?,'Visitante',?,?,'human',?)",
                   (conversation_id, uid(), lead["id"], advisor["id"], stamp()))
    needs.record(store, conversation_id, needs.build("fallback", "¿El techo aguanta las placas?"),
                 lead_id=lead["id"])
    sheet = calls.plan(store, lead["id"], advisor)
    assert [item["claim"] for item in sheet["remembered"]] == ["Le preocupan las interrupciones."], \
        "una deducción sin aprobar no entra en la hoja"
    assert sheet["open_needs"] and "techo" in sheet["open_needs"][0]["question"]
    assert any("techo" in line for line in sheet["confirm"])
    assert "Municipio" in [item["label"] for item in sheet["known"]]
    assert "Importe de la factura" in sheet["ask"]


def test_values_travel_as_stored_so_the_screen_gives_them_format(workspace):
    """La hoja no formatea: el importe viaja como número y la cita como instante."""
    app, store, admin, advisor, other, lead = workspace
    with store.connect() as db:
        db.execute("UPDATE leads SET monthly_bill=180 WHERE id=?", (lead["id"],))
    sheet = calls.plan(store, lead["id"], advisor)
    bill = next(item for item in sheet["known"] if item["label"] == "Importe de la factura")
    assert bill["value"] == 180 and bill["kind"] == "currency"
    assert sheet["appointment_at"] is None
    slot = store.slots(advisor["id"], (NOW + timedelta(days=2)).date().isoformat())["slots"][0]
    store.book({"lead_id": lead["id"], "advisor_id": advisor["id"],
                "start_at": slot["start_at"]}, source="app", actor=admin)
    booked = calls.plan(store, lead["id"], advisor)
    # La agenda ofrece la hora de Puerto Rico y el instante se guarda en UTC: es el
    # mismo momento escrito de dos maneras, así que se comparan instantes.
    assert datetime.fromisoformat(booked["appointment_at"]) == datetime.fromisoformat(slot["start_at"])
    assert not any("T" in line and "+00:00" in line for line in booked["confirm"]), \
        "ninguna fecha cruda se cuela en el texto"


def test_the_purpose_follows_the_stage(workspace):
    app, store, admin, advisor, other, lead = workspace
    assert "Presentarse" in calls.plan(store, lead["id"], advisor)["purpose"]
    with store.connect() as db:
        db.execute("UPDATE leads SET stage='negociacion' WHERE id=?", (lead["id"],))
    assert "quién más participa" in calls.plan(store, lead["id"], advisor)["purpose"]


def test_the_sheet_always_carries_what_must_not_be_said(workspace):
    app, store, admin, advisor, other, lead = workspace
    forbidden = " ".join(calls.plan(store, lead["id"], advisor)["never_say"]).lower()
    for word in ("precio", "ahorro", "financia", "garantía", "plazo"):
        assert word in forbidden


def test_closing_a_call_records_the_activity_and_the_next_step(workspace):
    app, store, admin, advisor, other, lead = workspace
    later = (NOW + timedelta(days=3)).isoformat()
    closed = calls.record_outcome(store, lead["id"], {
        "result": "reached", "notes": "Quedó en revisar su factura y hablar el jueves.",
        "next_followup_at": later}, advisor)
    assert closed["result_label"] == "Habló con la persona"
    assert closed["activity"]["type"] == "call"
    assert "Quedó en revisar" in closed["activity"]["outcome"]
    updated = store.get_lead(lead["id"], advisor)
    assert updated["next_followup_at"] == later
    assert updated["last_contact_at"], "cerrar una llamada cuenta como contacto"


def test_closing_with_do_not_call_blocks_the_next_call(workspace):
    app, store, admin, advisor, other, lead = workspace
    closed = calls.record_outcome(store, lead["id"], {
        "result": "do_not_call", "notes": "Pidió que no la llamemos más."}, advisor)
    assert closed["permission"]["allowed"] is False
    assert closed["permission"]["basis"] == "do_not_call"
    assert calls.plan(store, lead["id"], advisor)["permission"]["allowed"] is False


def test_the_outcome_is_checked_before_anything_is_written(workspace):
    app, store, admin, advisor, other, lead = workspace
    for broken in ({"result": "colgaron", "notes": "x"}, {"result": "reached"},
                   {"result": "reached", "notes": ""}, {"notes": "x"}):
        with pytest.raises(DomainError):
            calls.record_outcome(store, lead["id"], broken, advisor)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) c FROM lead_activities").fetchone()["c"] == 0


def test_an_advisor_cannot_prepare_or_close_a_call_of_someone_else_s_lead(workspace):
    app, store, admin, advisor, other, lead = workspace
    for action in (lambda: calls.plan(store, lead["id"], other),
                   lambda: calls.permission(store, lead["id"], other),
                   lambda: calls.record_consent(store, lead["id"], {"kind": "verbal", "evidence": "ajeno"}, other),
                   lambda: calls.record_outcome(store, lead["id"], {"result": "reached", "notes": "ajeno"}, other)):
        with pytest.raises(DomainError):
            action()


def test_the_whole_thing_travels_over_http(workspace):
    app, store, admin, advisor, other, lead = workspace
    with TestClient(app) as client, TestClient(app) as outsider:
        login(client, advisor)
        login(outsider, other)
        sheet = client.get(f"/api/leads/{lead['id']}/call-plan").json()
        assert sheet["permission"]["basis"] == "lead_consent"
        assert sheet["never_say"] and sheet["purpose"]

        recorded = client.post(f"/api/leads/{lead['id']}/call-consent",
                               json={"kind": "verbal", "evidence": "Lo autorizó en la llamada anterior."})
        assert recorded.status_code == 201
        assert recorded.json()["permission"]["basis"] == "verbal"

        closed = client.post(f"/api/leads/{lead['id']}/call-outcome",
                             json={"result": "voicemail", "notes": "Dejé constancia interna, sin mensaje grabado."})
        assert closed.status_code == 201 and closed.json()["result"] == "voicemail"

        assert outsider.get(f"/api/leads/{lead['id']}/call-plan").status_code == 404
        assert outsider.post(f"/api/leads/{lead['id']}/call-outcome",
                             json={"result": "reached", "notes": "ajeno"}).status_code == 404
        assert client.post(f"/api/leads/{lead['id']}/call-outcome",
                           json={"result": "inventado", "notes": "x"}).status_code == 422


def test_every_step_leaves_an_audit_entry(workspace):
    app, store, admin, advisor, other, lead = workspace
    calls.record_consent(store, lead["id"], {"kind": "written", "evidence": "Firmada."}, advisor)
    calls.record_outcome(store, lead["id"], {"result": "no_answer", "notes": "No contestó."}, advisor)
    with store.connect() as db:
        actions = [row["action"] for row in db.execute("SELECT action FROM audit_events")]
    assert "agent.call.consent" in actions and "agent.call.outcome" in actions
