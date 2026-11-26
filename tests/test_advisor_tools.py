import pytest
from fastapi.testclient import TestClient

from reigel.advisor_tools import evaluate_practice, prepare_brief
from reigel.api import create_app
from reigel.core import DomainError
from team_auth import allow, login as team_login


@pytest.fixture
def tools_system(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "advisor-tools.sqlite3")
    store = app.state.store
    admin = store.create_user({"name": "Admin de prueba", "email": "admin@tools.test", "password": "synthetic-tools-admin", "role": "admin"}, bootstrap=True)
    allow(store, admin, "owner@tools.test", "other@tools.test")
    owner = store.create_user({"name": "Asesor de prueba", "email": "owner@tools.test", "password": "synthetic-tools-owner"}, admin)
    other = store.create_user({"name": "Otro asesor", "email": "other@tools.test", "password": "synthetic-tools-other"}, admin)
    lead = store.create_lead({"name": "Persona sintética", "email": "persona@example.test", "municipality": "Caguas", "advisor_id": owner["id"]}, admin)
    return app, store, admin, owner, other, lead


def test_practice_is_explicit_simulation_with_reproducible_rubric():
    data = {"scenario_id": "cost", "response": "Entiendo que te preocupa el costo. Depende de una evaluación y de las condiciones documentadas. Si te parece, podemos revisar tu presupuesto y comparar las opciones, ¿quieres conversarlo?"}
    result = evaluate_practice(data)
    assert result == evaluate_practice(data)
    assert result["simulation"] is True and result["review_required"] is True
    assert result["method"] == "explicit_heuristics"
    assert result["score"] == 12
    assert {item["id"] for item in result["rubric"]} == {"clarity", "accuracy", "listening", "objection", "respect", "next_step"}
    assert all(item["criterion"] and item["evidence"] for item in result["rubric"])


def test_practice_flags_pressure_and_unverified_guarantees():
    result = evaluate_practice({"scenario_id": "finance", "response": "Tu financiamiento está aprobado y el ahorro garantizado. Solo hoy, tienes que firmar."})
    rubric = {item["id"]: item for item in result["rubric"]}
    assert rubric["accuracy"]["score"] == 0
    assert rubric["respect"]["score"] == 0
    assert any("promesas" in item for item in result["feedback"])


@pytest.mark.parametrize("data", [None, [], {}, {"scenario_id": "unknown", "response": "Esta es una respuesta"}, {"scenario_id": "cost", "response": "x"}, {"scenario_id": "cost", "response": "x" * 2501}, {"scenario_id": "cost", "response": "Respuesta simulada", "send": True}])
def test_practice_rejects_invalid_or_action_fields(data):
    with pytest.raises(DomainError) as error:
        evaluate_practice(data)
    assert error.value.status == 422


def test_preparation_uses_only_authorized_declared_context(tools_system):
    _, store, _, owner, other, lead = tools_system
    result = prepare_brief(store, lead["id"], owner)
    assert result["certified"] is False and result["review_required"] is True
    assert {"label": "Municipio declarado", "value": "Caguas"} in result["known"]
    assert result["questions"] and result["unverified"]
    assert "persona@example.test" not in str(result)
    assert any("autorización" in item for item in result["next_actions"])
    with pytest.raises(DomainError) as error:
        prepare_brief(store, lead["id"], other)
    assert error.value.status == 404


def test_advisor_tools_routes_require_authentication_and_preserve_data(tools_system):
    app, store, _, owner, other, lead = tools_system
    with TestClient(app) as client:
        assert client.get("/api/assistant/scenarios").status_code == 401
        assert client.post("/api/assistant/train", json={"scenario_id": "cost", "response": "Revisemos las condiciones."}).status_code == 401
        assert client.get(f"/api/leads/{lead['id']}/brief").status_code == 401
        assert team_login(client, owner["email"], "synthetic-tools-owner").status_code == 200
        assert len(client.get("/api/assistant/scenarios").json()["scenarios"]) == 7
        assert client.post("/api/assistant/train", json={"scenario_id": "cost", "response": "Entiendo tu presupuesto. Si quieres, podemos revisar las condiciones."}).status_code == 200
        assert client.get(f"/api/leads/{lead['id']}/brief").status_code == 200
        assert client.post("/api/assistant/train", json=[], headers={"Origin": "https://foreign.invalid"}).status_code == 403
        client.post("/api/auth/logout")
        team_login(client, other["email"], "synthetic-tools-other")
        assert client.get(f"/api/leads/{lead['id']}/brief").status_code == 404
    assert store.get_lead(lead["id"], owner) == lead
