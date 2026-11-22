"""Motor de sugerencias de /ia: catálogo curado, contexto, diversidad y memoria.

Origen: propuesta del titular de 160 preguntas (22 nov 2026). Se conservan las
que R.E.I.G.E.L. puede contestar dentro de sus reglas (palabras sencillas, sin
cifras, sin ahorro, sin pedir documentos, sin revisar contratos), reescritas en
lenguaje de todos los días. Las excluidas y el motivo están en
docs/TEAM_CAGUAS_IMPLEMENTATION.md. La selección es determinista: no gasta
tokens del modelo y no inventa preguntas.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

# Etiquetas de contexto y las palabras que las delatan en la conversación.
TOPICS = {
    "apagon": r"apag[oó]n|se va la luz|se fue la luz|hurac[aá]n|tormenta|emergencia|respaldo|generador",
    "bateria": r"bater[ií]a|guardar|almacen",
    # Palabras completas: «apagones» contiene «pago», «mantener» no es mantenimiento
    # y «compartir» no es comparar.
    "factura": r"factura|\bluma\b|\bpag(?:o|os|ar|as|ando)\b|cuenta de luz|\bcargos?\b|\bkwh\b|consumo|\bgast",
    "techo": r"techo|concreto|sombra|[aá]rbol|espacio|estructura",
    "placas": r"placa|panel|paneles",
    "inversor": r"inversor|microinversor",
    "medicion": r"medici[oó]n neta|contador|devolv|devuelv|cr[eé]dito",
    "contrato": r"contrato|firmar|financ|arrend|propuesta|cotizaci[oó]n|plazo|mensualidad",
    "mantenimiento": r"mantenimiento|limpi|garant[ií]a|aver[ií]a|\bdañ|\bdano\b|\bfall(?:a|an|ando)\b",
    "instalacion": r"instala|permiso|monitore|aplicaci[oó]n",
    "comparar": r"\bcompar(?:o|a|as|ar|ando|aci[oó]n)\b|diferencia|\bmejor\b|conviene|versus|\bvs\b",
}

LEVELS = ("basico", "intermedio", "profundo")


@dataclass(frozen=True)
class Suggestion:
    id: str
    category: str
    level: str
    intent: str
    text: str
    tags: tuple


# (categoría, etiquetas de la categoría, [(nivel, intención, texto), …])
_CATALOG = (
    ("introduccion", ("placas",), (
        ("basico", "aprender", "¿Cómo funciona un sistema solar en una casa?"),
        ("basico", "aprender", "Explícame la energía solar como si nunca hubiera escuchado de ella."),
        ("basico", "aprender", "¿Qué equipos necesita una casa para usar energía solar?"),
        ("basico", "aprender", "¿Qué pasa desde que el sol toca una placa hasta que prendo el televisor?"),
        ("basico", "aprender", "¿Puedo usar energía solar de día y de noche?"),
        ("intermedio", "aprender", "¿Qué diferencia hay entre producir, guardar y usar la luz?"),
        ("intermedio", "aprender", "¿Por qué una instalación solar necesita varios equipos?"),
        ("intermedio", "preparar", "¿Qué errores comete la gente al empezar a averiguar de energía solar?"),
    )),
    ("funcionamiento", ("placas", "inversor", "bateria"), (
        ("basico", "aprender", "¿Qué pasa cuando las placas producen más luz de la que uso?"),
        ("basico", "aprender", "¿De dónde saca luz mi casa cuando está nublado?"),
        ("intermedio", "aprender", "¿Cómo sabe el sistema cuándo usar la batería?"),
        ("intermedio", "aprender", "¿Cómo trabajan juntas las placas, el inversor y la luz de la calle?"),
        ("intermedio", "aprender", "¿Qué pasa cuando la batería se llena?"),
        ("basico", "aprender", "¿Cómo funciona el sistema de noche, mientras dormimos?"),
        ("basico", "aprender", "¿Por qué muchas casas con placas siguen conectadas a LUMA?"),
        ("profundo", "aprender", "Cuéntame un día completo del sistema, desde que sale el sol hasta la madrugada."),
    )),
    ("factura", ("factura",), (
        ("basico", "aprender", "¿Cómo leo mi factura de LUMA?"),
        ("basico", "aprender", "¿Qué es un kWh, explicado fácil?"),
        ("intermedio", "aprender", "¿Por qué mi factura puede subir aunque use los mismos equipos?"),
        ("intermedio", "evaluar", "¿Cómo sé en qué meses gasto más luz?"),
        ("basico", "evaluar", "¿Qué equipos de la casa suelen gastar más luz?"),
        ("intermedio", "aprender", "¿Qué pasa si gasto más luz después de poner placas?"),
        ("intermedio", "preparar", "¿Qué datos de mi factura conviene tener listos para la evaluación?"),
    )),
    ("evaluacion", ("techo", "factura"), (
        ("basico", "evaluar", "¿Cómo se evalúa una casa antes de proponer placas?"),
        ("intermedio", "evaluar", "¿Por qué dos casas con facturas parecidas pueden necesitar sistemas distintos?"),
        ("intermedio", "evaluar", "¿Cómo influye hacia dónde mira el techo?"),
        ("intermedio", "evaluar", "¿Qué pasa si después quiero poner más aires acondicionados?"),
        ("profundo", "evaluar", "¿Cómo se toma en cuenta que mi consumo puede crecer?"),
        ("profundo", "evaluar", "Explícame paso a paso cómo un especialista decide el tamaño del sistema."),
    )),
    ("placas", ("placas",), (
        ("basico", "aprender", "¿De qué están hechas las placas solares?"),
        ("basico", "aprender", "¿Qué hace que una placa produzca menos?"),
        ("intermedio", "aprender", "¿Cómo afecta el calor de Puerto Rico a las placas?"),
        ("intermedio", "aprender", "¿Qué pasa cuando una sombra tapa parte de una placa?"),
        ("intermedio", "aprender", "¿Las placas se desgastan con los años?"),
        ("profundo", "comparar", "¿Qué debo mirar cuando comparo placas?"),
    )),
    ("inversor", ("inversor",), (
        ("basico", "aprender", "¿Para qué sirve el inversor?"),
        ("intermedio", "aprender", "¿Qué es un microinversor y cuándo se usa?"),
        ("intermedio", "aprender", "¿Qué es un inversor híbrido, en palabras sencillas?"),
        ("intermedio", "aprender", "¿Por qué algunos sistemas se apagan cuando se va la luz?"),
        ("profundo", "aprender", "¿Qué protecciones debe tener una instalación?"),
    )),
    ("baterias", ("bateria", "apagon"), (
        ("basico", "aprender", "¿Cómo funciona una batería para la casa?"),
        ("basico", "evaluar", "¿Una batería puede mantener toda mi casa?"),
        ("intermedio", "evaluar", "¿Qué equipos gastan más batería en un apagón?"),
        ("intermedio", "aprender", "¿Puedo añadir otra batería más adelante?"),
        ("intermedio", "aprender", "¿Qué pasa cuando la batería se queda casi vacía?"),
        ("profundo", "evaluar", "¿De qué depende cuánto me dura la batería?"),
    )),
    ("apagones", ("apagon",), (
        ("basico", "aprender", "¿Qué pasa con mis placas cuando se va la luz de LUMA?"),
        ("basico", "aprender", "¿Puedo usar mis placas durante un apagón?"),
        ("intermedio", "aprender", "¿Cómo funciona el respaldo automático cuando se va la luz?"),
        ("basico", "preparar", "¿Qué equipos conviene dejar prendidos en una emergencia?"),
        ("intermedio", "preparar", "¿Cómo hago que la batería me dure más en un apagón?"),
        ("intermedio", "aprender", "¿Qué pasa si hay varios días nublados después de un huracán?"),
        ("profundo", "aprender", "¿Cómo se protegen las placas de los vientos fuertes?"),
        ("intermedio", "comparar", "¿Qué diferencia hay entre tener batería y tener generador?"),
        ("profundo", "preparar", "Ayúdame a planificar cómo usar la luz en un apagón largo."),
    )),
    ("techos", ("techo", "instalacion"), (
        ("basico", "evaluar", "¿Hay que inspeccionar el techo antes de poner placas?"),
        ("basico", "evaluar", "¿Se pueden poner placas en un techo de concreto?"),
        ("intermedio", "evaluar", "¿Qué pasa si mi techo necesita sellado?"),
        ("intermedio", "evaluar", "¿Cómo se sabe si el techo aguanta las placas?"),
        ("basico", "aprender", "¿Hay que perforar el techo para instalarlas?"),
        ("intermedio", "evaluar", "¿Qué opciones hay si tengo poco espacio?"),
        ("profundo", "evaluar", "¿Se pueden poner placas en una estructura aparte del techo?"),
        ("intermedio", "evaluar", "¿Qué pasa si tengo árboles que dan sombra?"),
        ("profundo", "preparar", "¿Qué le pregunto al instalador antes de autorizar el trabajo?"),
    )),
    ("medicion", ("medicion", "factura"), (
        ("basico", "aprender", "¿Qué es la medición neta?"),
        ("basico", "aprender", "¿Qué pasa con la luz solar que no uso en el momento?"),
        ("intermedio", "aprender", "¿Qué diferencia hay entre usar mi propia luz y devolverla a la red?"),
        ("basico", "aprender", "¿La medición neta quiere decir que no me llegará factura?"),
        ("intermedio", "preparar", "¿Qué trámites hacen falta para conectar placas a la red?"),
        ("intermedio", "aprender", "¿Cómo sé si mi contador cuenta lo que tomo y lo que devuelvo?"),
        ("profundo", "aprender", "¿Qué pasa con mi sistema si cambian las reglas de la luz?"),
    )),
    ("contratos", ("contrato",), (
        ("basico", "aprender", "¿Qué formas suele haber de adquirir un sistema solar?"),
        ("intermedio", "comparar", "¿Qué diferencia hay entre comprar, financiar y arrendar?"),
        ("intermedio", "preparar", "¿Por qué debo mirar el plazo y no solo el pago mensual?"),
        ("intermedio", "preparar", "¿Qué preguntas debo hacer antes de firmar un contrato solar?"),
        ("profundo", "preparar", "¿Qué cargos o aumentos debo buscar en un contrato?"),
        ("profundo", "preparar", "Ayúdame a hacer una lista de cosas que verificar antes de aceptar una propuesta."),
    )),
    ("mantenimiento", ("mantenimiento",), (
        ("intermedio", "aprender", "¿Cómo noto si el sistema produce menos de lo normal?"),
        ("basico", "preparar", "¿Qué papeles debo guardar después de la instalación?"),
        ("intermedio", "aprender", "¿Qué arreglos debe hacer solo un técnico?"),
        ("profundo", "comparar", "¿Qué debo mirar en la garantía de una batería?"),
    )),
    ("instalacion", ("instalacion",), (
        ("basico", "aprender", "¿Cuáles son los pasos de una instalación solar en Puerto Rico?"),
        ("intermedio", "preparar", "¿Qué permisos pueden hacer falta?"),
        ("intermedio", "preparar", "¿Cómo verifico que el instalador está cualificado?"),
        ("intermedio", "aprender", "¿Cómo se lee una aplicación de monitoreo solar?"),
        ("profundo", "aprender", "¿Qué debo revisar cada semana en el monitoreo?"),
        ("profundo", "preparar", "¿Qué preguntas hago cuando me dicen que la instalación terminó?"),
    )),
    ("comparaciones", ("comparar", "contrato"), (
        ("intermedio", "comparar", "¿Conviene más poner más placas o añadir batería?"),
        ("intermedio", "comparar", "¿Qué ventajas y desventajas tienen los microinversores?"),
        ("intermedio", "comparar", "¿Qué diferencia hay entre un sistema conectado a la red y uno aislado?"),
        ("intermedio", "comparar", "¿Qué diferencia hay entre respaldar parte de la casa o toda la casa?"),
        ("profundo", "comparar", "¿Cómo comparo dos propuestas sin depender solo de lo que dice el vendedor?"),
        ("profundo", "comparar", "Ayúdame a armar una tabla sencilla para comparar propuestas."),
        ("intermedio", "comparar", "¿Por qué un pago mensual más bajo no siempre sale más barato?"),
        ("profundo", "comparar", "¿Qué suposiciones pueden hacer que una propuesta prometa de más?"),
    )),
    # Cada situación toca un tema distinto: sus etiquetas salen de su propio texto.
    ("situaciones", ("situacion",), (
        ("basico", "evaluar", "Mi factura es baja. ¿Tiene sentido mirar energía solar?"),
        ("basico", "evaluar", "Mi techo es pequeño. ¿Qué alternativas hay?"),
        ("intermedio", "evaluar", "Uso más luz de día que de noche. ¿Cómo afecta eso?"),
        ("intermedio", "evaluar", "Tengo varios aires acondicionados. ¿Cómo se toma en cuenta su consumo?"),
        ("basico", "evaluar", "Vivo alquilado. ¿Qué puedo hablar con el dueño?"),
        ("intermedio", "evaluar", "Tengo placas viejas. ¿Se puede modernizar el sistema?"),
        ("basico", "comparar", "Ya tengo generador. ¿Qué me aportaría una batería?"),
        ("basico", "preparar", "No estoy listo para comprar. ¿Qué información debo reunir?"),
    )),
)


def _plain(value):
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold().strip()


def _tags_for(text, base):
    found = {topic for topic, pattern in TOPICS.items() if re.search(pattern, text, re.I)}
    return tuple(sorted(found | set(base)))


CATALOG = tuple(
    Suggestion(f"{category}_{index:02d}", category, level, intent, text, _tags_for(text, base))
    for category, base, items in _CATALOG
    for index, (level, intent, text) in enumerate(items, start=1)
)
BY_ID = {item.id: item for item in CATALOG}


@dataclass
class Context:
    tags: Counter          # how strongly each topic appeared, recent messages weigh more
    turns: int             # how many messages the visitor has sent
    asked: set             # normalized texts the visitor already sent
    last_category: str     # category of the last suggestion the visitor used, if any


def build_context(messages):
    """Reads only the visitor's own messages from a conversation they own."""
    user_texts = [m.get("content") or "" for m in messages if m.get("role") == "user"]
    tags = Counter()
    for distance, text in enumerate(reversed(user_texts)):
        weight = 3 if distance == 0 else 2 if distance == 1 else 1
        for topic, pattern in TOPICS.items():
            if re.search(pattern, text, re.I):
                tags[topic] += weight
    asked = {_plain(text) for text in user_texts}
    last_category = next((item.category for item in CATALOG if user_texts and _plain(item.text) == _plain(user_texts[-1])), "")
    return Context(tags=tags, turns=len(user_texts), asked=asked, last_category=last_category)


