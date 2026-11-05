from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from reigel.api import create_app
from reigel.core import DomainError, Store, calendar_file, stamp, uid


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "test.sqlite3")
    store = app.state.store
    admin = store.create_user({"name": "Administradora", "email": "admin@example.test", "password": "correct-horse-test-42", "role": "admin"}, bootstrap=True)
    advisor = store.create_user({"name": "Asesora", "email": "advisor@example.test", "password": "correct-horse-test-43", "role": "advisor"}, admin)
    store.update_user(advisor["id"], {"public_booking": True, "work_days": list(range(7))}, admin)
    return app, store, admin, advisor


def auth(client, email="admin@example.test", password="correct-horse-test-42"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response


def lead_data(**extra):
    return {"name": "Persona interesada", "email": "client@example.test", "phone": "+17875551212", "municipality": "Ponce", "monthly_bill": 180, "consent": True, **extra}


def next_slot(store, advisor):
    day = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    return store.slots(advisor["id"], day)["slots"][0]["start_at"]


def test_public_header_keeps_existing_booking_chat_and_private_app(system):
    app, *_ = system
    with TestClient(app) as client:
        landing = client.get("/")
        assert landing.status_code == 200
        assert 'id="public-menu-toggle"' in landing.text
        assert 'href="#proceso"' in landing.text
        assert 'href="#preguntas"' in landing.text
        assert 'href="#evaluacion"' in landing.text
        assert 'class="team-badge"' in landing.text
        assert "<span>Team <strong>Caguas</strong></span>" in landing.text
        assert 'class="hero-intents ps2-panel"' in landing.text
        assert 'class="public-hero ps2-layout"' in landing.text
        assert 'class="hero-grid ps2-inner"' in landing.text
        assert 'class="public-hero-copy ps2-copy"' in landing.text
        assert 'class="hero-intents ps2-panel"' in landing.text
        assert 'class="intent-options ps2-options"' in landing.text
        assert landing.text.count("intent-option ps2-option") == 4
        assert landing.text.index("public-intents.css") < landing.text.index("public-layout-refinement.css")
        assert 'data-open-chat' in landing.text
        assert 'id="reigel-chat"' in landing.text
        assert 'id="evaluacion"' in landing.text
        assert '/static/js/header-menu.js' in landing.text
        header_css = client.get("/static/css/public-header.css")
        assert header_css.status_code == 200
        assert ".public-header::before" in header_css.text
        assert "repeating-linear-gradient" in header_css.text
        assert "--psh-navy: #041631" in header_css.text
        assert "rgba(255, 255, 255, 0.1)" in header_css.text
        assert "@media (max-width: 1240px)" in header_css.text
        assert ".public-header .sun-mark::before" in header_css.text
        refinement_css = client.get("/static/css/public-layout-refinement.css")
        assert refinement_css.status_code == 200
        assert "--ps-container: 1280px" in refinement_css.text
        assert ".ps2-layout .ps2-inner" in refinement_css.text
        assert ".ps2-layout .ps2-panel .ps2-panel-title" in refinement_css.text
        assert "@media (max-width: 430px)" in refinement_css.text
        assert "@media (prefers-reduced-motion: reduce)" in refinement_css.text
        header_script = client.get("/static/js/header-menu.js")
        assert header_script.status_code == 200
        assert "aria-expanded" in header_script.text
        assert "Escape" in header_script.text
        assert "min-width: 1241px" in header_script.text
        intent_script = client.get("/static/js/public-intents.js")
        assert intent_script.status_code == 200
        assert "IntersectionObserver" in intent_script.text

        workspace = client.get("/app")
        assert workspace.status_code == 200
        assert 'id="login-screen"' in workspace.text


def test_public_intent_selector_prefills_chat_without_sending_or_collecting_contact_data(system):
    app, *_ = system
    expected_prompts = (
        "Quiero entender cómo evaluar el consumo y los costos de energía de mi hogar.",
        "Quiero explorar qué tendría que evaluar para tener respaldo durante apagones.",
        "Quiero orientación para explorar sistemas solares para mi hogar.",
        "No sé qué necesito y quisiera orientación sobre las opciones para mi hogar.",
    )
    with TestClient(app) as client:
        landing = client.get("/")
        assert landing.status_code == 200
        selector = landing.text.split('<section class="hero-intents ps2-panel"', 1)[1].split("</section>", 1)[0]
        assert "¿Qué te gustaría mejorar?" in selector
        assert selector.count('class="intent-option ps2-option"') == 4
        assert selector.count("data-open-chat") == 4
        assert "data-chat-prompt" not in selector
        assert "<input" not in selector
        assert "name=" not in selector
        for prompt in expected_prompts:
            assert f'data-chat-prefill="{prompt}"' in selector

        assert 'src="/static/js/chat.js?v=2"' in landing.text
        assert client.get("/static/css/public-intents.css").status_code == 200
        chat_script = client.get("/static/js/chat.js")
        assert chat_script.status_code == 200
        assert "const prompt = event?.currentTarget?.dataset.chatPrefill;" in chat_script.text
        assert "if (prompt) find('#chat-text').value = prompt;" in chat_script.text


def test_password_hashed_session_cookie_and_logout(system):
    app, store, admin, _ = system
    with store.connect() as db:
        assert db.execute("SELECT password_hash FROM users WHERE id=?", (admin["id"],)).fetchone()[0].startswith("scrypt$")
    with TestClient(app) as client:
        assert client.get("/api/dashboard").status_code == 401
        response = auth(client)
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert "password" not in response.text
        assert client.get("/api/auth/me").json()["user"]["id"] == admin["id"]
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/me").status_code == 401


def test_cross_origin_and_host_are_rejected(system):
    app, *_ = system
    with TestClient(app) as client:
        assert client.post("/api/auth/login", headers={"Origin": "https://attacker.example"}, json={"email": "admin@example.test", "password": "correct-horse-test-42"}).status_code == 403
        assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400
        response = client.get("/health")
        assert response.status_code == 200
        assert response.headers["X-Frame-Options"] == "DENY"


def test_login_rate_limited(system):
    app, *_ = system
    with TestClient(app) as client:
        for _ in range(8):
            assert client.post("/api/auth/login", json={"email": "admin@example.test", "password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"email": "admin@example.test", "password": "wrong"}).status_code == 429


def test_public_intake_consent_honeypot_and_no_pii_response(system):
    app, store, *_ = system
    with TestClient(app) as client:
        assert client.post("/api/public/leads", json=lead_data(consent=False)).status_code == 422
        assert client.post("/api/public/leads", json=lead_data(website="spam")).status_code == 422
        assert client.post("/api/public/leads", json=lead_data(email="bad", phone="")).status_code == 422
        response = client.post("/api/public/leads", json=lead_data(source="malicious arbitrary source", utm_campaign="solar-2026"))
        assert response.status_code == 201
        assert set(response.json()) == {"lead_id"}
        with store.connect() as db:
            row = db.execute("SELECT * FROM leads WHERE id=?", (response.json()["lead_id"],)).fetchone()
            assert row["source"] == "web"
            assert row["utm_campaign"] == "solar-2026"


def test_advisor_scope_cannot_read_modify_or_assign_other_contacts(system):
    app, store, admin, advisor = system
    private = store.create_lead(lead_data(advisor_id=admin["id"]), admin)
    own = store.create_lead(lead_data(email="other@example.test", advisor_id=advisor["id"]), admin)
    with TestClient(app) as client:
        auth(client, "advisor@example.test", "correct-horse-test-43")
        leads = client.get("/api/leads").json()["leads"]
        assert [lead["id"] for lead in leads] == [own["id"]]
        assert client.get(f"/api/leads/{private['id']}").status_code == 404
        assert client.patch(f"/api/leads/{private['id']}", json={"stage": "ganado"}).status_code == 404
        assert client.patch(f"/api/leads/{own['id']}", json={"advisor_id": admin["id"]}).status_code == 403
        assert client.post("/api/team", json={"name": "Bad", "email": "bad@example.test", "password": "safe-test-password"}).status_code == 403
        assert client.patch(f"/api/team/{advisor['id']}", json={"active": False}).status_code == 403
        assert client.patch("/api/settings", json={"name": "Hacked"}).status_code == 403


def test_atomic_booking_duplicate_rejects_and_no_orphan_lead(system):
    app, store, admin, advisor = system
    start = next_slot(store, advisor)
    with TestClient(app) as client:
        request = lead_data(advisor_id=advisor["id"], start_at=start)
        response = client.post("/api/public/book", json=request)
        assert response.status_code == 201, response.text
        assert set(response.json()["appointment"]) == {"id", "start_at", "end_at", "advisor_name"}
        assert client.post("/api/public/book", json=lead_data(email="second@example.test", advisor_id=advisor["id"], start_at=start)).status_code == 409
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM appointments").fetchone()[0] == 1
        assert db.execute("SELECT stage FROM leads").fetchone()[0] == "cita"


def test_parallel_bookings_only_one_wins(system):
    _, store, _, advisor = system
    start = next_slot(store, advisor)

    def reserve(index):
        try:
            return store.book(lead_data(email=f"client{index}@example.test", advisor_id=advisor["id"], start_at=start))["id"]
        except DomainError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(reserve, (1, 2)))
    assert sum(isinstance(value, str) for value in result) == 1
    assert result.count(409) == 1


def test_past_off_grid_and_horizon_cannot_book(system):
    _, store, _, advisor = system
    for start in [(datetime.now(UTC) - timedelta(days=1)).isoformat(), (datetime.now(UTC) + timedelta(days=100)).isoformat(), next_slot(store, advisor).replace(":00-", ":03-")]:
        with pytest.raises(DomainError) as error:
            store.book(lead_data(advisor_id=advisor["id"], start_at=start))
        assert error.value.status == 409
    with pytest.raises(DomainError):
        store.book(lead_data(advisor_id=advisor["id"], start_at="2030-02-01T09:00:00"))


def test_cancellation_releases_slot_and_calendar_is_private(system):
    app, store, admin, advisor = system
    start = next_slot(store, advisor)
    appointment = store.book(lead_data(advisor_id=advisor["id"], start_at=start))
    with TestClient(app) as client:
        assert client.get(f"/api/appointments/{appointment['id']}/ics").status_code == 401
        auth(client)
        response = client.get(f"/api/appointments/{appointment['id']}/ics")
        assert response.status_code == 200
        assert "BEGIN:VCALENDAR\r\n" in response.text
        assert "STATUS:CONFIRMED" in response.text
        assert client.patch(f"/api/appointments/{appointment['id']}", json={"status": "cancelled"}).status_code == 200
    result = store.book(lead_data(advisor_id=advisor["id"], start_at=start))
    assert result["id"] != appointment["id"]


def test_same_contact_cannot_double_book_different_advisors(system):
    _, store, admin, advisor = system
    store.update_user(admin["id"], {"public_booking": True, "work_days": list(range(7))}, admin)
    start = next_slot(store, advisor)
    store.book(lead_data(advisor_id=advisor["id"], start_at=start))
    with pytest.raises(DomainError) as error:
        store.book(lead_data(advisor_id=admin["id"], start_at=start))
    assert error.value.status == 409


def test_availability_configuration_and_private_profiles(system):
    app, store, admin, advisor = system
    with pytest.raises(DomainError):
        store.update_user(advisor["id"], {"work_start": "18:00", "work_end": "09:00"}, admin)
    with pytest.raises(DomainError):
        store.update_user(advisor["id"], {"timezone": "Fake/Zone"}, admin)
    with pytest.raises(DomainError):
        store.update_user(advisor["id"], {"duration_minutes": True}, admin)
    with pytest.raises(DomainError):
        store.update_user(admin["id"], {"active": False}, admin)
    with TestClient(app) as client:
        response = client.get("/api/public/config").json()
        assert response["advisors"] == [{"id": advisor["id"], "name": advisor["name"]}]
        assert "email" not in str(response)


def test_password_change_revokes_all_sessions(system):
    app, store, *_ = system
    with TestClient(app) as first, TestClient(app) as second:
        auth(first)
        auth(second)
        assert first.post("/api/auth/password", json={"current_password": "incorrect", "new_password": "my-safe-new-pass-44"}).status_code == 401
        assert first.post("/api/auth/password", json={"current_password": "correct-horse-test-42", "new_password": "my-safe-new-pass-44"}).status_code == 200
        assert second.get("/api/auth/me").status_code == 401
        assert first.get("/api/auth/me").status_code == 401
        auth(first, password="my-safe-new-pass-44")


def test_settings_no_unsafe_origin_and_private_no_cache(system):
    app, *_ = system
    with TestClient(app) as client:
        auth(client)
        assert client.patch("/api/settings", json={"site_url": "javascript:alert(1)"}).status_code == 422
        assert client.patch("/api/settings", json={"site_url": "https://user:secret@example.com"}).status_code == 422
        response = client.get("/api/dashboard")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-robots-tag"] == "noindex, nofollow"


def test_calendar_escapes_newline_and_folds_unicode(system):
    _, store, _, advisor = system
    appointment = {"id": "safe-id", "start_at": "2026-11-01T13:00:00+00:00", "end_at": "2026-11-01T13:30:00+00:00", "lead_name": "x\nATTENDEE:evil", "advisor_name": "José" * 50, "status": "confirmed"}
    output = calendar_file(appointment, store.settings())
    assert "\r\nATTENDEE:" not in output
    assert "\\nATTENDEE:" in output
    assert all(len(line.encode()) <= 75 for line in output.split("\r\n"))


def test_conversation_assignment_scopes_and_pauses_ai(system):
    app, store, admin, advisor = system
    lead = store.create_lead(lead_data(advisor_id=admin["id"]), admin)
    conversation_id = uid()
    with store.connect() as db:
        db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?,?,?)", (conversation_id, "telegram", "123456", "Persona", lead["id"], admin["id"], "ai", stamp()))
    with TestClient(app) as client:
        auth(client, "advisor@example.test", "correct-horse-test-43")
        assert client.get(f"/api/conversations/{conversation_id}").status_code == 404
        assert client.patch(f"/api/conversations/{conversation_id}", json={"advisor_id": advisor["id"]}).status_code == 403
        auth(client)
        assert client.patch(f"/api/conversations/{conversation_id}", json={"advisor_id": "missing"}).status_code == 422
        response = client.patch(f"/api/conversations/{conversation_id}", json={"advisor_id": advisor["id"]})
        assert response.status_code == 200
        assert response.json()["conversation"]["mode"] == "human"
        assert store.get_lead(lead["id"], admin)["advisor_id"] == advisor["id"]
        auth(client, "advisor@example.test", "correct-horse-test-43")
        assert client.get(f"/api/conversations/{conversation_id}").status_code == 200


def test_booking_reassignment_updates_linked_conversations(system):
    _, store, admin, advisor = system
    lead = store.create_lead(lead_data(advisor_id=admin["id"]), admin)
    conversation_id = uid()
    with store.connect() as db:
        db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?,?,?)", (conversation_id, "telegram", "456789", "Persona", lead["id"], admin["id"], "human", stamp()))
    store.book({"lead_id": lead["id"], "advisor_id": advisor["id"], "start_at": next_slot(store, advisor)}, actor=admin)
    assert store.conversation(conversation_id, advisor)["advisor_id"] == advisor["id"]


@pytest.mark.parametrize("endpoint,body", [
    ("/api/team", {"name": "Invalid", "email": "invalid@example.test", "password": "valid-test-password", "role": []}),
    ("/api/leads", lead_data(source=[])),
    ("/api/leads", lead_data(advisor_id={})),
])
def test_malformed_json_types_never_internal_error(system, endpoint, body):
    app, *_ = system
    with TestClient(app) as client:
        auth(client)
        assert client.post(endpoint, json=body).status_code == 422
