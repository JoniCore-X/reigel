from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from reigel.api import create_app
from reigel.core import DomainError, Store, calendar_file, stamp, uid
from team_auth import allow, login as team_login


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setattr("reigel.api.load_environment", lambda: None)
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "test.sqlite3")
    store = app.state.store
    admin = store.create_user({"name": "Administradora", "email": "admin@example.test", "password": "correct-horse-test-42", "role": "admin"}, bootstrap=True)
    allow(store, admin, "advisor@example.test")
    advisor = store.create_user({"name": "Asesora", "email": "advisor@example.test", "password": "correct-horse-test-43", "role": "advisor"}, admin)
    store.update_user(advisor["id"], {"public_booking": True, "work_days": list(range(7))}, admin)
    return app, store, admin, advisor


def auth(client, email="admin@example.test", password="correct-horse-test-42"):
    response = team_login(client, email, password)
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
        landing = client.get("/captacion")
        assert landing.status_code == 200
        assert 'id="public-menu-toggle"' in landing.text
        # La navegación dejó de apuntar a rutas y apunta a anclas de esta misma
        # página; solo `/app` sigue siendo un destino aparte.
        for anchor in ("#inicio", "#empresa", "#equipo", "#soluciones", "#proceso", "#contacto", "#preguntas"):
            assert f'href="{anchor}"' in landing.text, anchor
        assert 'href="/app"' in landing.text
        assert 'data-open-chat' in landing.text
        assert 'id="reigel-chat"' in landing.text
        assert 'id="chat-form"' in landing.text
        assert 'id="chat-book-form"' in landing.text
        assert 'href="#privacidad"' in landing.text
        assert '/static/js/header-menu.js' in landing.text
        header_script = client.get("/static/js/header-menu.js")
        assert header_script.status_code == 200
        assert "aria-expanded" in header_script.text
        assert "Escape" in header_script.text
        assert "setBackgroundInert" in header_script.text
        assert "restoreFocus" in header_script.text
        assert "event.shiftKey" in header_script.text
        assert client.get("/static/css/corporate.css").status_code == 200

        workspace = client.get("/app")
        assert workspace.status_code == 200
        assert 'id="login-screen"' in workspace.text


def test_root_is_the_public_conversation_and_legacy_chat_stays_reachable(system):
    app, store, admin, _ = system
    store.update_settings({"site_url": "https://powersolar.example"}, admin)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert page.headers["x-robots-tag"] == "noindex, nofollow"
        assert page.headers["cache-control"] == "no-store"
        assert '<meta name="robots" content="noindex,nofollow">' in page.text
        assert 'id="ia-shell"' in page.text
        assert 'id="ia-thread"' in page.text
        assert 'id="ia-form"' in page.text
        assert 'src="/static/js/ia.js?v=19"' in page.text
        assert '<svg class="ia-title-mark"' in page.text and '<svg class="ia-empty-logo"' in page.text
        assert 'id="ia-plus"' in page.text
        assert 'data-ia-menu="new"' in page.text
        assert 'data-ia-menu="copy"' in page.text
        assert 'data-ia-menu="export-pdf"' in page.text and 'data-ia-menu="export-txt"' in page.text
        assert 'data-ia-menu="docs"' not in page.text
        assert "Aún no disponible" in page.text
        assert 'href="/captacion"' in page.text
        assert 'id="reigel-chat"' not in page.text

        chat = client.get("/chat")
        assert chat.status_code == 200
        assert chat.headers["x-robots-tag"] == "noindex, nofollow"
        assert '<meta name="robots" content="noindex,nofollow">' in chat.text
        assert 'id="reigel-chat"' in chat.text
        assert 'id="chat-messages"' in chat.text
        assert 'id="chat-welcome"' not in chat.text
        assert 'class="chat-page-intro"' not in chat.text
        assert 'class="chat-page-aside"' not in chat.text
        assert 'id="chat-form"' in chat.text
        assert "El historial de esta conversación se guarda para el equipo" in chat.text
        assert 'id="chat-session-state" hidden' in chat.text
        assert 'src="/static/js/chat.js?v=10"' in chat.text
        assert chat.text.index("/static/css/coordination-chat.css?v=4") > chat.text.index("/static/css/site-loader.css")
        assert 'data-book-step="3"' in chat.text and 'id="chat-book-progress" hidden' in chat.text
        assert 'href="/captacion"' in chat.text
        assert 'href="/app"' in chat.text
        chat_script = client.get("/static/js/chat.js")
        assert chat_script.status_code == 200
        assert "if (panel.dataset.chatPage === 'true') open();" in chat_script.text
        assert "call('/api/public/chat')" in chat_script.text
        assert "typeof data.conversation_id === 'string'" in chat_script.text
        assert "No customer data goes to localStorage" in chat_script.text
        chat_styles = client.get("/static/css/public-chat.css")
        assert chat_styles.status_code == 200
        assert "dialog.reigel-chat.chat-page-dialog" in chat_styles.text
        assert "@media(max-width:600px)" in chat_styles.text
        assert ".chat-page-conversation{height:100%;min-height:0" in chat_styles.text
        assert ".chat-page-main{width:100%;padding:0}" in chat_styles.text

        marketing = client.get("/captacion")
        assert marketing.status_code == 200
        assert '<link rel="canonical" href="https://powersolar.example/captacion">' in marketing.text
        assert '<meta property="og:url" content="https://powersolar.example/captacion">' in marketing.text
        assert marketing.headers["link"] == "<https://powersolar.example/captacion>; rel=\"canonical\""
        assert client.get("/sitemap.xml").text.count("https://powersolar.example/captacion") == 1
        assert "https://powersolar.example/</loc>" not in client.get("/sitemap.xml").text

        workspace = client.get("/app")
        assert 'href="/captacion" class="text-link">← Ver página de captación' in workspace.text
        assert 'class="capture-link" href="/captacion"' in workspace.text


