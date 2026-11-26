"""Public replies cannot claim actions the assistant does not perform, nor mix Portuguese.

The bad answers are verbatim from scripts/eval_ia.py runs with qwen2.5:3b (25 nov 2026).
"""
import json

import pytest
from fastapi.testclient import TestClient

from reigel import ai_chat, api, assistant

OBSERVED_BAD = (
    "Reservaste una cita para una evaluación. El equipo de Power Solar revisará tu techo e informará sobre lo que conviene para tu hogar. ¿Quieres que te explique más sobre la evaluación?",
    "Reservaste una cita para una evaluación. El equipo de Power Solar revisará tu techo, el consumo de luz e irá a revisar el diseño de las placas. Esperamos poder ayudarte con lo que necesitas.",
    "Nosotros nos encargaremos de ello. No recibirá más mensajes de nuestra parte.",
    "Te tomamos nota. No recibirás más mensajes de nuestra parte. Si cambias de idea ou tienes alguna outra pergunta, só fale.",
    "Entendido, no enviaré más mensajes de Power Solar a partir de agora. Estoy en buen camino para entender más sobre opciones de energía solar. Si tienes más preguntas ou necesitas ayuda com algúno, estoy aquí para ajudar.",
    "Entonces hablaré como si fuera una persona del equipo. ¿Es para casa o apartamento?",
    "¡Hola! Entendido, hablaré con una persona del equipo para ayudarte. ¿Es para casa o apartamento?",
    "R.E.I.G.E.L.: Entiendo que prefieras que borremos tus datos personales. Sin embargo, no tengo la capacidad de hacer cambios directos en sistemas externos. Te recomendaría contactar directamente con el equipo de Power Solar para que puedan ayudarte con esto. ¿Quieres que te ayude a hacer esa llamada o a buscar información sobre cómo hacerlo?",
)
OTHER_CLAIMS = (
    "Listo, te agendo para el martes.",
    "Tu cita ya está confirmada.",
    "Te hemos dado de baja.",
    "Hemos borrado tus datos.",
    "Una persona del equipo te llamará pronto.",
    "Te comunico con un asesor ahora mismo.",
    "He pasado tu solicitud al equipo.",
    "Soy una persona del equipo de Power Solar.",
)
GOOD = (
    ai_chat.SAFE_REPLACEMENT,
    ai_chat.INSTALLATION_INVITATION,
    *ai_chat.REFERRAL_INVITATIONS.values(),
    "Para reservar la evaluación, usa «Citas y equipo». Allí una persona del equipo coordina contigo el día.",
    "Si prefieres que alguien del equipo te llame, pídelo en «Citas y equipo»; esta conversación no lo registra.",
    "Con gusto te explico otra cosa: las placas atrapan la luz del sol y el inversor la deja lista para la casa.",
    "Entiendo que no quieras recibir más mensajes. Para eso usa «Citas y equipo» en esta pantalla.",
    "Your question is welcome; the Power Solar team can review it.",
)


@pytest.mark.parametrize("value", OBSERVED_BAD + OTHER_CLAIMS)
def test_ia_and_chat_validators_reject_claimed_actions_and_portuguese(value):
    with pytest.raises(ValueError):
        ai_chat.validate_workspace_reply(value, verified=True)
    with pytest.raises(ValueError):
        ai_chat.validate_reply(value, verified=True)


@pytest.mark.parametrize("value", GOOD)
def test_ia_validator_accepts_referrals_and_plain_spanish(value):
    assert ai_chat.validate_workspace_reply(value, verified=False) == value
    assert not ai_chat.claimed_action(value) and not ai_chat.mixes_portuguese(value)


@pytest.mark.parametrize("value", [
    "Reservaste una cita para tu evaluación.",
    "Te hemos dado de baja y no recibirás más mensajes.",
    "Hemos borrado tus datos personales.",
    "Te explico com gusto, ou podemos verlo con el equipo.",
])
def test_drafts_reject_completed_actions_and_portuguese(value):
    with pytest.raises(RuntimeError):
        assistant.validate_draft(value)


def test_drafts_may_still_offer_a_real_handoff():
    # In a channel's ``ai`` mode staff can really take over, so offers stay valid.
    value = "Si prefieres, te paso con un asesor del equipo de Power Solar para coordinar la evaluación."
    assert assistant.validate_draft(value) == value


def test_portuguese_markers_do_not_hurt_common_spanish():
    for value in ("Con su factura y otra información, el equipo lo revisa.", "Cuéntame algo más sobre tu casa.",
                  "Sí, ahora mismo te explico.", "¿Tu techo es de cemento o de madera?"):
        assert not ai_chat.mixes_portuguese(value), value
    for value in ("Posso ajudar com isso.", "Não sei", "a avaliação", "a partir de agora"):
        assert ai_chat.mixes_portuguese(value), value


@pytest.mark.parametrize("question,intent", [
    ("Quiero reservar una cita para una evaluación en mi casa.", "booking"),
    ("Quiero hablar con una persona del equipo, no con un robot.", "human"),
    ("Ya no quiero recibir mensajes de Power Solar, denme de baja.", "opt_out"),
    ("Quiero que borren todos mis datos personales de su sistema.", "privacy_request"),
])
def test_referral_intents_get_the_fixed_sentence(question, intent):
    assert ai_chat.referral_intent(question) == intent
    reply = "Entiendo lo que necesitas."
    assert ai_chat.workspace_closing(question, reply) == ai_chat.REFERRAL_INVITATIONS[intent]
    assert ai_chat.workspace_closing(question, "Usa «Citas y equipo».") == ""
    assert ai_chat.workspace_closing(question, ai_chat.SAFE_REPLACEMENT) == ""
    assert ai_chat.workspace_closing("¿Cómo funciona una batería?", reply) == ""


def _events(text):
    events = []
    for block in text.split("\n\n"):
        event, data = "message", []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if data:
            events.append((event, json.loads("\n".join(data))))
    return events


@pytest.fixture
def ia_client(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_CHAT_AI", "ollama")
    monkeypatch.setenv("REIGEL_CHAT_MODEL", "test-model")
    monkeypatch.setenv("REIGEL_ENV", "local")
    client = TestClient(api.create_app(tmp_path / "claims.db"))
    client.get("/api/ia/bootstrap")
    return client


def _ask(client, monkeypatch, question, reply):
    async def fake_stream(history, incoming, verified="", reviewed=()):
        yield reply

    monkeypatch.setattr(ai_chat, "stream_workspace", fake_stream)
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    response = client.post(f"/api/ia/conversations/{conversation['id']}/messages", json={"text": question})
    return _events(response.text)


def test_ia_route_appends_the_referral_and_stores_it(ia_client, monkeypatch):
    question = "Quiero reservar una cita para una evaluación en mi casa."
    events = _ask(ia_client, monkeypatch, question, "¡Con gusto! La evaluación la hace el equipo de Power Solar.")
    published = "".join(data.get("text", "") for name, data in events if name == "delta")
    done = [data["assistant"]["content"] for name, data in events if name == "done"]
    assert published.endswith(ai_chat.REFERRAL_INVITATIONS["booking"]) and done == [published]


def test_ia_route_replaces_an_observed_claim(ia_client, monkeypatch):
    events = _ask(ia_client, monkeypatch, "Ya no quiero recibir mensajes de Power Solar, denme de baja.", OBSERVED_BAD[3])
    names = [name for name, _ in events]
    assert "replace" in names and "done" not in names
    assert "pergunta" not in "".join(data.get("text", "") for name, data in events if name == "delta")
