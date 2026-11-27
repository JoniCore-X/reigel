"""Las respuestas de venta del motor determinista.

Hasta el 26 de noviembre de 2026 precio, descuento, garantía y financiación recibían
el mismo párrafo. Ahora cada una contesta a lo que le preguntaron. Ninguna promete, y
eso se comprueba aquí: lo que cambia es el tono y el destino, nunca lo que se afirma.
"""
import re

import pytest

from reigel.conversation import classify_message, normalize
from reigel.core import Store
from reigel.knowledge import KnowledgeBase
from reigel.webchat import WebChat

PREGUNTAS = {
    "¿Cuánto cuesta un sistema completo?": "precio",
    "¿Cuál es el precio por panel?": "precio",
    "¿Qué descuento me pueden hacer?": "oferta",
    "¿Hay alguna promoción ahora?": "oferta",
    "¿Me dan garantía de por vida?": "garantia",
    "¿Qué garantía tienen los equipos?": "garantia",
    "¿Tienen financiamiento sin intereses?": "financiacion",
    "¿Me garantizan que bajará mi factura?": "ahorro",
}


@pytest.fixture
def chat(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    store = Store(tmp_path / "comercial.db")
    service = WebChat(store, KnowledgeBase(store))
    return service


def answer(service, message, index):
    token, _ = service.start()
    result = service.message(token, message, f"com-{index:04d}-aaaa")
    return next(item["text"] for item in reversed(result["messages"])
                if item["direction"] == "outbound")


@pytest.mark.parametrize("message,expected", PREGUNTAS.items())
def test_each_question_gets_the_answer_to_that_question(chat, message, expected):
    intent = classify_message(normalize(message)).intent
    assert intent in {"commercial_terms", "financing", "guaranteed_savings"}, (message, intent)
    assert WebChat._commercial_reply(intent, normalize(message)) == WebChat.COMMERCIAL_REPLIES[expected]


def test_the_four_answers_are_actually_different(chat):
    replies = {answer(chat, message, index) for index, message in enumerate(PREGUNTAS)}
    assert len(replies) >= 4, "volvieron a ser la misma respuesta para todo"


@pytest.mark.parametrize("message", list(PREGUNTAS))
def test_no_commercial_answer_promises_anything(chat, message):
    reply = answer(chat, message, 100 + len(message))
    assert not re.search(r"\d", reply), reply
    # «garantía» puede nombrarse; «garantizamos» no. Y nada de hablar por el equipo.
    assert not re.search(r"\bgarantiz\w*\b", reply.lower()), reply
    assert not re.search(r"\bahorr\w*\b", reply.lower()), reply
    assert not re.search(r"\b(?:nosotros|ofrecemos|instalamos|hacemos|calculamos)\b",
                         reply.lower()), reply


@pytest.mark.parametrize("message", list(PREGUNTAS))
def test_every_commercial_answer_keeps_the_conversation_open(chat, message):
    """Una objeción contestada y sin pregunta es una conversación que se apaga."""
    reply = answer(chat, message, 200 + len(message))
    assert reply.rstrip().endswith("?"), reply


def test_the_savings_question_is_refused_and_says_why(chat):
    reply = answer(chat, "¿Me garantizan que bajará mi factura?", 300)
    assert "no te lo puedo prometer" in reply.lower()
    assert "desconf" in reply.lower(), "la respuesta honesta también protege de quien sí promete"
