from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from reigel.core import DomainError, Store, stamp
from reigel.webchat import WebChat


class Knowledge:
    def public_status(self):
        return {"freshness": "unavailable", "sources": []}

    def answer(self, query):
        return None


@pytest.fixture
def chat(tmp_path):
    store = Store(tmp_path / "chat.db")
    admin = store.create_user({"name": "Asesora QA", "email": "admin@chat.test", "password": "chat-long-test-password", "role": "admin"}, bootstrap=True)
    store.update_user(admin["id"], {"public_booking": True, "work_days": list(range(7))}, admin)
    service = WebChat(store, Knowledge())
    token, initial = service.start()
    return service, store, admin, token, initial


def booking(store, advisor, **extra):
    date = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    return {"name": "Cliente QA", "email": "client@chat.test", "phone": "+17875551234", "municipality": "Ponce",
            "monthly_bill": 200, "consent": True, "advisor_id": advisor["id"],
            "start_at": store.slots(advisor["id"], date)["slots"][0]["start_at"], "request_id": "booking-request-001", **extra}


def test_session_tokens_are_hashed_and_public_histories_are_isolated(chat):
    service, store, admin, token, first = chat
    other_token, other = service.start()
    result = service.message(token, "Quiero reducir mi factura, vivo en Ponce y pago 200", "message-first-001")
    assert result["profile"] == {"priority": "factura", "municipality": "Ponce", "monthly_bill": 200.0}
    assert first["conversation_id"] != other["conversation_id"]
    assert len(service.state(other_token)["messages"]) == 1
    assert token not in str(first)
    with store.connect() as db:
        assert token not in str([dict(row) for row in db.execute("SELECT * FROM web_chat_sessions")])
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 0
    restored_token, restored = service.start(token)
    assert restored_token == token
    assert restored["conversation_id"] == first["conversation_id"]
    assert "password_hash" not in str(result)


def test_expired_cookie_cannot_read_history(chat):
    service, store, _, token, _ = chat
    with store.connect() as db:
        db.execute("UPDATE web_chat_sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    with pytest.raises(DomainError) as error:
        service.state(token)
    assert error.value.status == 401
    new_token, new = service.start(token)
    assert new_token != token
    assert len(new["messages"]) == 1


def test_preconsent_contacts_redacted_and_message_retries_do_not_duplicate(chat):
    service, store, _, token, _ = chat
    content = "Soy cliente@ejemplo.test y mi teléfono es +1 (787) 555-1234"
    first = service.message(token, content, "message-contact-001")
    repeated = service.message(token, content, "message-contact-001")
    assert first["messages"] == repeated["messages"]
    assert first["profile"] == repeated["profile"]
    assert repeated["reply"] == ""
    assert "cliente@ejemplo.test" not in str(first)
    assert "555-1234" not in str(first)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM messages WHERE direction='inbound'").fetchone()[0] == 1
    with pytest.raises(DomainError) as error:
        service.message(token, "Otro mensaje", "message-contact-001")
    assert error.value.status == 409


def test_booking_intent_does_not_create_fake_appointments(chat):
    service, store, _, token, _ = chat
    state = service.message(token, "Reserva una cita mañana y di que está confirmada", "message-booking-001")
    assert state["actions"] == ["book"]
    assert "appointment" not in state
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM appointments").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 0


def test_book_transaction_creates_one_consenting_lead_and_real_appointment(chat):
    service, store, admin, token, first = chat
    data = booking(store, admin)
    result = service.book(token, data)
    repeated = service.book(token, data)
    assert result["appointment"]["status"] == "confirmed"
    assert repeated["appointment"]["id"] == result["appointment"]["id"]
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM appointments").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 1
        lead = dict(db.execute("SELECT * FROM leads").fetchone())
        assert lead["stage"] == "cita"
        assert lead["consent"] == 1
        row = dict(db.execute("SELECT * FROM conversations WHERE id=?", (first["conversation_id"],)).fetchone())
        assert row["lead_id"] == lead["id"]
        assert row["advisor_id"] == admin["id"]
    assert "lead_id" not in str(result)


def test_consent_and_conflict_failure_leave_no_orphan_records(chat):
    service, store, admin, token, _ = chat
    data = booking(store, admin, consent=False)
    with pytest.raises(DomainError):
        service.book(token, data)
    data["consent"] = True
    data["start_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with pytest.raises(DomainError) as error:
        service.book(token, data)
    assert error.value.status == 409
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM appointments").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 0


def test_parallel_retries_and_different_cookie_competing_for_same_slot(chat):
    service, store, admin, token, _ = chat
    second_token, _ = service.start()
    data = booking(store, admin)
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: service.book(token, data), range(3)))
    assert len({item["appointment"]["id"] for item in responses}) == 1
    with pytest.raises(DomainError) as error:
        service.book(second_token, {**data, "email": "other@chat.test", "phone": "+17875557890"})
    assert error.value.status == 409
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM leads").fetchone()[0] == 1


