"""R.E.I.G.E.L. speaks like a Team Caguas advisor on every AI route, without customer data."""
from datetime import datetime
from pathlib import Path

import pytest

from reigel import ai_chat, assistant, voice

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("hour,expected", [(6, "buenos días"), (11, "buenos días"), (12, "buenas tardes"),
                                           (18, "buenas tardes"), (19, "buenas noches"), (2, "buenas noches")])
def test_greeting_follows_puerto_rico_time(hour, expected):
    assert voice.greeting(datetime(2026, 11, 21, hour, 30, tzinfo=voice.ZONE)) == expected


def test_every_ai_route_receives_the_voice_guide():
    prompts = {
        "/ia": ai_chat.workspace_instructions(),
        "/chat": ai_chat._instructions({}, ""),
        "borradores": assistant._instructions({}),
    }
    for route, prompt in prompts.items():
        assert "casa o apartamento" in prompt, route
        assert "una sola pregunta a la vez" in prompt, route
        assert "no son datos de esta persona" in prompt, route
        assert "nunca permite prometer ahorro" in prompt, route


def test_example_replies_pass_every_output_validator():
    replies = [text for speaker, text in voice.EXAMPLE if speaker == "R.E.I.G.E.L."]
    assert len(replies) == 3
    for text in replies:
        assert ai_chat.validate_workspace_reply(text) == text
        assert ai_chat.validate_reply(text, verified=True) == text
        assert assistant.validate_draft(text) == text


def test_the_style_example_is_anonymous():
    # The owner shared a real conversation as a style model; only the style is kept:
    # no speaker names, no greeting addressed to a person by name.
    assert {speaker for speaker, _ in voice.EXAMPLE} == {"Persona", "R.E.I.G.E.L."}
    for _, text in voice.EXAMPLE:
        assert "¡Hola, buenas" not in text or text.startswith("¡Hola, buenas noches!"), text


JARGON = ("corriente continua", "corriente alterna", "corriente directa", "fotovoltaic", "fotones", "electrones",
          "viabilidad", "dimensiona", "sincroniz", "cargas conectadas")


def test_plain_language_rule_reaches_every_ai_route():
    for prompt in (ai_chat.workspace_instructions(), ai_chat._instructions({}, ""), assistant._instructions({})):
        assert "arroz y habichuela" in prompt
        assert "contesta directo, sin esas palabras" in prompt
    assert "lenguaje educativo" not in ai_chat.workspace_instructions()


def test_fixed_texts_shown_to_people_avoid_jargon():
    from reigel.knowledge import TECHNICAL_TOPICS
    texts = [topic["answer"] for topic in TECHNICAL_TOPICS.values() if "answer" in topic]
    texts.append((ROOT / "reigel" / "webchat.py").read_text(encoding="utf-8"))
    texts.append((ROOT / "frontend" / "pages" / "soluciones.html").read_text(encoding="utf-8"))
    for text in texts:
        lowered = text.lower()
        for word in JARGON:
            assert word not in lowered, (word, text[:80])


def test_glossary_gives_the_model_correct_plain_definitions():
    prompt = ai_chat.workspace_instructions()
    assert "no inventes otras definiciones" in prompt
    terms = {term for term, _ in voice.GLOSSARY}
    assert {"medición neta", "batería", "inversor", "apagón"} <= terms
    net = dict(voice.GLOSSARY)["medición neta"]
    assert "la que le devuelve" in net and "créditos" in net
    for _, meaning in voice.GLOSSARY:
        lowered = meaning.lower()
        assert not any(word in lowered for word in JARGON), meaning
