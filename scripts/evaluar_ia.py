r"""La mitad de la batería que necesita el modelo encendido.

Lo determinista —clasificación, recuperación y extracción— corre en la suite normal
(`tests/test_eval_battery.py`), sin Ollama y en cada cambio. Aquí se mide lo que solo
se puede comprobar generando: que la respuesta pase los validadores, cierre
preguntando, no se alargue y no diga lo que no debe.

    .\.venv\Scripts\python.exe scripts\evaluar_ia.py
    .\.venv\Scripts\python.exe scripts\evaluar_ia.py --particion final --json r.json
    .\.venv\Scripts\python.exe scripts\evaluar_ia.py --grupo capacidad_comercial

**Las dos particiones no son intercambiables.** Con `optimizacion` se afina: se miran
las respuestas y se vuelve a correr. `final` se reserva y se corre una vez, al terminar,
para saber si lo que se afinó sirve de verdad o solo se ajustó a lo que se estaba
mirando. Afinar contra los casos finales los gasta: dejan de medir.

No descarga modelos, no abre la base y no escribe en ninguna conversación.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("REIGEL_ENV", "local")

from reigel import ai_chat  # noqa: E402

OLLAMA = "http://127.0.0.1:11434"
CASES = json.loads((ROOT / "evaluacion" / "casos_ia.json").read_text(encoding="utf-8"))["casos"]
# Comprobaciones que necesitan una respuesta generada.
MODEL_CHECKS = ("respuesta_valida", "cierra_preguntando", "maximo_palabras", "no_debe_contener")


def needs_model(case):
    return any(key in case["espera"] for key in MODEL_CHECKS)


def available(model):
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=8) as response:
            names = [item.get("name") for item in json.load(response).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return "Ollama no responde en " + OLLAMA + ". Arráncalo antes de evaluar."
    if model not in names:
        return "El modelo " + model + " no está instalado."
    return None


def ask(messages, model, temperature, seed, timeout):
    options = {"temperature": temperature, "num_predict": 220, "num_ctx": 5120}
    if seed is not None:
        options["seed"] = seed
    body = json.dumps({"model": model, "messages": messages, "stream": False,
                       "options": options, "keep_alive": "10m"}).encode("utf-8")
    request = urllib.request.Request(OLLAMA + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return " ".join(str(payload.get("message", {}).get("content", "")).split())


def check(case, text):
    """Devuelve {comprobación: aprobada}. Solo lo que el caso pide."""
    expected = case["espera"]
    results = {}
    if "respuesta_valida" in expected:
        try:
            ai_chat.validate_reply(text)
            passed = True
            reason = ""
        except ValueError as problem:
            passed, reason = False, str(problem)
        results["respuesta_valida"] = (passed == expected["respuesta_valida"], reason)
    if "cierra_preguntando" in expected:
        results["cierra_preguntando"] = (text.rstrip().endswith("?") == expected["cierra_preguntando"], "")
    if "maximo_palabras" in expected:
        words = len(text.split())
        results["maximo_palabras"] = (words <= expected["maximo_palabras"], f"{words} palabras")
    if "no_debe_contener" in expected:
        hits = [pattern for pattern in expected["no_debe_contener"]
                if re.search(pattern, text, re.I | re.M)]
        results["no_debe_contener"] = (not hits, ", ".join(hits))
    return results


def _retriever():
    """La misma recuperación que usa `webchat.ai_brief`: corporativa más técnica, y
    solo lo que esté «verified». Base temporal: no se toca ninguna conversación."""
    import tempfile

    from reigel.core import Store
    from reigel.knowledge import KnowledgeBase

    base = KnowledgeBase(Store(str(Path(tempfile.mkdtemp()) / "evaluacion.db")))

    def evidence(message):
        corporate = base.answer(message)
        technical = base.answer_technical(message)
        parts = [part for part in (
            corporate.get("text", "") if isinstance(corporate, dict) else "",
            technical.get("text", "") if isinstance(technical, dict)
            and technical.get("status") == "verified" else "",
        ) if part]
        return " ".join(parts)

    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evalúa la IA contra la batería de casos.")
    parser.add_argument("--particion", choices=("optimizacion", "final"), default="optimizacion")
    parser.add_argument("--grupo", help="evaluar solo un grupo")
    parser.add_argument("--modelo", default="qwen2.5:3b")
    parser.add_argument("--temperatura", type=float, default=0.2)
    parser.add_argument("--semilla", type=int, default=7, help="-1 para no fijarla")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json", metavar="RUTA", help="guardar respuestas y resultados")
    options = parser.parse_args(argv)
    seed = None if options.semilla is not None and options.semilla < 0 else options.semilla

    selected = [case for case in CASES
                if needs_model(case) and case["particion"] == options.particion
                and (not options.grupo or case["grupo"] == options.grupo)]
    if not selected:
        print("No hay casos que evaluar con esos filtros.")
        return 1
    problem = available(options.modelo)
    if problem:
        print(problem)
        return 1
    if options.particion == "final":
        print("PARTICIÓN FINAL: córrela una vez y no afines contra ella.\n")
    print(f"modelo {options.modelo} · partición {options.particion} · {len(selected)} casos")

    # El prompt tiene que armarse como en producción, con la evidencia que el chat
    # recupera para ese mensaje. Sin esto se mediría un sistema que no existe: uno al
    # que nunca le llega una fuente, y al que el validador le rechaza cualquier
    # explicación técnica con toda la razón.
    evidence = _retriever()

    rows = []
    started = time.monotonic()
    for index, case in enumerate(selected):
        messages = ai_chat.build_messages(case["mensaje"], [], case.get("perfil") or {},
                                          evidence(case["mensaje"]))
        text = ask(messages, options.modelo, options.temperatura,
                   None if seed is None else seed + index, options.timeout)
        rows.append({**case, "texto": text, "resultado": check(case, text)})
        print(".", end="", flush=True)
    elapsed = time.monotonic() - started
    print("\n")

    by_group = defaultdict(list)
    for row in rows:
        by_group[row["grupo"]].append(row)
    print("grupo".ljust(28) + "casos".rjust(7) + "sin fallo".rjust(12) + "comprobaciones".rjust(16))
    for group, group_rows in sorted(by_group.items()):
        clean = sum(1 for row in group_rows if all(ok for ok, _ in row["resultado"].values()))
        checks = [ok for row in group_rows for ok, _ in row["resultado"].values()]
        print(group.ljust(28) + str(len(group_rows)).rjust(7)
              + f"{clean}/{len(group_rows)}".rjust(12)
              + f"{sum(checks)}/{len(checks)}".rjust(16))
    every = [ok for row in rows for ok, _ in row["resultado"].values()]
    print("\nTOTAL".ljust(28) + str(len(rows)).rjust(7)
          + f"{sum(1 for r in rows if all(ok for ok, _ in r['resultado'].values()))}/{len(rows)}".rjust(12)
          + f"{sum(every)}/{len(every)}".rjust(16))
    print(f"{elapsed / len(rows):.1f} segundos por respuesta")

    failures = defaultdict(int)
    print("\n--- qué falla, y cuántas veces ---")
    for row in rows:
        for name, (ok, detail) in row["resultado"].items():
            if not ok:
                failures[name + (": " + detail if detail else "")] += 1
    for reason, total in sorted(failures.items(), key=lambda item: -item[1]):
        print(f"  {total:>3}  {reason[:110]}")
    if not failures:
        print("  nada")

    print("\n--- tres respuestas, para leerlas ---")
    for row in rows[:3]:
        print("\n» " + row["mensaje"])
        print("  " + row["texto"][:220])
    if options.json:
        Path(options.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\nguardado en " + options.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