def test_public_intent_selector_sends_its_question_without_collecting_contact_data(system):
    app, *_ = system
    expected_prompts = (
        "Quiero entender cómo evaluar el consumo y los costos de energía de mi hogar.",
        "Quiero explorar qué tendría que evaluar para tener respaldo durante apagones.",
        "Quiero orientación para explorar sistemas solares para mi hogar.",
        "No sé qué necesito y quisiera orientación sobre las opciones para mi hogar.",
    )
    with TestClient(app) as client:
        solutions = client.get("/soluciones")
        assert solutions.status_code == 200

        class PrefillButtons(HTMLParser):
            def __init__(self):
                super().__init__()
                self.buttons = []

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if "data-chat-prefill" in attributes:
                    assert tag == "button"
                    self.buttons.append(attributes)

        selector = PrefillButtons()
        selector.feed(solutions.text)
        intents = [button for button in selector.buttons if "intent-option" in button.get("class", "").split()]
        assert len(intents) == 4
        assert {button["data-chat-prefill"] for button in intents} == set(expected_prompts)
        assert "Quiero entender cómo funciona un sistema solar con batería en una casa." in {
            button["data-chat-prefill"] for button in selector.buttons
        }
        for button in selector.buttons:
            assert button.get("type") == "button"
            assert "data-open-chat" in button
            assert button.get("aria-controls") == "reigel-chat"
            assert "data-chat-prompt" not in button
            assert "name" not in button

        assert '/static/js/chat.js' in solutions.text
        chat_script = client.get("/static/js/chat.js")
        assert chat_script.status_code == 200
        assert "const prompt = event?.currentTarget?.dataset.chatPrefill;" in chat_script.text
        assert "if (prompt) await send(prompt);" in chat_script.text
        # /ia only auto-sends with the one-time authorization left by this click (same tab, 30 s).
        assert "sessionStorage.setItem('ia:autosend'" in chat_script.text


def test_password_hashed_session_cookie_and_logout(system):
    app, store, admin, _ = system
    with store.connect() as db:
        assert db.execute("SELECT password_hash FROM users WHERE id=?", (admin["id"],)).fetchone()[0].startswith("$argon2id$")
    with TestClient(app) as client:
        assert client.get("/api/dashboard").status_code == 401
        response = auth(client)
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert "password" not in response.text
        assert client.get("/api/auth/me").json()["user"]["id"] == admin["id"]
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/me").status_code == 401


def test_google_form_frame_permission_is_limited_to_contact_page(tmp_path, monkeypatch):
    monkeypatch.setattr("reigel.api.load_environment", lambda: None)
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "frame-policy.sqlite3")
    with TestClient(app) as client:
        # El formulario de Google vive en la página pública única desde el 27 de
        # noviembre de 2026, así que la excepción de `frame-src` la lleva `/captacion`.
        # Las direcciones de las secciones fundidas solo redirigen, y una redirección
        # no enmarca nada.
        for path, expected_status in (("/captacion", 200), ("/captacion?utm_source=test", 200),
                                      ("/contacto", 302), ("/empresa", 302), ("/equipo", 302),
                                      ("/soluciones", 302), ("/proceso", 302), ("/preguntas", 302), ("/", 200),
                                      ("/app", 200), ("/health", 200), ("/api/auth/me", 401)):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == expected_status, path
            directives = {
                parts[0]: parts[1:]
                for directive in response.headers["content-security-policy"].split(";")
                if (parts := directive.split())
            }
            expected_frames = ["'self'", "https://docs.google.com"] if path.startswith("/captacion") else ["'self'"]
            assert directives["frame-src"] == expected_frames, path
            assert directives["default-src"] == ["'self'"]
            assert directives["script-src"] == ["'self'"]
            assert directives["connect-src"] == ["'self'"]
            assert directives["form-action"] == ["'self'"]
            assert directives["object-src"] == ["'none'"]
            assert directives["frame-ancestors"] == ["'none'"]
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
            assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"


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
        assert set(response.json()["appointment"]) == {"id", "reference", "start_at", "end_at", "advisor_name"}
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
