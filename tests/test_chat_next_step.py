"""/chat offers «Coordinar evaluación» / «Hablar con el equipo» once the visitor is prospected."""
import pytest

from reigel.core import Store
from reigel.webchat import WebChat

from test_webchat import Knowledge, booking


@pytest.fixture
def chat(tmp_path):
    store = Store(tmp_path / "next.db")
    admin = store.create_user({"name": "Asesora QA", "email": "admin@next.test", "password": "next-long-test-password", "role": "admin"}, bootstrap=True)
    store.update_user(admin["id"], {"public_booking": True, "work_days": list(range(7))}, admin)
    service = WebChat(store, Knowledge())
    token, initial = service.start()
    return service, store, admin, token, initial


def test_dock_stays_hidden_at_the_start_and_after_small_talk(chat):
    service, _, _, token, initial = chat
    assert initial["next_step"] is False
    assert service.message(token, "Hola, buenas", "small-talk-001")["next_step"] is False


def test_dock_appears_once_need_and_one_more_fact_are_known(chat):
    service, _, _, token, _ = chat
    first = service.message(token, "Quiero bajar mi factura de luz", "qualify-001")
    assert first["profile"].get("priority") == "factura"
    assert first["next_step"] is False
    second = service.message(token, "Vivo en Caguas", "qualify-002")
    assert second["profile"].get("municipality") == "Caguas"
    assert second["next_step"] is True
    # Once offered, it stays offered.
    assert service.message(token, "Gracias", "qualify-003")["next_step"] is True
    assert service.state(token)["next_step"] is True


@pytest.mark.parametrize("text", ["Quiero hablar con una persona", "Quiero reservar una cita"])
def test_asking_for_the_next_step_shows_it_right_away(chat, text):
    service, _, _, token, _ = chat
    assert service.message(token, text, "ask-step-001")["next_step"] is True


def test_a_booked_visitor_keeps_the_dock(chat):
    service, store, admin, token, _ = chat
    assert service.book(token, booking(store, admin))["next_step"] is True


def test_scripted_replies_speak_like_a_team_caguas_advisor(chat):
    service, _, _, token, initial = chat
    welcome = initial["messages"][-1]["text"]
    assert welcome == "Hola, ¿en qué te ayudo?"
    need = service.message(token, "Las alzas en la factura", "voice-flow-001")["reply"]
    assert need.startswith("¡Súper!") and "¿en qué pueblo está tu hogar?" in need
    town = service.message(token, "Caguas", "voice-flow-002")["reply"]
    assert town.startswith("¡Perfecto, Caguas!") and "cuánto pagas de luz al mes" in town
    bill = service.message(token, "Pago como 200", "voice-flow-003")["reply"]
    assert "$200" in bill and "¿Quieres ver los horarios disponibles o prefieres hablar con alguien del equipo?" in bill
    for reply in (need, town, bill):
        assert reply.count("?") == 1, reply  # una sola pregunta a la vez


@pytest.mark.parametrize("phrase,amount", [("Pago como 200", "$200"), ("como 200 al mes", "$200"), ("Pago como $200", "$200"),
                                           ("alrededor de 200", "$200"), ("más o menos 180", "$180"), ("cerca de 150 dólares", "$150")])
def test_approximate_bill_amounts_are_understood(chat, phrase, amount):
    service, _, _, token, _ = chat
    service.message(token, "Las alzas en la factura", "approx-flow-001")
    service.message(token, "Caguas", "approx-flow-002")
    assert f"Anoto {amount} como tu pago mensual" in service.message(token, phrase, "approx-flow-003")["reply"]
