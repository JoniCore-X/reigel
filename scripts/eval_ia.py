r"""Banco de preguntas de /ia contra Ollama local, en una base temporal.

Uso: .\.venv\Scripts\python.exe scripts\eval_ia.py [--model qwen2.5:3b] [--output resultados.json]

- Usa las mismas instrucciones del sistema que /ia (``ai_chat.stream_workspace``)
  y la misma frontera de publicación que la ruta (``ai_chat.WorkspaceOutput``,
  mediante ``learning_eval.run_bank``).
- Nunca lee ``.env`` ni abre la base comercial: crea una base temporal, guarda en
  ella la corrida y la borra al salir. ``--output`` conserva una copia en JSON.
  Para guardar la corrida en la base de R.E.I.G.E.L., usa «Aprendizaje» en /app.
- No descarga modelos. Si Ollama no responde o el modelo no está instalado,
  termina con un mensaje claro y código 2.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _ollama_models(base_url):
    import httpx

    response = httpx.get(base_url + "/api/tags", timeout=3, trust_env=False, follow_redirects=False)
    response.raise_for_status()
    return [item.get("name") for item in response.json().get("models", []) if isinstance(item, dict)]


def _print_case(item):
    mark = ("PASA" if item["ok"] else "FALLA") + (" · sustituida" if item["replaced"] else "")
    print(f"[{mark}] {item['case_id']}", flush=True)


async def run(model, output):
    from reigel.core import Store
    from reigel.knowledge import KnowledgeBase
    from reigel.learning import LearningQueue
    from reigel.learning_eval import run_bank

    with tempfile.TemporaryDirectory(prefix="reigel-eval-") as folder:
        store = Store(Path(folder) / "eval.sqlite3")
        knowledge = KnowledgeBase(store)  # vacía: sin red ni refresco
        queue = LearningQueue(store)
        run_row = await run_bank(queue, knowledge, progress=_print_case)

    results = run_row["results"]
    print()
    print(f"Modelo: {model} (Ollama local). Base temporal, ya eliminada.")
    print(run_row["summary"])
    for item in results:
        if item["ok"] and not item["replaced"]:
            continue
        print()
        state = "pasa con sustitución" if item["ok"] else "falla"
        print(f"--- {item['case_id']} ({state}): {item['question']}")
        for failure in item["failed"]:
            extra = f" [{failure['detail']}]" if failure.get("detail") else ""
            print(f"  falla: {failure['id']} — {failure['description']}{extra}")
        if item["replaced"]:
            print(f"  la ruta sustituye la respuesta ({item['replacement_reason']})")
        print("  respuesta publicada:")
        print("  " + item["published"].replace("\n", "\n  "))
        if item["replaced"] and item["raw"]:
            print("  respuesta original del modelo (no publicada):")
            print("  " + item["raw"].replace("\n", "\n  "))
    if output:
        Path(output).write_text(json.dumps(run_row, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        print(f"\nCopia en JSON: {output}")
    return 0 if run_row["failed"] == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="Banco de preguntas de /ia contra Ollama local.")
    parser.add_argument("--model", help="Modelo local ya instalado (por defecto, el de /ia: REIGEL_CHAT_MODEL o qwen2.5:3b).")
    parser.add_argument("--output", help="Ruta opcional para guardar la corrida en JSON.")
    args = parser.parse_args()

    # Solo este proceso: activa la IA local y fija el modelo sin leer .env.
    os.environ["REIGEL_CHAT_AI"] = "local"
    if args.model:
        os.environ["REIGEL_CHAT_MODEL"] = args.model
    from reigel import ai_chat

    try:
        model = ai_chat.model_name()
    except ValueError as error:
        print(f"Modelo no válido: {error}", file=sys.stderr)
        return 2
    try:
        installed = _ollama_models(ai_chat.LOCAL_URL)
    except Exception:
        print(f"Ollama no responde en {ai_chat.LOCAL_URL}. Inícialo y vuelve a intentarlo; "
              "no se ejecutó ningún caso.", file=sys.stderr)
        return 2
    if model not in installed:
        print(f"El modelo {model} no está instalado en Ollama ({', '.join(installed) or 'ninguno'}). "
              "Este script no descarga modelos.", file=sys.stderr)
        return 2
    return asyncio.run(run(model, args.output))


if __name__ == "__main__":
    raise SystemExit(main())
