"""Lo que el modelo recibe como evidencia verificada.

Hay dos bases: la del sitio corporativo (`answer`) y la de temas generales con fuente
oficial citada y vigente (`answer_technical`). Hasta el 26 de noviembre de 2026 la ruta
de IA solo consultaba la primera, que está vacía, así que el modelo redactaba sin
fuente y el validador le rechazaba cualquier explicación técnica.

Alcance real, medido ese día: el modelo solo ve los mensajes que el motor no supo
clasificar, así que esto ayuda en la intersección entre «no clasificado» y «tema con
fuente», que es estrecha. Lo que no es estrecho es la consecuencia cuando ocurre.
"""
import pytest

from reigel.core import Store
from reigel.knowledge import KnowledgeBase
from reigel.webchat import WebChat


@pytest.fixture
def chat(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    store = Store(tmp_path / "verified.db")
    service = WebChat(store, KnowledgeBase(store))
    token, _ = service.start()
    return service, token


def test_a_curated_topic_reaches_the_model_as_verified_evidence(chat):
    service, token = chat
    # No lo clasifica el motor, pero el recuperador técnico sí lo reconoce.
    brief = service.ai_brief(token, "Oye y si se va la luz que pasa con eso", "verif-001")
    assert brief, "el mensaje debería llegar al modelo"
    assert brief["verified"], "y con la evidencia que sí existe para ese tema"
    assert "inversor" in brief["verified"] or "red" in brief["verified"]


def test_a_topic_without_a_source_is_never_passed_off_as_verified(chat):
    """`insufficient` es el aviso de que no hay fuente. Pasarlo como evidencia sería
    justo lo contrario de lo que significa."""
    service, token = chat
    # Cuántos paneles necesita una casa concreta: ninguna fuente general lo contesta,
    # y por eso este tema sigue absteniéndose aunque otros ganaran fuente.
    answer = service.knowledge.answer_technical("cuantos paneles necesita mi casa")
    assert answer and answer["status"] == "insufficient"
    brief = service.ai_brief(token, "y lo de cuantos paneles como va la cosa", "verif-002")
    if brief:
        assert answer["text"] not in brief["verified"]


def test_a_message_with_no_matching_topic_still_gets_no_evidence(chat):
    service, token = chat
    brief = service.ai_brief(token, "Tengo una duda sobre la lluvia y mi tejado", "verif-003")
    assert brief and brief["verified"] == ""


def test_the_curated_topics_that_are_usable_all_carry_a_citation():
    """Trazabilidad: ningún tema puede estar «verified» sin su fuente."""
    from reigel import knowledge

    usable = [name for name, spec in knowledge.TECHNICAL_TOPICS.items()
              if spec["status"] == "verified"]
    assert usable, "la base no puede quedarse sin temas utilizables"
    for name in usable:
        sources = knowledge.TECHNICAL_TOPICS[name]["source_ids"]
        assert sources, name
        for source_id in sources:
            source = knowledge.TECHNICAL_SOURCES[source_id]
            assert source["url"].startswith("https://"), name
            assert source["organization"], name


def test_a_topic_without_sources_stays_out_of_the_usable_set():
    """No inventar para rellenar: lo que no tiene fuente se queda en revisión."""
    from reigel import knowledge

    for name, spec in knowledge.TECHNICAL_TOPICS.items():
        if not spec["source_ids"]:
            assert spec["status"] != "verified", name
