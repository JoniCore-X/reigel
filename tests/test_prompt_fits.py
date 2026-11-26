"""El prompt tiene que caber en la ventana que le damos al modelo.

Cuando no cabe, Ollama no avisa: recorta y contesta igual, con la mitad de sus
instrucciones. Medido el 26 de noviembre de 2026 con qwen2.5:3b, el prompt de los
borradores eran 2179 tokens contra una ventana de 2048, y el modelo leía 1026.

Estas pruebas no llaman al modelo: comparan el tamaño real de los prompts del
proyecto contra las ventanas configuradas, con la relación de caracteres por token
que se midió ese día. Su trabajo es avisar cuando el prompt vuelva a crecer.
"""
import os

import pytest

from reigel import ai_chat, assistant


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("REIGEL_CHAT_NUM_CTX", "REIGEL_IA_NUM_CTX", "REIGEL_LOCAL_NUM_CTX",
                 "REIGEL_CHAT_NUM_PREDICT", "REIGEL_IA_NUM_PREDICT", "REIGEL_LOCAL_NUM_PREDICT",
                 "REIGEL_CHAT_HISTORY", "REIGEL_IA_HISTORY"):
        monkeypatch.delenv(name, raising=False)


def size(messages):
    return sum(len(str(item.get("content", ""))) for item in messages)


def long_history(turns, length=360):
    return [{"direction": "inbound" if index % 2 == 0 else "outbound",
             "text": ("Texto de un turno anterior de la conversación. " * 20)[:length]}
            for index in range(turns)]


def test_the_chat_prompt_fits_with_a_full_history_and_the_longest_message():
    _, history, options = ai_chat._settings()
    # El peor caso real: el historial completo y un mensaje en el límite de 2000.
    messages = ai_chat.build_messages(
        "a" * 2000, long_history(history), {"municipality": "Caguas", "priority": "factura"},
        "Texto verificado de ejemplo. " * 20)
    assert ai_chat.prompt_fits(size(messages), options["num_ctx"], options["num_predict"]), (
        size(messages), options["num_ctx"])


def test_the_workspace_prompt_fits_with_its_longer_history_and_message():
    _, history, options = ai_chat._workspace_settings()
    turns = [{"role": "user" if index % 2 == 0 else "assistant",
              "text": ("Turno anterior del espacio de IA. " * 20)[:360]} for index in range(history)]
    messages = ai_chat.workspace_messages(turns, "a" * 4000, "Evidencia verificada. " * 40)
    assert ai_chat.prompt_fits(size(messages), options["num_ctx"], options["num_predict"]), (
        size(messages), options["num_ctx"])


def test_the_draft_prompt_fits_in_its_own_window():
    """Este era el caso roto: el prompt del sistema, él solo, no cabía."""
    _, options = assistant._generation_settings()
    instructions = assistant._instructions({})
    assert ai_chat.prompt_fits(len(instructions), options["num_ctx"], options["num_predict"]), (
        len(instructions), options["num_ctx"])


def test_the_windows_are_not_smaller_than_what_was_measured_as_broken():
    """Las tres ventanas que se corrigieron ese día no pueden volver a bajar."""
    assert ai_chat._settings()[2]["num_ctx"] >= 5120
    assert ai_chat._workspace_settings()[2]["num_ctx"] >= 8192
    assert assistant._generation_settings()[1]["num_ctx"] >= 4096


def test_an_operator_can_still_tune_the_window(monkeypatch):
    monkeypatch.setenv("REIGEL_LOCAL_NUM_CTX", "6144")
    assert assistant._generation_settings()[1]["num_ctx"] == 6144


def test_the_ratio_is_pessimistic_against_what_was_measured():
    """3.57 caracteres por token fue lo medido; el guardián usa 3.3 a propósito."""
    assert ai_chat.CHARS_PER_TOKEN < 3.57
    # Y el guardián rechaza lo que de verdad no cabía aquel día.
    assert not ai_chat.prompt_fits(7788, 2048, 260)
    assert ai_chat.prompt_fits(7788, 4096, 260)
