from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json

import pytest

from reigel.core import DomainError, Store, stamp
from reigel.knowledge import KnowledgeBase
from reigel.webchat import WebChat


class Knowledge:
    def public_status(self):
        return {"freshness": "unavailable", "sources": []}

    def answer(self, query):
        return None

    def answer_technical(self, query):
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
    result = service.message(token, "Quiero reducir mi factura, vivo en Ponce y pago 200 al mes", "message-first-001")
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


def test_technical_knowledge_answers_with_citations_without_company_claims(tmp_path):
    store = Store(tmp_path / "technical-chat.db")
    service = WebChat(store, KnowledgeBase(store))
    token, _ = service.start()

    answer = service.message(
        token,
        "¿Las placas funcionan durante un apagón?",
        "technical-outage-001",
    )

    assert "se desconecta" in answer["reply"]
    assert "compatible" in answer["reply"]
    assert answer["sources"][0]["organization"] == "U.S. Department of Energy"
    assert answer["sources"][0]["url"].startswith("https://www.energy.gov/")
    assert "Power Solar" not in answer["reply"]


def test_technical_chat_abstains_on_unverified_luma_billing(tmp_path):
    store = Store(tmp_path / "luma-chat.db")
    service = WebChat(store, KnowledgeBase(store))
    token, _ = service.start()

    answer = service.message(
        token,
        "¿Qué cargos de LUMA significa este recibo?",
        "technical-luma-001",
    )

    assert "no tengo una fuente técnica vigente" in answer["reply"].lower()
    assert answer["sources"] == []
    assert answer["actions"] == ["human"]


def test_technical_chat_abstains_on_unverified_maintenance_guidance(tmp_path):
    store = Store(tmp_path / "maintenance-chat.db")
    service = WebChat(store, KnowledgeBase(store))
    token, _ = service.start()

    answer = service.message(
        token,
        "¿Qué mantenimiento preventivo debo hacer a los paneles?",
        "technical-maintenance-001",
    )

    assert "no tengo una fuente técnica vigente" in answer["reply"].lower()
    assert answer["sources"] == []
    assert answer["actions"] == ["human"]


def test_public_history_does_not_show_failed_draft_or_private_fields(chat):
    service, store, admin, token, first = chat
    store.record_outbound(first["conversation_id"], "BORRADOR PRIVADO NO ENTREGADO", {"status": "failed"}, admin)
    state = service.state(token)
    assert "BORRADOR PRIVADO" not in str(state)
    assert set(state["messages"][0]) == {"direction", "text", "created_at"}


def test_bill_frequency_is_confirmed_before_reporting_monthly_amount(chat):
    service, _, _, token, _ = chat

    pending = service.message(token, "Mi factura es de $300", "message-bill-period-001")

    assert "monthly_bill" not in pending["profile"]
    assert "¿Corresponde a tu factura mensual?" in pending["reply"]

    confirmed = service.message(token, "Sí, mensual", "message-bill-period-002")

    assert confirmed["profile"]["monthly_bill"] == 300
    assert "$300" in confirmed["reply"]
    assert "factura mensual" in confirmed["reply"]


def test_bill_correction_replaces_previous_amount(chat):
    service, _, _, token, _ = chat
    service.message(token, "Pago $300 al mes", "message-bill-correction-001")

    corrected = service.message(
        token,
        "Me equivoqué, en realidad son $250 mensuales",
        "message-bill-correction-002",
    )

    assert corrected["profile"]["monthly_bill"] == 250
    assert "corrección" in corrected["reply"].lower()


def test_conflicting_bill_amounts_request_clarification_without_storing_either(chat):
    service, _, _, token, _ = chat

    result = service.message(
        token,
        "Mi factura es de $300 y pago $250",
        "message-bill-conflict-001",
    )

    assert "no quiero asumir" in result["reply"].lower()
    assert "monthly_bill" not in result["profile"]


def test_corrected_municipality_uses_latest_value(chat):
    service, _, _, token, _ = chat
    service.message(token, "Vivo en Ponce", "message-municipality-001")

    result = service.message(
        token,
        "No, me equivoqué: vivo en Caguas",
        "message-municipality-002",
    )

    assert result["profile"]["municipality"] == "Caguas"
    assert "corrección" in result["reply"].lower()


def test_contextual_monthly_bill_answer_is_saved_and_acknowledged(chat):
    service, _, _, token, _ = chat
    service.message(token, "No sé cuántos kWh consumo", "message-bill-question-001")

    result = service.message(token, "Son unos 280 dólares", "message-bill-answer-001")

    assert result["profile"]["monthly_bill"] == 280
    assert "$280" in result["reply"]
    assert "mensual" in result["reply"].lower()


def test_contextual_municipality_answer_is_acknowledged(chat):
    service, _, _, token, _ = chat
    service.message(token, "Quiero reducir mi factura", "message-location-question-001")

    result = service.message(token, "Bayamón", "message-location-answer-001")

    assert result["profile"]["municipality"] == "Bayamón"
    assert "bayamón" in result["reply"].lower()


def test_annual_bill_is_not_misclassified_as_monthly_confirmation(chat):
    service, store, _, token, _ = chat
    service.message(token, "Pago $500", "message-annual-period-001")

    result = service.message(token, "Es anual, no mensual", "message-annual-period-002")

    assert result["profile"].get("monthly_bill") is None
    assert "$500" not in result["reply"]
    with store.connect() as db:
        profile = json.loads(
            db.execute(
                "SELECT profile_json FROM web_chat_sessions WHERE token_hash=?",
                (service._token_hash(token),),
            ).fetchone()["profile_json"]
        )
    assert profile["bill_period"] == "annual"


def test_extended_context_and_correction_flow(chat):
    service, _, _, token, _ = chat

    priority = service.message(token, "Quiero reducir mi factura", "message-long-flow-001")
    location = service.message(token, "Bayamón", "message-long-flow-002")
    consumption = service.message(
        token,
        "No sé cuántos kWh consumo",
        "message-long-flow-003",
    )
    bill = service.message(token, "Son unos 280 dólares", "message-long-flow-004")
    correction = service.message(
        token,
        "Perdón, quise decir 320 al mes",
        "message-long-flow-005",
    )

    assert priority["profile"]["priority"] == "factura"
    assert "bayamón" in location["reply"].lower()
    assert "no hace falta" in consumption["reply"].lower()
    assert "$280" in bill["reply"]
    assert correction["profile"]["monthly_bill"] == 320
    assert "corrección" in correction["reply"].lower()
    assert len(correction["messages"]) == 11


def test_definitive_decline_does_not_offer_booking(chat):
    service, _, _, token, _ = chat

    result = service.message(token, "No me interesa", "message-decline-001")

    assert result["actions"] == []
    assert "no insistiré" in result["reply"].lower()


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
    service.message(token, "Vivo en Ponce y pago 200 al mes de factura", "message-context-resume-001")
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
