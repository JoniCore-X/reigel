import math

import pytest
from fastapi.testclient import TestClient

from reigel.api import create_app
from reigel.core import DomainError
from reigel.energy import calculate
from team_auth import allow, login as team_login


def test_energy_known_array_consumption_production_and_coverage():
    result = calculate({"monthly_kwh": 600, "panel_watts": 400, "panel_count": 10,
                        "specific_yield_kwh_per_kw_year": 1500, "coverage_target_percent": 100,
                        "monthly_bill": 175})
    assert result["results"] == {"monthly_kwh": 600, "annual_kwh": 7200, "system_kw": 4,
                                  "system_watts": 4000, "annual_production_kwh": 6000,
                                  "coverage_percent": pytest.approx(83.33333333),
                                  "required_system_kw": 4.8, "required_panel_count": 12}
    assert result["declared"]["monthly_bill"] == 175
    assert result["review_required"] is True
    assert result["assumptions"]
    assert len(result["limitations"]) == 4
    assert not result["missing"]
    assert "savings" not in result["results"]


def test_energy_no_default_yield_or_tariff_is_invented():
    result = calculate({"monthly_bill": 300})
    assert all(value is None for value in result["results"].values())
    assert len(result["missing"]) == 3
    assert not result["assumptions"]
    result = calculate({"annual_kwh": 1200, "system_kw": 2})
    assert result["results"]["monthly_kwh"] == 100
    assert result["results"]["system_watts"] == 2000
    assert result["results"]["annual_production_kwh"] is None


def test_energy_zero_consumption_avoids_division_and_count_rounds_up():
    zero = calculate({"monthly_kwh": 0, "system_kw": 2, "specific_yield_kwh_per_kw_year": 1000})
    assert zero["results"]["coverage_percent"] is None
    assert zero["missing"]
    sized = calculate({"annual_kwh": 3500, "panel_watts": 405,
                       "specific_yield_kwh_per_kw_year": 1000, "coverage_target_percent": 50})
    assert sized["results"]["required_system_kw"] == 1.75
    assert sized["results"]["required_panel_count"] == 5


@pytest.mark.parametrize("data", [
    {"monthly_kwh": -1}, {"system_kw": 0}, {"panel_watts": 0}, {"panel_count": 1.5},
    {"panel_count": True}, {"panel_count": 1_000_001}, {"specific_yield_kwh_per_kw_year": 0},
    {"annual_kwh": "NaN"}, {"system_kw": math.inf}, {"monthly_kwh": {}},
    {"monthly_bill": False}, {"coverage_target_percent": 101}, {"coverage_target_percent": 0},
    {"tariff": 0.3}, {"monthly_kwh": 100, "annual_kwh": 500},
    {"system_kw": 3, "panel_watts": 400, "panel_count": 10},
    {"annual_kwh": "1e-310", "system_kw": 1_000_000_000, "specific_yield_kwh_per_kw_year": 1_000_000_000},
])
def test_energy_rejects_invalid_and_inconsistent_inputs(data):
    with pytest.raises(DomainError) as error:
        calculate(data)
    assert error.value.status == 422


def test_energy_authenticated_endpoint_and_invalid_request(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.setenv("SITE_URL", "")
    app = create_app(tmp_path / "energy.sqlite3")
    app.state.store.create_user({"name": "Energía QA", "email": "energy@example.test",
                                 "password": "energy-qa-long-password", "role": "admin"}, bootstrap=True)
    with TestClient(app) as client:
        assert client.post("/api/energy/calculate", json={"system_kw": 4}).status_code == 401
        assert team_login(client, "energy@example.test", "energy-qa-long-password").status_code == 200
        response = client.post("/api/energy/calculate", json={"system_kw": 4, "annual_kwh": 6000,
                                                            "specific_yield_kwh_per_kw_year": 1500})
        assert response.status_code == 200, response.text
        assert response.json()["results"]["coverage_percent"] == 100
        assert response.headers["cache-control"] == "no-store"
        assert client.post("/api/energy/calculate", json={"system_kw": -4}).status_code == 422
        assert client.post("/api/energy/calculate", json={}, headers={"Origin": "https://foreign.example"}).status_code == 403