def score(suggestion, context):
    """Qué tan útil es mostrar `suggestion` ahora; más alto = más arriba.

    Recibe una Suggestion (category, level, intent, tags) y el Context de la
    conversación (tags con pesos, turns, asked, last_category).
    """
    # Relevancia (0 a 4): qué parte de lo conversado toca esta pregunta. Es lo que más pesa.
    total = sum(context.tags.values())
    relevance = sum(context.tags[tag] for tag in suggestion.tags) / total if total else 0.0
    # Nivel (0 a 1): empieza básico y profundiza a medida que la persona pregunta más.
    target = 0 if context.turns <= 1 else 1 if context.turns <= 3 else 2
    level_fit = 1 - abs(LEVELS.index(suggestion.level) - target) / 2
    # Siguiente paso: un empujón leve hacia evaluar o prepararse, sin insistir en vender.
    next_step = 0.5 if context.turns >= 3 and suggestion.intent in {"evaluar", "preparar"} else 0.0
    # Seguir el hilo del último tema que la persona escogió.
    same_thread = 0.5 if suggestion.category == context.last_category else 0.0
    return 4 * relevance + level_fit + next_step + same_thread


def _tiebreak(seed, suggestion_id):
    return hashlib.sha256(f"{seed}:{suggestion_id}".encode()).hexdigest()


def select(messages=(), seen=(), count=6, seed=""):
    """Six relevant, different suggestions: never one already asked, avoid recently
    shown ones (until the catalog runs out), and at most one per category in the
    first pass so the visitor sees different doors."""
    context = build_context(list(messages))
    seen = {item for item in seen if item in BY_ID}
    fresh = [item for item in CATALOG if _plain(item.text) not in context.asked]
    pool = [item for item in fresh if item.id not in seen]
    if len(pool) < count:
        pool = fresh
    ranked = sorted(pool, key=lambda item: (-score(item, context), _tiebreak(seed, item.id)))
    picked, categories = [], set()
    for item in ranked:
        if item.category not in categories:
            picked.append(item)
            categories.add(item.category)
        if len(picked) == count:
            break
    for item in ranked:
        if len(picked) == count:
            break
        if item not in picked:
            picked.append(item)
    return picked
