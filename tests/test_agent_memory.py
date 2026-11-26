"""The agent's memory: provenance, expiry, supersession, and the single gate that
decides what may reach a customer. Nothing here is ever overwritten."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from reigel.agent import memory
from reigel.api import create_app
from reigel.core import DomainError
from team_auth import allow, login as team_login

NOW = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
PASSWORD = "synthetic-password-memory"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "memory.db")
    store = app.state.store
    admin = store.create_user(
        {"name": "QA Admin", "email": "memory-admin@example.test", "password": PASSWORD, "role": "admin"},
        bootstrap=True)
    allow(store, admin, "memory-a@example.test", "memory-b@example.test")
    first = store.create_user(
        {"name": "QA Asesora", "email": "memory-a@example.test", "password": PASSWORD, "role": "advisor"}, admin)
    second = store.create_user(
        {"name": "QA Asesor", "email": "memory-b@example.test", "password": PASSWORD, "role": "advisor"}, admin)
    prospect = store.create_lead(
        {"name": "Prospecto sintético", "phone": "+17875550100", "consent": True,
         "advisor_id": first["id"]}, admin)
    return app, store, admin, first, second, prospect


def remember(store, lead_id, actor, *, now=None, **data):
    base = {"subject": "vivienda", "claim": "Vive en una casa de dos niveles.",
            "source_kind": "lead_said", "confidence": 0.9}
    return memory.record(store, lead_id, {**base, **data}, actor, now=now or NOW)


def login(client, person):
    assert team_login(client, person["email"], PASSWORD).status_code == 200


def test_a_belief_records_where_it_came_from_and_when_it_expires(workspace):
    app, store, admin, first, second, prospect = workspace
    belief = remember(store, prospect["id"], admin)
    assert belief["source_kind"] == "lead_said" and belief["source_label"] == "La persona lo dijo"
    assert belief["state"] == "active" and belief["usable"] is True
    assert belief["observed_at"] == NOW.isoformat()
    # 180 días para lo que dijo la persona: lo que alguien contó hace ocho meses ya no es un hecho.
    assert belief["expires_at"] == (NOW + timedelta(days=180)).isoformat()


def test_a_model_guess_is_remembered_but_never_used_until_a_person_approves_it(workspace):
    app, store, admin, first, second, prospect = workspace
    guess = remember(store, prospect["id"], admin, source_kind="inferred",
                     claim="Parece que decide con su pareja.", subject="decisor", confidence=0.4)
    assert guess["state"] == "active", "la deducción se recuerda"
    assert guess["usable"] is False, "pero no se usa al hablar"
    assert memory.speaking_context(store, prospect["id"], now=NOW) == []
    approved = memory.approve(store, guess["id"], first, now=NOW)
    assert approved["usable"] is True and approved["approved_by"] == first["id"]
    assert [item["claim"] for item in memory.speaking_context(store, prospect["id"], now=NOW)] == [
        "Parece que decide con su pareja."]


def test_a_revision_never_overwrites_the_earlier_belief(workspace):
    app, store, admin, first, second, prospect = workspace
    old = remember(store, prospect["id"], admin, claim="Vive en un apartamento.")
    new = remember(store, prospect["id"], admin, claim="Se mudó a una casa.")
    stored = memory.history(store, prospect["id"], admin, now=NOW)["beliefs"]
    assert len(stored) == 2
    current = next(item for item in stored if item["id"] == new["id"])
    previous = next(item for item in stored if item["id"] == old["id"])
    assert current["state"] == "active" and current["supersedes"] == old["id"]
    assert previous["state"] == "superseded" and previous["superseded_by"] == new["id"]
    assert previous["claim"] == "Vive en un apartamento.", "lo anterior sigue legible"
    assert [item["claim"] for item in memory.speaking_context(store, prospect["id"], now=NOW)] == [
        "Se mudó a una casa."]


def test_two_subjects_live_side_by_side(workspace):
    app, store, admin, first, second, prospect = workspace
    remember(store, prospect["id"], admin, subject="vivienda", claim="Casa de dos niveles.")
    remember(store, prospect["id"], admin, subject="motivo", claim="Le preocupan las interrupciones.")
    claims = {item["claim"] for item in memory.speaking_context(store, prospect["id"], now=NOW)}
    assert claims == {"Casa de dos niveles.", "Le preocupan las interrupciones."}


def test_an_expired_belief_stays_readable_but_stops_being_used(workspace):
    app, store, admin, first, second, prospect = workspace
    belief = remember(store, prospect["id"], admin)
    later = NOW + timedelta(days=181)
    stored = memory.history(store, prospect["id"], admin, now=later)["beliefs"][0]
    assert stored["state"] == "expired" and stored["usable"] is False
    assert stored["claim"] == belief["claim"]
    assert memory.speaking_context(store, prospect["id"], now=later) == []


def test_each_provenance_brings_its_own_shelf_life(workspace):
    app, store, admin, first, second, prospect = workspace
    for source, days in (("lead_said", 180), ("team_entered", 365), ("record", 90),
                         ("verified", 30), ("inferred", 30)):
        belief = remember(store, prospect["id"], admin, source_kind=source, subject="otro")
        assert belief["expires_at"] == (NOW + timedelta(days=days)).isoformat(), source


def test_a_retracted_belief_is_not_deleted_and_does_not_block_a_new_one(workspace):
    app, store, admin, first, second, prospect = workspace
    belief = remember(store, prospect["id"], admin)
    retracted = memory.retract(store, belief["id"], {"reason": "Se registró en el prospecto equivocado."},
                               first, now=NOW)
    assert retracted["state"] == "retracted" and retracted["usable"] is False
    assert retracted["retracted_reason"] == "Se registró en el prospecto equivocado."
    assert retracted["superseded_by"] is None, "retirar no es corregir"
    assert memory.speaking_context(store, prospect["id"], now=NOW) == []
    fresh = remember(store, prospect["id"], admin, claim="Vive en una casa de un nivel.")
    assert fresh["supersedes"] is None
    assert len(memory.history(store, prospect["id"], admin, now=NOW)["beliefs"]) == 2
    with pytest.raises(DomainError):
        memory.retract(store, belief["id"], {"reason": "otra vez"}, first, now=NOW)


def test_a_belief_needs_a_known_subject_a_known_source_and_a_real_confidence(workspace):
    app, store, admin, first, second, prospect = workspace
    for broken in ({"subject": "inventado"}, {"source_kind": "intuicion"}, {"confidence": 0},
                   {"confidence": 1.5}, {"confidence": "mucha"}, {"claim": ""},
                   {"usable": True}, {"expires_at": "2099-01-01T00:00:00+00:00"},
                   {"approved_at": "2026-01-01T00:00:00+00:00"}):
        with pytest.raises(DomainError):
            remember(store, prospect["id"], admin, **broken)


def test_an_advisor_cannot_reach_the_memory_of_someone_else_s_lead(workspace):
    app, store, admin, first, second, prospect = workspace
    belief = remember(store, prospect["id"], admin)
    with pytest.raises(DomainError):
        memory.history(store, prospect["id"], second, now=NOW)
    with pytest.raises(DomainError):
        memory.record(store, prospect["id"], {"subject": "otro", "claim": "Intento ajeno.",
                                              "source_kind": "team_entered"}, second, now=NOW)
    with pytest.raises(DomainError):
        memory.approve(store, belief["id"], second, now=NOW)
    assert memory.history(store, prospect["id"], first, now=NOW)["beliefs"][0]["id"] == belief["id"]


def test_the_claim_is_stored_as_written_even_when_it_carries_markup(workspace):
    app, store, admin, first, second, prospect = workspace
    belief = remember(store, prospect["id"], admin, claim="<script>alert(1)</script> dijo eso")
    assert belief["claim"] == "<script>alert(1)</script> dijo eso"


def test_the_memory_travels_over_http_with_the_same_limits(workspace):
    app, store, admin, first, second, prospect = workspace
    with TestClient(app) as owner, TestClient(app) as outsider:
        login(owner, admin)
        login(outsider, second)
        created = owner.post(f"/api/leads/{prospect['id']}/memory", json={
            "subject": "objecion", "claim": "Le preocupa el ruido de los equipos.",
            "source_kind": "lead_said", "confidence": 0.8})
        assert created.status_code == 201, created.text
        belief = created.json()["belief"]
        assert belief["usable"] is True

        guess = owner.post(f"/api/leads/{prospect['id']}/memory", json={
            "subject": "plazo", "claim": "Seguramente quiere resolverlo este año.",
            "source_kind": "inferred", "confidence": 0.3}).json()["belief"]
        assert guess["usable"] is False

        listed = owner.get(f"/api/leads/{prospect['id']}/memory").json()
        assert len(listed["beliefs"]) == 2 and len(listed["usable"]) == 1
        assert "no se usa al hablar" in listed["notice"]

        assert owner.post(f"/api/memory/{guess['id']}/approve").json()["belief"]["usable"] is True
        assert owner.post(f"/api/memory/{belief['id']}/retract",
                          json={"reason": "No era de esta persona."}).json()["belief"]["state"] == "retracted"
        assert owner.post(f"/api/memory/{belief['id']}/retract", json={}).status_code == 422

        assert outsider.get(f"/api/leads/{prospect['id']}/memory").status_code == 404
        assert outsider.post(f"/api/memory/{guess['id']}/approve").status_code == 404


def test_every_write_leaves_an_audit_entry(workspace):
    app, store, admin, first, second, prospect = workspace
    belief = remember(store, prospect["id"], admin)
    memory.approve(store, belief["id"], first, now=NOW)
    memory.retract(store, belief["id"], {"reason": "Dato equivocado."}, first, now=NOW)
    with store.connect() as db:
        actions = [row["action"] for row in db.execute("SELECT action FROM audit_events")]
    for expected in ("agent.memory.record", "agent.memory.approve", "agent.memory.retract"):
        assert expected in actions
