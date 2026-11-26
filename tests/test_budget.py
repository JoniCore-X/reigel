"""El presupuesto de tokens: qué entra en el prompt, qué se recorta y cuándo no se envía.

Lo crítico —las reglas y el mensaje de la persona— nunca se recorta. El historial se
suelta por el turno más viejo. Si ni así cabe, la ruta se niega en lugar de mandar un
prompt sin sus reglas.
"""
import logging

import pytest

from reigel import ai_chat, assistant, budget


def test_the_estimate_is_pessimistic_against_what_the_model_counted():
    """Medido el 26 nov 2026: 7788 caracteres fueron 2179 tokens con qwen2.5:3b.
    La cuenta tiene que quedar por encima, nunca por debajo."""
    assert budget.estimate("x" * 7788) >= 2179


def test_nothing_is_dropped_when_everything_fits():
    plan = budget.fit("reglas", ["uno", "dos", "tres"], "pregunta", num_ctx=4096, reply=260)
    assert plan.kept == ["uno", "dos", "tres"]
    assert plan.dropped == 0 and plan.trimmed is False and plan.overflow is False


def test_the_oldest_turns_are_the_ones_that_go():
    """Lo último dicho pesa más que lo primero: se recorta por el principio."""
    # Los tres del mismo tamaño, para que lo único que decida sea el orden.
    turns = ["uno" + "." * 797, "dos" + "." * 797, "tres" + "." * 796]
    assert len({len(turn) for turn in turns}) == 1
    plan = budget.fit("reglas " * 100, turns, "pregunta", num_ctx=1024, reply=260)
    assert plan.kept and plan.kept[-1] == turns[-1], "el turno más reciente se queda"
    assert turns[0] not in plan.kept, "el más viejo es el que sale"
    assert plan.trimmed is True


def test_the_rules_and_the_question_are_never_trimmed():
    plan = budget.fit("reglas " * 300, [], "pregunta " * 50, num_ctx=4096, reply=260)
    assert plan.overflow is False
    assert plan.critical >= budget.estimate("reglas " * 300)


def test_a_prompt_that_does_not_fit_even_empty_refuses_instead_of_shrinking(caplog):
    """Este era el caso real: el mensaje de sistema solo, contra una ventana de 2048."""
    with caplog.at_level(logging.ERROR):
        plan = budget.fit("s" * 7788, ["algo"], "pregunta", num_ctx=2048, reply=260)
    assert plan.overflow is True
    assert plan.kept == []
    assert "No se envía" in caplog.text


def test_trimming_is_written_down(caplog):
    with caplog.at_level(logging.WARNING):
        budget.fit("reglas " * 100, ["turno " * 200] * 4, "pregunta", num_ctx=1024, reply=260)
    assert "Historial recortado" in caplog.text


# --- Las tres rutas -----------------------------------------------------------

def test_the_chat_route_keeps_its_rules_and_drops_history_instead(monkeypatch):
    monkeypatch.setenv("REIGEL_CHAT_NUM_CTX", "1024")
    history = [{"direction": "inbound", "text": "mensaje largo " * 60} for _ in range(8)]
    messages, plan = ai_chat.build_messages_with_plan("¿Qué me recomiendas?", history, {})
    assert messages[0]["role"] == "system" and len(messages[0]["content"]) > 2000
    assert messages[-1]["content"].endswith("¿Qué me recomiendas?")
    assert plan.trimmed is True


def test_the_chat_route_returns_no_reply_when_the_rules_do_not_fit(monkeypatch):
    """`reply` devuelve None y /chat usa su respuesta determinista, que sí contesta."""
    import asyncio

    monkeypatch.setenv("REIGEL_CHAT_AI", "ollama")
    monkeypatch.setenv("REIGEL_CHAT_NUM_CTX", "1024")
    monkeypatch.setenv("REIGEL_CHAT_NUM_PREDICT", "400")
    assert asyncio.run(ai_chat.reply("¿Qué me recomiendas?", [], {})) is None


def test_the_workspace_keeps_the_attached_document_as_critical(monkeypatch):
    monkeypatch.setenv("REIGEL_IA_NUM_CTX", "2048")
    history = [{"role": "user", "content": "turno " * 150} for _ in range(10)]
    messages, plan = ai_chat.workspace_messages_with_plan(history, "¿Qué dice esto?")
    assert messages[0]["role"] == "system"
    assert messages[-1]["content"].endswith("¿Qué dice esto?")
    assert plan.trimmed is True


def test_the_draft_route_refuses_instead_of_drafting_without_its_rules(monkeypatch):
    import asyncio

    monkeypatch.setenv("REIGEL_LOCAL_NUM_CTX", "512")
    monkeypatch.setenv("REIGEL_LOCAL_MODEL", "qwen2.5:3b")
    with pytest.raises(ValueError, match="no cabe"):
        asyncio.run(assistant.draft("Redacta un seguimiento", {}))


def test_the_defaults_leave_every_route_with_room(monkeypatch):
    """Con la configuración que se publica, ninguna ruta debería desbordar."""
    for name in ("REIGEL_CHAT_NUM_CTX", "REIGEL_IA_NUM_CTX", "REIGEL_LOCAL_NUM_CTX"):
        monkeypatch.delenv(name, raising=False)
    history = [{"direction": "inbound", "text": "a" * 360} for _ in range(8)]
    assert ai_chat.build_messages_with_plan("a" * 2000, history, {})[1].overflow is False
    workspace = [{"role": "user", "content": "a" * 360} for _ in range(20)]
    assert ai_chat.workspace_messages_with_plan(workspace, "a" * 4000)[1].overflow is False
