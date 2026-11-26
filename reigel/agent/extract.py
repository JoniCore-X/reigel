"""Extracción de creencias: lo que una conversación deja en la memoria del agente.

Hasta aquí la memoria la escribía una persona. Esto la llena sola, con una regla
dura: **solo se extrae con patrones, nunca con el modelo**, y lo que se guarda no
es el texto del visitante sino una frase fija escrita de antemano. Dos razones, y
las dos son de seguridad, no de estilo:

1. Un texto escrito por un visitante que entra en la memoria vuelve al modelo en
   la siguiente respuesta. Guardar frases fijas y dejar el texto original en la
   conversación cierra esa vía: la memoria no transporta nada que el visitante
   haya redactado, así que no puede llevar instrucciones ni datos personales.
2. Lo que se extrae hay que poder auditarlo. Un patrón se lee, se prueba y se
   discute; la deducción de un modelo, no.

La procedencia la declara cada patrón y decide si la creencia sirve para hablar:

- Lo que la persona contestó a una pregunta directa del chat llega como
  `lead_said`: el vocabulario es cerrado (municipios de una lista, importes
  numéricos, etiquetas fijas), así que repetirlo no interpreta nada.
- Una negativa literal («no me llamen») también es `lead_said`. No hace falta
  leer entre líneas y tiene que llegar al plan de llamada, que solo muestra lo
  usable.
- Todo lo demás entra como `pattern`: lo leyó un patrón, no lo afirmó la persona
  y no lo dedujo ningún modelo. No se usa al hablar hasta que alguien lo aprueba.

Nada se extrae de una baja comercial ni de una solicitud de privacidad, y nada se
guarda sin un registro al que atarlo: una creencia sin ficha no tiene dueño.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime

from . import memory

LIMIT = 4  # cuántas creencias puede dejar un mensaje, para que no inunde la ficha
CONFIRMED_CONFIDENCE = 0.9


def _plain(value) -> str:
    """Sin tildes y en minúsculas, como `normalized` en el chat: los patrones se
    escriben una sola vez y no en dos variantes por acento."""
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _same(left, right) -> bool:
    return " ".join(_plain(left).split()) == " ".join(_plain(right).split())


# --- Lo que la persona contestó a una pregunta directa -------------------------
# El chat pregunta, clasifica la respuesta y la guarda en el perfil con
# vocabulario cerrado. Estas creencias repiten esa respuesta, no la interpretan.
PRIORITY_CLAIMS = {
    "factura": "Busca bajar la factura eléctrica.",
    "respaldo": "Busca respaldo para los apagones.",
    "factura y respaldo": "Busca bajar la factura y tener respaldo.",
}


def from_profile(profile) -> list[dict]:
    """Creencias a partir de lo que el visitante ya contestó en el chat."""
    profile = profile if isinstance(profile, dict) else {}
    found = []

    def add(subject, claim):
        found.append({"subject": subject, "claim": claim, "source_kind": "lead_said",
                      "confidence": CONFIRMED_CONFIDENCE})

    priority = PRIORITY_CLAIMS.get(str(profile.get("priority") or "").strip().casefold())
    if priority:
        add("motivo", priority)
    municipality = profile.get("municipality")
    if municipality:
        add("ubicacion", f"Está en {municipality}.")
    period = profile.get("bill_period")
    amount = profile.get("monthly_bill", profile.get("bill_amount"))
    if period == "monthly" and amount is not None:
        add("consumo", f"Su factura mensual ronda los {float(amount):.0f} dólares.")
    elif period == "annual" and amount is not None:
        add("consumo", f"Dio {float(amount):.0f} dólares como importe anual, no mensual.")
    elif period == "declined":
        add("consumo", "Prefirió no compartir el importe de su factura.")
    loads = profile.get("backup_loads")
    if isinstance(loads, (list, tuple)) and loads:
        add("respaldo", "Quiere respaldar: " + ", ".join(str(item) for item in loads)[:200] + ".")
    return found


# --- Lo que un patrón lee en el texto libre ------------------------------------
# Cada entrada es (asunto, patrón, afirmación, procedencia, confianza). La
# afirmación es siempre fija: nunca se guarda lo que escribió el visitante.
PATTERNS = (
    ("contacto", r"\bno (?:me |nos |les )?(?:llame|llamen|llames|llamar|llamaran)\b"
                 r"|\bno quiero (?:que me )?llam|\bsin llamadas\b|\bnada de llamadas\b",
     "Pidió que no la llamen por teléfono.", "lead_said", 0.95),
    ("contacto", r"\b(?:por|via) whatsapp\b|\bmejor por (?:texto|mensaje|escrito)\b"
                 r"|\bescribe?me\b|\bescribanme\b",
     "Prefiere que le escriban por mensaje antes que llamarla.", "lead_said", 0.9),
    ("vivienda", r"\b(?:alquil|rent)(?:o|a|ada|ado|amos|ando)\b|\bsoy inquilin",
     "Dice que la vivienda es alquilada.", "pattern", 0.7),
    ("vivienda", r"\b(?:casa propia|es mi casa|la casa es mia|casa es nuestra)\b",
     "Dice que la casa es propia.", "pattern", 0.7),
    ("vivienda", r"\bapartament",
     "Habla de un apartamento, no de una casa.", "pattern", 0.6),
    ("decisor", r"\btengo que (?:hablar|consultar|preguntar)\b|\b(?:lo|la) decide\b"
                r"|\bdecidimos (?:entre|junto)|\bno decido (?:yo )?sol",
     "Hay otra persona que participa en la decisión.", "pattern", 0.6),
    ("plazo", r"\b(?:cuanto antes|ya mismo|lo antes posible|esta semana|este mes)\b|\burgente\b",
     "Quiere resolverlo pronto.", "pattern", 0.6),
    ("plazo", r"\bno tengo (?:prisa|apuro)\b|\bmas adelante\b|\b(?:el |al )?(?:ano|proximo ano) que viene\b"
              r"|\bsolo (?:estoy )?(?:preguntando|mirando)\b",
     "No tiene prisa: está explorando.", "pattern", 0.6),
    ("historial", r"\bya tengo (?:placas|paneles|sistema|solar)\b|\bme (?:instalaron|instalo)\b"
                  r"|\botra compania\b|\bya me (?:hicieron|cotizaron)\b",
     "Ya tuvo una instalación o trató con otra compañía.", "pattern", 0.6),
    # La objeción. Cinco objeciones distintas piden cinco respuestas distintas, así
    # que cada una lleva su patrón y no se resumen en «tiene dudas». El orden va de
    # la que menos se puede confundir a la que más: el primer patrón gana el asunto.
    ("objecion", r"\bno (?:tengo|hay) credito\b|\bmi credito\b|\bno cualific",
     "Le preocupa calificar para el financiamiento.", "pattern", 0.7),
    ("objecion", r"\b(?:voy a |pienso )?vender la casa\b|\bme voy a mudar\b|\bnos mudamos\b",
     "Puede que no se quede en esa vivienda.", "pattern", 0.7),
    ("objecion", r"\b(?:muy |bien |demasiado )?caro\b|\bno me da el presupuesto\b"
                 r"|\bno puedo pagar\b|\bfuera de mi presupuesto\b",
     "El precio le parece alto.", "pattern", 0.65),
    ("objecion", r"\bme (?:quedo|dejaron) mal\b|\bmala experiencia\b|\bme (?:estafaron|enganaron)\b"
                 r"|\bno me (?:fio|confio)\b|\bya me fallaron\b",
     "Desconfía por una experiencia anterior.", "pattern", 0.6),
    ("objecion", r"\bno vale la pena\b|\bno (?:se|estoy seguro) si (?:sirve|funciona|conviene)\b"
                 r"|\bde verdad (?:ahorra|funciona)\b",
     "Duda de que el sistema le convenga.", "pattern", 0.5),
)


def from_message(message) -> list[dict]:
    """Creencias que los patrones leen en el texto libre del visitante.

    Un asunto no se repite: el primer patrón que acierta gana, y los patrones
    están en orden de cuánto afirman.
    """
    value = " ".join(_plain(message).split())
    if not value:
        return []
    found, seen = [], set()
    for subject, pattern, claim, source_kind, confidence in PATTERNS:
        if subject in seen or not re.search(pattern, value):
            continue
        seen.add(subject)
        found.append({"subject": subject, "claim": claim,
                      "source_kind": source_kind, "confidence": confidence})
    return found


def candidates(message, profile=None, *, limit=LIMIT) -> list[dict]:
    """Lo que esta vuelta de conversación deja como memoria, sin tocar la base."""
    items, seen = [], set()
    for item in from_profile(profile) + from_message(message):
        if item["subject"] in seen:
            continue
        seen.add(item["subject"])
        items.append(item)
    return items[:limit]


# Qué procedencia puede sustituir a cuál. Una lectura mía no pisa lo que la
# persona contestó ni lo que escribió el equipo: así la memoria no deriva.
AUTHORITY = {"verified": 4, "team_entered": 3, "lead_said": 2, "record": 1,
             "pattern": 1, "inferred": 0}


def _known(store, lead_id, now):
    """Lo vigente por asunto y lo que alguien ya retiró.

    Hace falta lo segundo: si solo se mirara lo vigente, el mismo patrón volvería a
    crear en el mensaje siguiente justo la creencia que una persona acababa de
    retirar, y «Retirar» no sostendría nada.
    """
    with store.connect() as db:
        rows = [memory.view(row, now) for row in db.execute(memory.HISTORY, (lead_id,))]
    current, refused = {}, set()
    for row in rows:  # HISTORY viene de lo más nuevo a lo más viejo
        if row["state"] == "active" and row["subject"] not in current:
            current[row["subject"]] = row
        elif row["state"] == "retracted":
            refused.add((row["subject"], " ".join(_plain(row["claim"]).split())))
    return current, refused


def apply(store, lead_id, items, *, conversation_id=None, now=None) -> list[dict]:
    """Guarda las creencias nuevas. Omite las que ya están y las que degradarían
    lo que ya se sabe de mejor fuente."""
    if not lead_id or not items:
        return []
    now = now or datetime.now(UTC)
    current, refused = _known(store, lead_id, now)
    saved = []
    for item in items:
        if (item["subject"], " ".join(_plain(item["claim"]).split())) in refused:
            continue  # alguien ya la retiró: el patrón no la resucita
        existing = current.get(item["subject"])
        if existing:
            if _same(existing["claim"], item["claim"]):
                continue  # ya lo sabe: repetirlo solo alargaría la cadena
            if AUTHORITY.get(item["source_kind"], 0) < AUTHORITY.get(existing["source_kind"], 0):
                continue  # una lectura mía no sustituye una respuesta suya
        saved.append(memory.record(store, lead_id, {
            "subject": item["subject"], "claim": item["claim"],
            "source_kind": item["source_kind"], "confidence": item["confidence"],
            "source_ref": conversation_id or "",
        }, None, now=now))
    return saved


def context(conversation, profile, message) -> dict | None:
    """Lo que hace falta para extraer, recogido dentro de la transacción del chat.

    Devuelve `None` cuando no hay nada que atar: sin ficha no hay memoria.
    """
    lead_id = conversation["lead_id"] if conversation is not None else None
    if not lead_id:
        return None
    items = candidates(message, profile)
    if not items:
        return None
    return {"lead_id": lead_id, "conversation_id": conversation["id"], "items": items}
