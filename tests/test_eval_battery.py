"""La parte de la batería de evaluación que no necesita el modelo.

Clasificación, recuperación de evidencia y extracción de objeciones son deterministas:
se comprueban en cada cambio, rápido y sin Ollama. Lo que sí necesita el modelo vive en
`scripts/evaluar_ia.py`, porque depende de una máquina con Ollama encendido.

Las dos particiones corren aquí: en lo determinista no hay nada que afinar mirando los
resultados, así que no se gastan. En el modelo sí, y por eso allí van separadas.
"""
import json
from pathlib import Path

import pytest

from reigel.agent import extract
from reigel.conversation import classify_message, normalize
from reigel.core import Store
from reigel.knowledge import KnowledgeBase

CASES = json.loads((Path(__file__).resolve().parent.parent / "evaluacion" / "casos_ia.json")
                   .read_text(encoding="utf-8"))["casos"]
GROUPS = {"precision_tecnica", "deteccion_objeciones", "seguridad", "ambiguo",
          "seguimiento_instrucciones", "coherencia", "capacidad_comercial"}


def by(key):
    return [case for case in CASES if key in case["espera"]]


def ident(case):
    return case["id"] + "-" + case["mensaje"][:28]


# --- La batería como tal ------------------------------------------------------

def test_the_battery_is_large_enough_and_split():
    assert len(CASES) >= 100, len(CASES)
    partitions = {case["particion"] for case in CASES}
    assert partitions == {"optimizacion", "final"}
    final = [case for case in CASES if case["particion"] == "final"]
    assert len(final) >= 20, "la partición final tiene que poder decir algo"


def test_every_case_is_identifiable_and_checkable():
    identifiers = [case["id"] for case in CASES]
    assert len(identifiers) == len(set(identifiers)), "hay identificadores repetidos"
    for case in CASES:
        assert case["grupo"] in GROUPS, case["id"]
        assert case["mensaje"].strip(), case["id"]
        assert case["espera"], case["id"] + ": un caso sin expectativa es una opinión"


def test_every_group_has_cases_in_both_partitions():
    for group in GROUPS:
        cases = [case for case in CASES if case["grupo"] == group]
        assert cases, group
        assert {case["particion"] for case in cases} == {"optimizacion", "final"}, group


# --- Lo que se puede comprobar sin el modelo ----------------------------------

@pytest.mark.parametrize("case", by("intencion"), ids=ident)
def test_the_engine_classifies_security_and_consent_messages(case):
    assert classify_message(normalize(case["mensaje"])).intent == case["espera"]["intencion"]


@pytest.mark.parametrize("case", by("tema_tecnico"), ids=ident)
def test_the_retriever_finds_the_right_topic_with_the_right_status(tmp_path_factory, case):
    base = KnowledgeBase(Store(tmp_path_factory.mktemp("kb") / "k.db"))
    answer = base.answer_technical(case["mensaje"])
    assert answer, case["id"] + ": el recuperador no reconoció el tema"
    assert answer["topic"] == case["espera"]["tema_tecnico"]
    assert answer["status"] == case["espera"]["estado_tecnico"]
    if answer["status"] == "verified":
        assert answer["sources"], "verificado sin fuente no es verificado"


@pytest.mark.parametrize("case", by("objecion"), ids=ident)
def test_the_extractor_reads_the_objection_that_it_is(case):
    found = {item["subject"]: item["claim"] for item in extract.from_message(case["mensaje"])}
    assert "objecion" in found, case["id"] + ": no se detectó ninguna objeción"
    assert found["objecion"] == case["espera"]["objecion"]


def test_no_verified_topic_is_claimed_without_a_citation(tmp_path):
    """Trazabilidad, sobre todos los casos técnicos de una vez."""
    base = KnowledgeBase(Store(tmp_path / "k.db"))
    for case in by("tema_tecnico"):
        answer = base.answer_technical(case["mensaje"]) or {}
        if answer.get("status") == "verified":
            assert all(source["url"].startswith("https://") for source in answer["sources"])
