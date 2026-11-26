"""Independent regression cases discovered through isolated QA, never live data."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from reigel.api import create_app
from reigel.core import DomainError
from team_auth import allow, login as team_login


@pytest.fixture
def qa_system(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "independent.db")
    store = app.state.store
    admin = store.create_user({"name": "QA Admin", "email": "admin@independent.test", "password": "independent-long-password", "role": "admin"}, bootstrap=True)
    allow(store, admin, "advisor@independent.test")
    advisor = store.create_user({"name": "QA Advisor", "email": "advisor@independent.test", "password": "independent-long-password", "role": "advisor"}, admin)
    for person in (admin, advisor):
        store.update_user(person["id"], {"public_booking": True, "work_days": list(range(7))}, admin)
    return app, store, admin, advisor


@pytest.mark.parametrize("bad_url", ["https://[", "https://example.test:bad", "https://example.test:99999"])
def test_malformed_business_url_is_rejected_without_server_error(qa_system, bad_url):
    app, store, _, _ = qa_system
    with TestClient(app, raise_server_exceptions=False) as client:
        assert team_login(client, "admin@independent.test", "independent-long-password").status_code == 200
        response = client.patch("/api/settings", json={"site_url": bad_url})
        assert response.status_code == 422, response.text
        assert store.settings()["site_url"] == ""


def test_same_phone_with_different_punctuation_cannot_overlap(qa_system):
    _, store, admin, advisor = qa_system
    day = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    start = store.slots(admin["id"], day)["slots"][0]["start_at"]
    store.book({"name": "Same person", "phone": "+1 (787) 555-1234", "consent": True, "advisor_id": admin["id"], "start_at": start})
    with pytest.raises(DomainError) as rejected:
        store.book({"name": "Same person", "phone": "17875551234", "consent": True, "advisor_id": advisor["id"], "start_at": start})
    assert rejected.value.status == 409
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM appointments").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 1


def test_successful_team_logins_do_not_exhaust_failure_budget(qa_system):
    app, _, _, _ = qa_system
    with TestClient(app) as client:
        for _ in range(12):
            response = team_login(client, "admin@independent.test", "independent-long-password")
            assert response.status_code == 200, response.text