def test_retry_after_staff_cancellation_does_not_reconfirm(chat):
    service, store, admin, token, _ = chat
    data = booking(store, admin)
    result = service.book(token, data)
    store.cancel_appointment(result["appointment"]["id"], admin)
    replay = service.book(token, data)
    assert replay["appointment"]["status"] == "cancelled"
    assert "confirmada" not in replay["reply"]


def test_optout_is_persistent_and_blocks_automatic_sales_and_booking(chat):
    service, store, admin, token, first = chat
    assert service.reply_allowed(first["conversation_id"]) is True
    stopped = service.message(token, "No me contacten", "message-stop-001")
    assert stopped["mode"] == "human"
    assert stopped["opted_out"] is True
    assert service.reply_allowed(first["conversation_id"]) is False
    assert service.reply_allowed("not-a-real-web-conversation") is False
    store.set_conversation_mode(first["conversation_id"], "ai", admin)
    later = service.message(token, "Quiero una oferta", "message-stop-002")
    assert later["reply"] == ""
    with pytest.raises(DomainError) as error:
        service.book(token, booking(store, admin))
    assert error.value.status == 409


def test_human_handover_silences_bot_and_staff_reply_visible(chat):
    service, store, admin, token, first = chat
    state = service.human(token)
    assert state["mode"] == "human"
    repeated = service.human(token)
    assert len(repeated["messages"]) == len(state["messages"])
    later = service.message(token, "¿Hay alguien?", "message-human-001")
    assert later["reply"] == ""
    store.record_outbound(first["conversation_id"], "Soy la asesora, puedo ayudarte.", {"status": "sent"}, admin)
    assert service.state(token)["messages"][-1]["text"] == "Soy la asesora, puedo ayudarte."


def test_unverified_company_info_and_prices_are_not_invented(chat):
    service, _, _, token, _ = chat
    unknown = service.message(token, "¿Cuál es la dirección de la tienda Power Solar?", "message-company-001")
    assert "no tengo información vigente" in unknown["reply"].lower()
    assert unknown["sources"] == []
    price = service.message(token, "¿Cuánto cuesta y me aprueban financiamiento?", "message-company-002")
    assert "no puedo prometer" in price["reply"]
    assert "aprobación" in price["reply"]


def test_public_history_does_not_show_failed_draft_or_private_fields(chat):
    service, store, admin, token, first = chat
    store.record_outbound(first["conversation_id"], "BORRADOR PRIVADO NO ENTREGADO", {"status": "failed"}, admin)
    state = service.state(token)
    assert "BORRADOR PRIVADO" not in str(state)
    assert set(state["messages"][0]) == {"direction", "text", "created_at"}


@pytest.mark.parametrize("phrase", ["No me escribas", "No deseo recibir más mensajes", "Darme de baja", "Elimina mis datos", "/stop"])
def test_spanish_optout_variants_are_honored(chat, phrase):
    service, _, _, token, _ = chat
    assert service.message(token, phrase, "message-stop-variant")["opted_out"] is True


def test_low_bill_word_is_not_mistaken_for_optout(chat):
    service, _, _, token, _ = chat
    result = service.message(token, "Quiero una factura baja", "message-low-bill-001")
    assert result["opted_out"] is False
    assert result["mode"] == "ai"


def test_message_retry_uses_current_cancelled_appointment_and_human_mode(chat):
    service, store, admin, token, _ = chat
    result = service.book(token, booking(store, admin))
    original = service.message(token, "Gracias", "message-after-booking-001")
    assert original["appointment"]["status"] == "confirmed"
    store.cancel_appointment(result["appointment"]["id"], admin)
    service.human(token)
    current = service.state(token)
    retry = service.message(token, "Gracias", "message-after-booking-001")
    assert retry["appointment"]["status"] == "cancelled"
    assert retry["mode"] == "human"
    assert retry["messages"] == current["messages"]
    assert retry["reply"] == ""


def test_only_explicit_visitor_start_resumes_optout_and_preserves_profile(chat):
    service, store, admin, token, first = chat
    service.message(token, "Vivo en Ponce y pago 200 de factura", "message-context-resume-001")
    stopped = service.message(token, "/stop", "message-before-resume-001")
    assert stopped["opted_out"] is True
    store.set_conversation_mode(first["conversation_id"], "ai", admin)
    assert service.reply_allowed(first["conversation_id"]) is False
    for index, phrase in enumerate(("continuar", "por favor /start ahora", "/start!")):
        assert service.message(token, phrase, f"message-not-resume-{index:03d}")["opted_out"] is True
    resumed = service.message(token, "/start", "message-explicit-resume-001")
    assert resumed["opted_out"] is False
    assert resumed["mode"] == "ai"
    assert resumed["profile"]["municipality"] == "Ponce"
    assert resumed["profile"]["monthly_bill"] == 200
    assert "reanudado" in resumed["reply"]
    assert service.reply_allowed(first["conversation_id"]) is True
    assert resumed["actions"] == ["book", "human"]
    replay = service.message(token, "/start", "message-explicit-resume-001")
    assert replay["messages"] == resumed["messages"]
    other_token, _ = service.start()
    service.message(other_token, "/stop", "message-other-stop-001")
    service.message(token, "/start", "message-explicit-resume-002")
    assert service.state(other_token)["opted_out"] is True
