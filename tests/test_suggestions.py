"""Suggestion engine for /ia: curated catalog, diversity, memory and privacy."""
import re

import pytest
from fastapi.testclient import TestClient

from reigel import suggestions
from reigel.api import create_app

# Words that would make R.E.I.G.E.L. reject its own answer or break the plain-language rule.
FORBIDDEN = re.compile(
    r"\d|%|\$|ahorr|precio|cu[aá]nto cuesta|apr\b|rentab|recuperaci|mppt|monocristal|policristal|lfp|"
    r"corriente (?:continua|alterna|directa)|fotovoltaic|revisar(?:lo)? (?:mi|el) contrato|necesitas de mi factura",
    re.I,
)


def test_catalog_is_large_unique_and_within_the_rules():
    catalog = suggestions.CATALOG
    assert len(catalog) >= 100
    assert len({item.id for item in catalog}) == len(catalog)
    assert len({item.text.casefold() for item in catalog}) == len(catalog)
    assert {item.level for item in catalog} == set(suggestions.LEVELS)
    for item in catalog:
        assert not FORBIDDEN.search(item.text), item.text
        assert item.tags, item.id


def test_six_different_suggestions_from_six_categories():
    picked = suggestions.select(seed="demo")
    assert len(picked) == 6
    assert len({item.id for item in picked}) == 6
    assert len({item.category for item in picked}) == 6


def test_rounds_do_not_repeat_what_was_shown():
    seen, shown = [], []
    for round_number in range(4):
        picked = suggestions.select(seen=seen, seed=f"demo:{round_number}")
        shown.extend(item.id for item in picked)
        seen.extend(item.id for item in picked)
    assert len(shown) == len(set(shown)) == 24


def test_questions_already_asked_are_never_suggested():
    asked = suggestions.CATALOG[0].text
    messages = [{"role": "user", "content": asked}, {"role": "assistant", "content": "Respuesta."}]
    for seed in ("a", "b", "c", "d"):
        assert asked not in [item.text for item in suggestions.select(messages, seed=seed)]


def test_when_everything_was_shown_it_starts_over_instead_of_going_empty():
    everything = [item.id for item in suggestions.CATALOG]
    assert len(suggestions.select(seen=everything, seed="x")) == 6


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    return TestClient(create_app(tmp_path / "suggest.db"))


def test_endpoint_returns_six_and_respects_seen(client):
    client.get("/api/ia/bootstrap")
    first = client.get("/api/ia/suggestions").json()["suggestions"]
    assert len(first) == 6
    second = client.get("/api/ia/suggestions", params={"seen": ",".join(item["id"] for item in first)}).json()["suggestions"]
    assert not {item["id"] for item in first} & {item["id"] for item in second}


def test_endpoint_never_reads_someone_elses_conversation(client, tmp_path):
    client.get("/api/ia/bootstrap")
    mine = client.post("/api/ia/conversations", json={}).json()["conversation"]["id"]
    assert client.get("/api/ia/suggestions", params={"conversation_id": mine}).status_code == 200
    stranger = TestClient(client.app)
    stranger.get("/api/ia/bootstrap")
    assert stranger.get("/api/ia/suggestions", params={"conversation_id": mine}).status_code == 404


@pytest.mark.parametrize("text,expected,unexpected", [
    ("Tengo muchos apagones", "apagon", "factura"),
    ("Se fue la luz y quiero mantener la nevera", "apagon", "mantenimiento"),
    ("Quiero compartir esto con mi esposa", None, "comparar"),
    ("Pago mucho de luz", "factura", "apagon"),
])
def test_topic_detection_uses_whole_words(text, expected, unexpected):
    tags = suggestions.build_context([{"role": "user", "content": text}]).tags
    if expected:
        assert tags[expected] > 0
    assert tags[unexpected] == 0


def talk(*texts):
    messages = []
    for text in texts:
        messages += [{"role": "user", "content": text}, {"role": "assistant", "content": "Respuesta."}]
    return messages


def test_first_round_starts_with_basic_questions():
    assert all(item.level == "basico" for item in suggestions.select(seed="inicio"))


@pytest.mark.parametrize("text,tag", [
    ("¿Qué pasa con la casa en un apagón?", "apagon"),
    ("No entiendo mi factura de LUMA", "factura"),
    ("Mi techo tiene mucha sombra", "techo"),
])
def test_suggestions_follow_the_conversation_and_stay_diverse(text, tag):
    picked = suggestions.select(talk(text), seed="contexto")
    assert tag in picked[0].tags
    assert sum(tag in item.tags for item in picked) >= 2
    assert len({item.category for item in picked}) == 6


def test_recent_topic_outweighs_an_older_one():
    picked = suggestions.select(talk("Mi techo es viejo", "¿Y qué pasa en un apagón?"), seed="reciente")
    assert "apagon" in picked[0].tags


def test_depth_grows_with_the_conversation():
    early = suggestions.select(talk("Hola"), seed="nivel")
    late = suggestions.select(talk("Hola", "Sigo", "Cuéntame", "Otra", "Más"), seed="nivel")
    rank = {level: index for index, level in enumerate(suggestions.LEVELS)}
    assert sum(rank[item.level] for item in late) > sum(rank[item.level] for item in early)


def test_a_situation_is_only_tagged_with_what_it_talks_about():
    roof = next(item for item in suggestions.CATALOG if item.text.startswith("Mi techo es pequeño"))
    assert "techo" in roof.tags and "apagon" not in roof.tags and "factura" not in roof.tags
    picked = suggestions.select(talk("¿Qué pasa con la casa en un apagón?"), seed="ver")
    assert roof not in picked[:3]


def test_no_button_invites_hands_on_or_damage_advice():
    # With the real model these produced unsafe or false answers that a word filter cannot judge.
    risky = re.compile(r"limpiar|se da[ñn]a|fallando|despu[eé]s de una tormenta|cu[aá]nto mantenimiento|revisar de vez", re.I)
    assert not [item.text for item in suggestions.CATALOG if risky.search(item.text)]
