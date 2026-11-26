r"""¿Aguanta el servidor? Memoria, latencia y concurrencia del modelo local, medidas.

    .\.venv\Scripts\python.exe scripts\medir_recursos.py
    .\.venv\Scripts\python.exe scripts\medir_recursos.py --concurrencia 1 2 4 --repeticiones 6

Mide lo que decide el tamaño del servidor: cuánta memoria ocupa el modelo cargado,
cuánto tarda una respuesta y qué pasa cuando llegan varias a la vez. Esto último
importa más de lo que parece: el `compose.yaml` fija `OLLAMA_NUM_PARALLEL=1`, así que
dos visitantes simultáneos no se reparten la máquina, hacen cola.

No descarga nada, no abre la base y no escribe en ninguna conversación.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("REIGEL_ENV", "local")

from reigel import ai_chat  # noqa: E402

OLLAMA = "http://127.0.0.1:11434"
# Mensajes de longitud parecida, para que la comparación no dependa del texto.
PROBES = (
    "Cuéntame de los paneles solares para mi casa",
    "No sé si esto de verdad me conviene a mí",
    "Se me va la luz muy seguido en mi casa",
    "Estoy comparando opciones con otra compañía",
)


def post(path, payload, timeout=240):
    request = urllib.request.Request(OLLAMA + path, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def loaded():
    with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=20) as response:
        return json.load(response).get("models", [])


def generate(model, message, num_ctx):
    messages = ai_chat.build_messages(message, [], {}, None)
    started = time.monotonic()
    payload = post("/api/chat", {"model": model, "messages": messages, "stream": False,
                                 "options": {"temperature": 0.2, "num_predict": 220,
                                             "num_ctx": num_ctx},
                                 "keep_alive": "10m"})
    return {
        "segundos": time.monotonic() - started,
        "tokens_prompt": payload.get("prompt_eval_count", 0),
        "tokens_respuesta": payload.get("eval_count", 0),
    }


def percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mide memoria, latencia y concurrencia del modelo local.")
    parser.add_argument("--modelo", default="qwen2.5:3b")
    parser.add_argument("--num-ctx", type=int, default=5120)
    parser.add_argument("--repeticiones", type=int, default=5)
    parser.add_argument("--concurrencia", type=int, nargs="*", default=[1, 2, 4])
    options = parser.parse_args(argv)

    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=8) as response:
            installed = json.load(response).get("models", [])
    except (urllib.error.URLError, OSError, ValueError):
        print("Ollama no responde en " + OLLAMA + ".")
        return 1
    by_name = {item.get("name"): item for item in installed}
    if options.modelo not in by_name:
        print("El modelo " + options.modelo + " no está instalado.")
        return 1

    print("modelo " + options.modelo + " · ventana " + str(options.num_ctx) + "\n")
    print("--- almacenamiento ---")
    print(f"  el modelo en disco: {by_name[options.modelo].get('size', 0) / 1024**3:.2f} GB")
    print(f"  todos los modelos:  {sum(m.get('size', 0) for m in installed) / 1024**3:.2f} GB")

    generate(options.modelo, PROBES[0], options.num_ctx)  # cargarlo antes de medir
    print("\n--- memoria con el modelo cargado ---")
    for item in loaded():
        if item.get("name") == options.modelo:
            print(f"  {item['name']}: {item.get('size', 0) / 1024**3:.2f} GB")

    print("\n--- latencia de una respuesta a la vez ---")
    singles = [generate(options.modelo, PROBES[index % len(PROBES)], options.num_ctx)
               for index in range(options.repeticiones)]
    times = [row["segundos"] for row in singles]
    print(f"  mediana {statistics.median(times):.1f} s · p95 {percentile(times, 0.95):.1f} s"
          f" · máximo {max(times):.1f} s")
    print(f"  prompt {statistics.median(r['tokens_prompt'] for r in singles):.0f} tokens"
          f" · respuesta {statistics.median(r['tokens_respuesta'] for r in singles):.0f} tokens")

    print("\n--- varias a la vez (OLLAMA_NUM_PARALLEL=1 en el servidor: hacen cola) ---")
    print("  simultáneas".ljust(16) + "mediana".rjust(10) + "p95".rjust(10) + "máximo".rjust(10))
    for level in options.concurrencia:
        results = []
        lock = threading.Lock()

        def worker(index=0):
            row = generate(options.modelo, PROBES[index % len(PROBES)], options.num_ctx)
            with lock:
                results.append(row["segundos"])

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(level)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        print(f"  {level}".ljust(16) + f"{statistics.median(results):.1f} s".rjust(10)
              + f"{percentile(results, 0.95):.1f} s".rjust(10) + f"{max(results):.1f} s".rjust(10))

    print("\nLa latencia con varias a la vez es la que decide si el servidor aguanta:")
    print("el visitante espera su turno completo, no una fracción.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
