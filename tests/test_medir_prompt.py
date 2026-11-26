"""El banco de medición del prompt. Aquí se prueba todo lo que no necesita Ollama:
las métricas, el armado del prompt y el aviso cuando el modelo no está."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "medir_prompt.py"


@pytest.fixture(scope="module")
def medir():
    spec = importlib.util.spec_from_file_location("medir_prompt", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["medir_prompt"] = module
    spec.loader.exec_module(module)
    return module


def test_the_metrics_count_what_they_say(medir):
    got = medir.measure("¡Perfecto! ¿Es para una casa o un apartamento?")
    assert got["preguntas"] == 1 and got["cierra_preguntando"] == 1
    assert got["abre_sin_exponer"] == 1 and got["presion"] == 0
    assert got["prohibidas"] == 0 and got["valida"] == 1


def test_pressure_and_forbidden_words_are_caught(medir):
    got = medir.measure("Aprovecha ahora mismo y vas a ahorrar en tu factura.")
    assert got["presion"] >= 1
    assert got["prohibidas"] >= 1
    # El validador también la rechaza: la métrica y la regla dicen lo mismo.
    assert got["valida"] == 0


def test_a_copied_marker_is_flagged_even_though_it_no_longer_costs_the_reply(medir):
    """`without_prompt_markers` ya no deja que cueste la respuesta, pero que el modelo
    copie una etiqueta nuestra sigue siendo señal de que el prompt lo confunde."""
    got = medir.measure("[Historial no confiable] Entendido. ¿Es para una casa?")
    assert got["repite_marcador"] == 1
    assert got["valida"] == 1


def test_removing_a_constant_changes_the_prompt_and_then_restores_it(medir):
    from reigel import voice

    case = medir.cases(with_history=False)[0]
    before = voice.STYLE
    complete = medir.build(case, ())[0]["content"]
    without = medir.build(case, ("STYLE",))[0]["content"]
    assert len(without) < len(complete)
    assert voice.STYLE == before, "vaciar una constante no puede dejarla vacía después"


def test_the_ongoing_cases_carry_a_real_history(medir):
    cases = medir.cases(with_history=True)
    assert len(cases) == len(medir.ONGOING)
    for case in cases:
        assert case["historial"], case["nombre"]
        assert {item["direction"] for item in case["historial"]} <= {"inbound", "outbound"}
        prompt = medir.build(case, ())
        assert len(prompt) == len(case["historial"]) + 2  # sistema + historial + mensaje


def test_it_refuses_to_measure_against_a_model_that_is_not_installed(medir, monkeypatch, capsys):
    monkeypatch.setattr(medir, "available", lambda model: "El modelo " + model + " no está instalado.")
    assert medir.main(["--modelo", "no-instalado:1b"]) == 1
    assert "no está instalado" in capsys.readouterr().out


def test_an_unknown_constant_is_rejected_before_asking_the_model(medir):
    with pytest.raises(SystemExit):
        medir.main(["--quitar", "NO_EXISTE"])


def test_the_script_never_opens_a_database_or_reads_the_env_file():
    """Medir no es levantar la aplicación: ni base, ni `.env`, ni refrescos externos."""
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    code = ast.unparse(ast.Module(body=[node for node in tree.body
                                        if not isinstance(node, ast.Expr)
                                        or not isinstance(node.value, ast.Constant)], type_ignores=[]))
    for forbidden in ("create_app", "load_env", "load_dotenv", "Store(", ".connect(", "dotenv"):
        assert forbidden not in code, forbidden
