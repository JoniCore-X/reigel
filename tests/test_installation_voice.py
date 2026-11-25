"""Roof evaluation, placement and installation are Power Solar's work, said in the third person.

Owner, 25 nov 2026, about a real /ia answer that told a homeowner how to place panels:
«Le falta hablar en tercera persona. ¿No sabías que ese trabajo lo hacemos nosotros?»
"""
import json

import pytest
from fastapi.testclient import TestClient

from reigel import ai_chat, api, assistant, voice

# Real /ia answer the owner rejected (llama3.2:3b).
OWNER_REJECTED = (
    "En un techo con baja pendiente, es importante que las placas solares estén colocadas de manera "
    "que no tengan sombras durante todo el día. Una forma de hacer esto es colocar las placas solares en "
    "un ángulo que permita que la luz del sol las ilumine durante la mayor parte del día. También se pueden "
    "colocar placas solares en diferentes áreas del techo para que cada una tenga la oportunidad de recibir "
    "luz del sol."
)

# Reproduced in /ia before the fix (llama3.2:3b, 25 nov 2026) and in drafts.
OBSERVED_DIY = (
    "Si tu techo es de madera y tiene una baja pendiente, es importante que revises cómo las placas "
    "solares se instalan.",
    "Si una casa tiene un techo plano, es mejor colocar las placas en un lado que reciba la luz del sol "
    "durante todo el día.",
    "Las placas solares se colocan en el techo de tu casa de manera que atrapen la luz del sol.",
    "Sí, puedes poner placas solares en un techo plano.",
    "Es recomendable que las placas solares sean colocadas en un ángulo más pronunciado.",
)

OTHER_DIY = (
    "Coloca las placas mirando hacia donde más sol da.",
    "Puedes inclinarlas un poco con unos soportes.",
    "Debes revisar la estructura de madera antes de empezar.",
    "Te recomiendo montar los paneles en la parte del techo sin sombra.",
    "Lo mejor es que pongas las placas tú mismo en el lado sur.",
)

GOOD_THIRD_PERSON = (
    "Eso lo trabaja el equipo de Power Solar. En la evaluación, el equipo revisa el material y el estado "
    "del techo de madera, su inclinación, hacia dónde mira y las sombras, y Power Solar diseña dónde "
    "conviene que vayan las placas. Para pedir esa evaluación, usa «Citas y equipo». "
    "¿Quieres que te explique qué se mira en el techo?",
    "El equipo de Power Solar decide dónde se colocan las placas después de evaluar el techo.",
    "No intentes instalar las placas por tu cuenta: ese trabajo lo hace el equipo de Power Solar.",
)


def test_every_ai_route_requires_third_person_power_solar_voice_for_installation_work():
    prompts = {
        "/ia": ai_chat.workspace_instructions(),
        "/chat": ai_chat._instructions({}, ""),
        "borradores": assistant._instructions({}),
    }
    for route, prompt in prompts.items():
        assert "es trabajo del equipo de Power Solar, no de la persona" in prompt, route
        assert "tercera persona" in prompt and "«el equipo de Power Solar evalúa…»" in prompt, route
        assert "nunca le digas a la persona que coloque, ponga, incline, oriente, monte, fije ni instale" in prompt, route
        assert "ni que revise o mida el techo ella misma" in prompt, route
        assert "sin cifras ni promesas" in prompt, route


def test_ia_prompt_sends_roof_questions_to_citas_y_equipo():
    prompt = ai_chat.workspace_instructions()
    assert "invitando a pedir la evaluación en «Citas y equipo»" in prompt
    # /ia still does not book or speak for the team in the first person.
    assert "No confirmes, reserves, cambies ni canceles citas" in prompt
    assert "«evaluamos», «instalamos»" in prompt


def test_glossary_and_example_present_the_team_doing_the_work():
    meaning = dict(voice.GLOSSARY)["techo, ubicación, inclinación, sombras o instalación de las placas"]
    assert "equipo de Power Solar" in meaning and "no las coloca, inclina ni instala por su cuenta" in meaning
    replies = [text for speaker, text in voice.PLAIN_EXAMPLE if speaker == "R.E.I.G.E.L."]
    roof = [text for text in replies if text.startswith("Eso lo trabaja el equipo de Power Solar")]
    assert roof and "equipo de Power Solar" in roof[0]


