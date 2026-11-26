r"""¿Sirve de algo lo que acabas de añadir al prompt? Pregúntaselo al modelo, no a tu intuición.

Compara las respuestas del modelo local con y sin un trozo del prompt. No abre la base,
no lee `.env`, no descarga nada y no escribe en ninguna conversación: solo arma el prompt
real del proyecto, pregunta a Ollama y cuenta.

    .\.venv\Scripts\python.exe scripts\medir_prompt.py
    .\.venv\Scripts\python.exe scripts\medir_prompt.py --quitar STYLE --muestras 3
    .\.venv\Scripts\python.exe scripts\medir_prompt.py --historial --json medicion.json

Sin `--quitar` hace una sola pasada y dice cuántas respuestas tira el validador y por
qué; es la revisión de salud del prompt tal como está. Con `--quitar NOMBRE` vacía esa
constante de `reigel/voice.py` en la segunda variante y compara las dos.

Lo que aprendimos usándolo, el 26 nov 2026 con `qwen2.5:3b`:

- Una conducta que el prompt ya consigue el 100 % de las veces no deja margen: añadir
  otra instrucción que pida lo mismo no puede mejorarla y sí puede estorbar a la que
  funcionaba.
- `--historial` encontró lo que `--historial` no buscaba: el modelo copiaba el marcador
  «[Historial no confiable]» y el validador tiraba esas respuestas enteras.

Hace falta Ollama corriendo en 127.0.0.1:11434 con el modelo instalado. Si no está, el
script lo dice y sale; no descarga nada.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Una medición no es la aplicación: sin `.env` y con el entorno declarado a mano.
os.environ.setdefault("REIGEL_ENV", "local")

from reigel import ai_chat, voice  # noqa: E402

OLLAMA = "http://127.0.0.1:11434"

# Mensajes donde se nota una forma de responder: objeción, duda, comparación, alguien
# que quizá no encaja y alguien que solo mira. Ninguno es técnico ni trae cifras.
FIRST_MESSAGES = (
    "Me interesa pero me parece muy caro",
    "Cuéntame de los paneles solares",
    "Se me va la luz todo el tiempo en mi casa",
    "No sé si esto de verdad me conviene",
    "Estoy comparando con otra compañía",
    "Vivo en un apartamento alquilado",
    "¿Qué me recomiendas?",
    "Solo estoy mirando por ahora",
)

# Conversaciones ya empezadas: donde el prompt se pone a prueba de verdad, porque la
# persona ya contestó cosas, se resiste o repite que no quiere decidir.
ONGOING = (
    {
        "nombre": "ya contestó y ahora duda",
        "perfil": {"municipality": "Caguas", "priority": "factura"},
        "historial": (
            ("outbound", "¡Hola! ¿Es para una casa o un apartamento?"),
            ("inbound", "Para mi casa en Caguas"),
            ("outbound", "¡Perfecto! ¿Qué buscas resolver, las alzas en la factura o las interrupciones?"),
            ("inbound", "La factura, pero no sé si quiero meterme en esto ahora"),
        ),
        "mensaje": "La verdad es que no estoy seguro, tengo que pensarlo",
    },
    {
        "nombre": "insiste en el precio",
        "perfil": {"municipality": "Gurabo", "priority": "factura"},
        "historial": (
            ("inbound", "¿Cuánto cuesta?"),
            ("outbound", "El costo depende de tu consumo y del diseño; eso se ve en la evaluación."),
            ("inbound", "Ya, pero dame un estimado"),
            ("outbound", "No puedo dar cifras sin la evaluación, y prefiero no inventarte una."),
        ),
        "mensaje": "Entonces no me sirve de nada hablar contigo",
    },
    {
        "nombre": "no quiere que la presionen",
        "perfil": {"priority": "respaldo"},
        "historial": (
            ("inbound", "Se me va la luz mucho"),
            ("outbound", "Entiendo. ¿Es para una casa o un apartamento?"),
            ("inbound", "Casa, pero no quiero que me estén llamando ni presionando"),
        ),
        "mensaje": "Solo quiero información, nada más",
    },
    {
        "nombre": "probablemente no encaja",
        "perfil": {},
        "historial": (
            ("outbound", "¡Hola! ¿Es para una casa o un apartamento?"),
            ("inbound", "Un apartamento alquilado, no es mío"),
        ),
        "mensaje": "¿Igual me sirve?",
    },
)

PRESSURE = re.compile(
    r"\b(?:ahora mismo|no pierdas|oportunidad|aprovech\w*|hoy mismo|ultim\w*|limitad\w*|"
    r"no esperes|date prisa|urge\w*|ya mismo|solo por)\b", re.I)
# «ahorrar» la prohíbe `voice.STYLE`; las otras las rechaza `validate_reply`.
FORBIDDEN = re.compile(r"\b(?:ahorr\w*|garantiz\w*|asegur\w*)\b", re.I)
ABOUT_HER = re.compile(
    r"\b(?:tu casa|tu hogar|tu techo|tu factura|tu consumo|tu situaci\w*|tus |te gustar\w*|"
    r"qué buscas|que buscas|qué necesitas|que necesitas|vives|apartamento o casa|"
    r"casa o apartamento|te preocupa|tienes|cuál es tu|cual es tu|cómo es tu|como es tu)\b", re.I)

METRICS = ("palabras", "oraciones", "preguntas", "cierra_preguntando", "pregunta_por_ella",
           "abre_sin_exponer", "presion", "prohibidas", "repite_marcador", "valida")


def measure(text):
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    first = parts[0] if parts else ""
    questions = text.count("?")
    return {
        "palabras": len(text.split()),
        "oraciones": len(parts),
        "preguntas": questions,
        "cierra_preguntando": int(text.rstrip().endswith("?")),
        "pregunta_por_ella": int(bool(ABOUT_HER.search(text)) and questions > 0),
        "abre_sin_exponer": int("?" in first or len(first.split()) <= 12),
        "presion": len(PRESSURE.findall(text)),
        "prohibidas": len(FORBIDDEN.findall(text)),
        # Que el modelo copie una etiqueta nuestra es señal de que el prompt lo confunde,
        # aunque ya no le cueste la respuesta.
        "repite_marcador": int(any(text.lstrip().startswith(mark) for mark in ai_chat.PROMPT_MARKERS)),
        "valida": int(rejection(text) is None),
    }


def rejection(text):
    try:
        ai_chat.validate_reply(text)
    except ValueError as problem:
        return str(problem)
    return None


def ask(messages, model, temperature, seed, timeout):
    options = {"temperature": temperature, "num_predict": 220, "num_ctx": 3072}
    if seed is not None:
        options["seed"] = seed
    body = json.dumps({"model": model, "messages": messages, "stream": False,
                       "options": options, "keep_alive": "10m"}).encode("utf-8")
    request = urllib.request.Request(OLLAMA + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return " ".join(str(payload.get("message", {}).get("content", "")).split())


def available(model):
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=8) as response:
            names = [item.get("name") for item in json.load(response).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return "Ollama no responde en " + OLLAMA + ". Arráncalo antes de medir."
    if model not in names:
        return "El modelo " + model + " no está instalado. Instalado: " + ", ".join(n for n in names if n)
    return None


def cases(with_history):
    """Cada caso: su nombre, el historial previo, el perfil y el mensaje nuevo."""
    if with_history:
        return [{"nombre": case["nombre"], "perfil": case["perfil"], "mensaje": case["mensaje"],
                 "historial": [{"direction": direction, "text": text}
                               for direction, text in case["historial"]]}
                for case in ONGOING]
    return [{"nombre": message, "perfil": {}, "mensaje": message, "historial": []}
            for message in FIRST_MESSAGES]


def build(case, removed):
    """El prompt real del proyecto, con las constantes indicadas vaciadas."""
    saved = {name: getattr(voice, name) for name in removed}
    for name in removed:
        setattr(voice, name, "")
    try:
        return ai_chat.build_messages(case["mensaje"], case["historial"], case["perfil"], None)
    finally:
        for name, value in saved.items():
            setattr(voice, name, value)


def run(options):
    rows = []
    variants = [("completo", ())]
    if options.quitar:
        variants.append(("sin " + "+".join(options.quitar), tuple(options.quitar)))
    for case in cases(options.historial):
        for label, removed in variants:
            prompt = build(case, removed)
            for index in range(options.muestras):
                seed = None if options.semilla is None else options.semilla + index
                text = ask(prompt, options.modelo, options.temperatura, seed, options.timeout)
                rows.append({"caso": case["nombre"], "variante": label, "muestra": index,
                             "texto": text, "rechazo": rejection(text), **measure(text)})
                print(".", end="", flush=True)
    print()
    return rows, [label for label, _ in variants]


def report(rows, variants):
    print("\n=== " + str(len(rows)) + " respuestas ===")
    header = "métrica".ljust(20)
    for label in variants:
        header += label[:14].rjust(16)
    if len(variants) == 2:
        header += "dif".rjust(10)
    print(header)
    for key in METRICS:
        line = key.ljust(20)
        means = []
        for label in variants:
            group = [row[key] for row in rows if row["variante"] == label]
            means.append(statistics.mean(group) if group else 0.0)
            line += f"{means[-1]:>16.2f}"
        if len(means) == 2:
            line += f"{means[1] - means[0]:>+10.2f}"
        print(line)
    print("\n--- respuestas que el validador rechaza, y por qué ---")
    for label in variants:
        group = [row for row in rows if row["variante"] == label]
        failed = [row for row in group if row["rechazo"]]
        print("  " + label + ": " + str(len(failed)) + " de " + str(len(group)))
        for reason, total in Counter(row["rechazo"] for row in failed).most_common():
            print("      " + str(total) + "  " + reason)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compara las respuestas del modelo con y sin un trozo del prompt.")
    parser.add_argument("--quitar", nargs="*", default=[], metavar="CONSTANTE",
                        help="constantes de reigel/voice.py a vaciar en la segunda variante (p. ej. STYLE PLAIN)")
    parser.add_argument("--historial", action="store_true",
                        help="usar conversaciones ya empezadas en lugar de primeros mensajes")
    parser.add_argument("--muestras", type=int, default=1, help="generaciones por caso y variante")
    parser.add_argument("--temperatura", type=float, default=0.0,
                        help="0 con semilla fija aísla el prompt; 0.2 es la de producción")
    parser.add_argument("--semilla", type=int, default=7, help="semilla fija; usa -1 para no fijarla")
    parser.add_argument("--modelo", default="qwen2.5:3b")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json", metavar="RUTA", help="guardar las respuestas completas")
    options = parser.parse_args(argv)
    if options.semilla is not None and options.semilla < 0:
        options.semilla = None
    unknown = [name for name in options.quitar if not isinstance(getattr(voice, name, None), str)]
    if unknown:
        parser.error("no son constantes de texto de reigel/voice.py: " + ", ".join(unknown))

    problem = available(options.modelo)
    if problem:
        print(problem)
        return 1
    total = len(cases(options.historial)) * (2 if options.quitar else 1) * options.muestras
    print("modelo " + options.modelo + " · " + str(total) + " generaciones")
    rows, variants = run(options)
    report(rows, variants)
    if options.json:
        Path(options.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\nrespuestas completas en " + options.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