@pytest.mark.parametrize("text", (OWNER_REJECTED, *OBSERVED_DIY, *OTHER_DIY))
def test_diy_installation_coaching_is_rejected_on_every_route(text):
    assert ai_chat.coaches_installation(text)
    with pytest.raises(ValueError):
        ai_chat.validate_workspace_reply(text, verified=True)
    with pytest.raises(ValueError):
        ai_chat.validate_reply(text, verified=True)
    with pytest.raises(RuntimeError):
        assistant.validate_draft(text)


@pytest.mark.parametrize("text", GOOD_THIRD_PERSON)
def test_third_person_team_answers_pass(text):
    assert not ai_chat.coaches_installation(text)
    assert ai_chat.validate_workspace_reply(text) == text
    assert assistant.validate_draft(text) == text


def test_every_style_example_passes_the_new_check():
    for speaker, text in voice.EXAMPLE + voice.PLAIN_EXAMPLE:
        if speaker == "R.E.I.G.E.L.":
            assert not ai_chat.coaches_installation(text), text
            assert ai_chat.validate_workspace_reply(text) == text


def test_unrelated_second_person_advice_still_passes():
    for text in (
        "Lo primero es mirar tus facturas de luz de varios meses.",
        "Puedo orientarte sobre energía solar. ¿Qué necesitas saber?",
        "Si ves algo raro, aléjate y llama a un técnico cualificado.",
    ):
        assert not ai_chat.coaches_installation(text), text


def test_chat_roof_and_panel_questions_stay_with_the_deterministic_motor():
    # «placas» reached the /chat model before; only «panel» was considered technical.
    for text in ("¿Cómo deciden dónde van las placas?", "¿Puedo poner placas en un techo plano?"):
        assert ai_chat._TECHNICAL.search(text)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.setenv("REIGEL_CHAT_AI", "ollama")
    monkeypatch.setenv("REIGEL_CHAT_MODEL", "test-model")
    return TestClient(api.create_app(tmp_path / "installation-voice.db"))


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


def _answer(client, monkeypatch, reply):
    async def fake_stream(history, incoming, verified=""):
        yield reply

    monkeypatch.setattr(ai_chat, "stream_workspace", fake_stream)
    client.get("/api/ia/bootstrap")
    conversation = client.post("/api/ia/conversations", json={}).json()["conversation"]
    response = client.post(
        f"/api/ia/conversations/{conversation['id']}/messages",
        json={"text": "¿Qué debo revisar si mi techo es de madera y de baja pendiente?"},
    )
    return _events(response.text)


def test_ia_never_publishes_the_owner_rejected_answer(client, monkeypatch):
    events = _answer(client, monkeypatch, OWNER_REJECTED)
    names = [name for name, _ in events]
    assert "replace" in names and "done" not in names
    published = "".join(data.get("text", "") for name, data in events if name == "delta")
    assert "colocar las placas" not in published
    replaced = [data["assistant"]["content"] for name, data in events if name == "replace"]
    assert replaced == [ai_chat.SAFE_REPLACEMENT]


def test_ia_publishes_a_third_person_answer(client, monkeypatch):
    events = _answer(client, monkeypatch, GOOD_THIRD_PERSON[0])
    done = [data["assistant"]["content"] for name, data in events if name == "done"]
    assert done == [GOOD_THIRD_PERSON[0]]


def test_ia_appends_the_fixed_citas_y_equipo_invitation_to_roof_answers(client, monkeypatch):
    reply = "El equipo de Power Solar evalúa el techo, hacia dónde mira y las sombras, y decide dónde van las placas."
    events = _answer(client, monkeypatch, reply)
    published = "".join(data.get("text", "") for name, data in events if name == "delta")
    done = [data["assistant"]["content"] for name, data in events if name == "done"]
    expected = reply + "\n\n" + ai_chat.INSTALLATION_INVITATION
    assert published == expected and done == [expected]
    assert ai_chat.validate_workspace_reply(ai_chat.INSTALLATION_INVITATION) == ai_chat.INSTALLATION_INVITATION


def test_invitation_only_for_installation_questions_without_one():
    reply = "El equipo de Power Solar evalúa el techo."
    assert ai_chat.installation_invitation("¿Puedo poner placas en un techo plano?", reply)
    assert ai_chat.installation_invitation("¿Cómo deciden dónde van las placas?", reply)
    assert not ai_chat.installation_invitation("¿Qué es la medición neta?", reply)
    assert not ai_chat.installation_invitation("¿Mi techo sirve?", "Pide la evaluación en «Citas y equipo».")
    assert not ai_chat.installation_invitation("¿Mi techo sirve?", ai_chat.SAFE_REPLACEMENT)
