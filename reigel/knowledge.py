"""Small, auditable Power Solar knowledge cache with no paid service.

Remote HTML supplies evidence for a fixed set of carefully worded statements.
It is never executable policy or an instruction to a language model. Prices,
offers, financial eligibility, guarantees and testimonials are not imported.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import unicodedata
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from .core import stamp

REFRESH_INTERVAL_SECONDS = 6 * 60 * 60
TTL_HOURS = 24
MAX_BYTES = 768 * 1024
SOURCES = (
    {"id": "home", "title": "Power Solar · soluciones", "url": "https://powersolarpr.com/"},
    {"id": "company", "title": "Conoce a Power Solar", "url": "https://powersolarpr.com/conoce-a-power-solar/"},
    {"id": "locations", "title": "Tiendas de Power Solar", "url": "https://powersolarpr.com/tiendas-power-solar/"},
)
ALLOWED_PATHS = {urlparse(source["url"]).path for source in SOURCES}

SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_sources (
 id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
 content_hash TEXT NOT NULL DEFAULT '', facts TEXT NOT NULL DEFAULT '[]',
 checked_at TEXT, success_at TEXT, changed_at TEXT, valid_until TEXT,
 last_error TEXT NOT NULL DEFAULT '', etag TEXT NOT NULL DEFAULT '',
 last_modified TEXT NOT NULL DEFAULT '', verification_method TEXT NOT NULL DEFAULT ''
);
"""


def normalize(value: str) -> str:
    return " ".join("".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                            if not unicodedata.combining(char)).split())


def allowed_url(value: str) -> bool:
    """Only hard-coded corporate pages; no arbitrary URL or referral domain."""
    try:
        parsed = urlparse(value)
        return (parsed.scheme == "https" and parsed.hostname in {"powersolarpr.com", "www.powersolarpr.com"}
                and parsed.path in ALLOWED_PATHS and parsed.port in (None, 443)
                and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
    except (ValueError, TypeError):
        return False


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg", "iframe"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg", "iframe"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, value):
        if not self.ignored:
            self.parts.append(value)


def _facts(html: str, source_id: str) -> list[str]:
    parser = _Text()
    parser.feed(html)
    clean = normalize(" ".join(parser.parts))
    if len(clean) < 150 or "power solar" not in clean:
        raise ValueError("La página recibida no contiene información corporativa reconocible.")
    found = []
    if source_id == "company" and "empresa netamente puertorriquena" in clean and "sistemas fotovoltaicos" in clean:
        found.append("company")
    if source_id == "home":
        if all(term in clean for term in ("solar para tu hogar", "baterias para apartamentos", "soluciones comerciales")):
            found.append("services")
        if all(term in clean for term in ("equipos seleccionados", "capacidad de la bateria", "consumo", "diseno del sistema")):
            found.append("battery")
        if all(term in clean for term in ("estudio de consumo", "visita tecnica", "interconexion")):
            found.append("process")
    if source_id == "locations" and "nuestras tiendas" in clean and "ubicaciones" in clean:
        found.append("locations")
    return found


ANSWERS = {
    "company": "La información corporativa de Power Solar la presenta como una empresa puertorriqueña dedicada a sistemas fotovoltaicos. Podemos comenzar por entender tu consumo y las condiciones de tu propiedad para coordinar una evaluación.",
    "services": "Power Solar presenta soluciones solares para hogares y negocios, y baterías para apartamentos. La configuración se evalúa según el consumo, el espacio disponible y las necesidades de respaldo. ¿Buscas reducir tu dependencia de la red, respaldo o ambas cosas?",
    "battery": "El sitio de Power Solar explica que una solución con batería puede respaldar equipos seleccionados. La duración depende de la capacidad, el consumo y el diseño; no significa que toda la casa funcione indefinidamente. ¿Qué equipos necesitas mantener durante un apagón?",
    "process": "El proceso publicado por Power Solar contempla revisar el consumo, evaluar documentación y realizar una visita técnica y diseño antes de la instalación e interconexión. Los plazos y condiciones de tu caso deben confirmarse con el asesor. Podemos coordinar esa primera conversación.",
    "locations": "Power Solar tiene una página corporativa para localizar tiendas. Consulta allí la ubicación y confirma el horario antes de ir; esta página no permite verificar automáticamente una dirección o disponibilidad concreta. También puedes coordinar una evaluación con el equipo desde aquí.",
}

TECHNICAL_REVIEWED_AT = "2026-11-05T00:00:00+00:00"
TECHNICAL_VALIDITY_DAYS = 180
TECHNICAL_SOURCES = {
    "doe_inverters": {
        "title": "Solar Integration: Inverters and Grid Services Basics",
        "url": "https://www.energy.gov/cmei/systems/solar-integration-inverters-and-grid-services-basics",
        "organization": "U.S. Department of Energy",
    },
    "eia_measurement": {
        "title": "Measuring Electricity",
        "url": "https://www.eia.gov/energyexplained/electricity/measuring-electricity.php",
        "organization": "U.S. Energy Information Administration",
    },
}

TECHNICAL_TOPICS = {
    "pv_operation": {
        "status": "verified",
        "source_ids": ("doe_inverters",),
        "answer": (
            "Las placas atrapan la luz del sol y la convierten en electricidad. Esa electricidad "
            "todavía no sirve tal cual para la casa: un equipo llamado inversor la deja lista para "
            "tus enseres y para la red. Cuánta produciría tu casa se sabe con una evaluación."
        ),
    },
    "inverter": {
        "status": "verified",
        "source_ids": ("doe_inverters",),
        "answer": (
            "El inversor es el equipo que toma la electricidad que sale de las placas y la deja "
            "lista para usarla en tu casa. Según el sistema, también vigila que todo funcione bien "
            "y trabaja junto con la batería."
        ),
    },
    "microinverter": {
        "status": "verified",
        "source_ids": ("doe_inverters",),
        "answer": (
            "Un microinversor es un inversor pequeñito que va en cada placa. Así, si a una placa "
            "le da sombra o tiene un problema, las demás no se afectan igual, según explica el "
            "Departamento de Energía. Si te conviene o no depende del diseño de tu casa."
        ),
    },
    "power_energy": {
        "status": "verified",
        "source_ids": ("eia_measurement",),
        "answer": (
            "Piénsalo como un carro: el kW es como la velocidad, cuánta luz se usa en un momento; "
            "el kWh es como la distancia recorrida, cuánta luz se usó en total. Por eso el contador "
            "de tu casa suma kWh, y no son lo mismo."
        ),
    },
    "grid_outage": {
        "status": "verified",
        "source_ids": ("doe_inverters",),
        "answer": (
            "Cuando se va la luz, un sistema conectado a la red se desconecta solo, por seguridad. "
            "O sea, las placas solas no mantienen tu casa prendida en un apagón. Para eso hace falta "
            "un sistema diseñado para trabajar sin la red, con equipos compatibles, y una batería "
            "no siempre cubre la casa completa."
        ),
    },
    "grid_connected_system": {
        "status": "verified",
        "source_ids": ("doe_inverters",),
        "answer": (
            "Un sistema conectado a la red trabaja al compás de la luz que llega a tu casa. "
            "Qué equipos y protecciones lleva depende del diseño, y estar conectado a la red no "
            "quiere decir que vayas a tener luz en un apagón."
        ),
    },
    "generation_storage": {
        "status": "verified",
        "source_ids": ("doe_inverters",),
        "answer": (
            "Las placas hacen electricidad cuando hay sol, y la batería la guarda para usarla "
            "después, como una alcancía. La batería no fabrica energía, y que te dé luz en un "
            "apagón depende de cómo se diseñe el sistema y de qué equipos tengas conectados."
        ),
    },
    "residential_consumption": {
        "status": "verified",
        "source_ids": ("eia_measurement",),
        "answer": (
            "Lo que gastas de luz se mide en kWh, y el contador de tu casa lo va sumando. "
            "Ese número ayuda, pero no explica todos los cargos de la factura ni basta "
            "para saber qué sistema necesitas."
        ),
    },
    "solar_production": {
        "status": "pending_review",
        "source_ids": (),
    },
    "hybrid_system": {
        "status": "pending_review",
        "source_ids": (),
    },
    "efficiency": {
        "status": "pending_review",
        "source_ids": (),
    },
    "net_metering_puerto_rico": {
        "status": "pending_review",
        "source_ids": (),
    },
    "luma_billing": {
        "status": "pending_review",
        "source_ids": (),
    },
    "preliminary_sizing": {
        "status": "pending_review",
        "source_ids": (),
    },
    "maintenance": {
        "status": "pending_review",
        "source_ids": (),
    },
    "electrical_safety": {
        "status": "pending_review",
        "source_ids": (),
    },
    "component_lifespan": {
        "status": "pending_review",
        "source_ids": (),
    },
}

_TECHNICAL_UNSUPPORTED_COMMERCIAL = re.compile(
    r"\b(?:precio\w*|cuanto cuesta|cuanto sale|oferta\w*|promocion\w*|"
    r"descuento\w*|incentivo\w*|garantia\w*|ahorr\w*|financi\w*|"
    r"credito|interes|pagar con tarjeta|costo\w*)\b"
)


class KnowledgeBase:
    def __init__(self, store):
        self.store = store
        self._refresh_lock = threading.Lock()
        with store.connect() as db:
            db.executescript(SCHEMA)
            if "verification_method" not in {row["name"] for row in db.execute("PRAGMA table_info(knowledge_sources)")}:
                db.execute("ALTER TABLE knowledge_sources ADD COLUMN verification_method TEXT NOT NULL DEFAULT ''")
            for source in SOURCES:
                db.execute("INSERT OR IGNORE INTO knowledge_sources(id,url,title) VALUES(?,?,?)",
                           (source["id"], source["url"], source["title"]))

    def _rows(self):
        with self.store.connect() as db:
            rows = {row["id"]: dict(row) for row in db.execute("SELECT * FROM knowledge_sources")}
        # Fixed catalog is authoritative even if old cache rows survive an upgrade.
        return [{**rows[source["id"]], "url": source["url"], "title": source["title"]} for source in SOURCES]

    @staticmethod
    def _fresh(row, current=None):
        try:
            return (bool(row["content_hash"]) and bool(row["valid_until"])
                    and datetime.fromisoformat(row["valid_until"]) > (current or datetime.now(UTC)))
        except (ValueError, TypeError):
            return False

    def status(self):
        rows = self._rows()
        sources = []
        for row in rows:
            fresh = self._fresh(row)
            state = "cached" if fresh and row["last_error"] else "fresh" if fresh else "error" if row["last_error"] else "stale" if row["content_hash"] else "unavailable"
            sources.append({key: row[key] for key in ("id", "title", "url", "checked_at", "changed_at", "valid_until", "last_error", "success_at", "verification_method")}
                           | {"checked_at": row["success_at"], "last_attempt_at": row["checked_at"],
                              "status": state, "available": fresh, "topics": json.loads(row["facts"]) if fresh else []})
        count = sum(source["available"] for source in sources)
        state = "fresh" if count == len(sources) and not any(row["last_error"] for row in rows) else "partial" if count else "stale" if any(row["content_hash"] for row in rows) else "unavailable"
        return {"status": state, "checked_at": max((row["success_at"] for row in rows if row["success_at"]), default=None),
                "last_attempt_at": max((row["checked_at"] for row in rows if row["checked_at"]), default=None),
                "valid_until": min((row["valid_until"] for row in rows if self._fresh(row)), default=None),
                "refresh_interval_seconds": REFRESH_INTERVAL_SECONDS, "ttl_hours": TTL_HOURS, "sources": sources,
                "refreshing": self._refresh_lock.locked(),
                "notice": "Se revisan páginas corporativas cada 6 horas mientras R.E.I.G.E.L. está encendido y conectado. Los datos caducan a las 24 horas. Las ofertas, precios y financiación requieren confirmación del equipo."}

    def public_status(self):
        result = self.status()
        for source in result["sources"]:
            source.pop("last_error", None)
        return result

    async def _fetch(self, client, source, previous):
        address = source["url"]
        headers = {"User-Agent": "REIGEL-Knowledge/1.0 (bounded corporate information check)", "Accept": "text/html"}
        if previous["etag"]:
            headers["If-None-Match"] = previous["etag"]
        if previous["last_modified"]:
            headers["If-Modified-Since"] = previous["last_modified"]
        for _ in range(3):
            if not allowed_url(address):
                raise ValueError("La fuente intentó salir de las páginas corporativas permitidas.")
            async with client.stream("GET", address, headers=headers) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    address = urljoin(address, response.headers.get("location", ""))
                    if not response.headers.get("location") or not allowed_url(address):
                        raise ValueError("La fuente redirigió a una dirección no permitida.")
                    continue
                if response.status_code == 304:
                    if not previous["content_hash"]:
                        raise ValueError("La fuente indicó contenido sin cambios, pero no existe una copia validada.")
                    return {"content_hash": previous["content_hash"], "facts": previous["facts"],
                            "etag": previous["etag"], "last_modified": previous["last_modified"]}
                if response.status_code != 200:
                    raise ValueError(f"La fuente respondió HTTP {response.status_code}.")
                if response.headers.get("content-type", "").split(";", 1)[0].lower().strip() not in {"text/html", "application/xhtml+xml"}:
                    raise ValueError("La fuente no entregó una página HTML.")
                try:
                    declared_size = int(response.headers.get("content-length", "0"))
                except ValueError:
                    raise ValueError("La fuente declaró un tamaño no válido.") from None
                if declared_size > MAX_BYTES or declared_size < 0:
                    raise ValueError("La página supera el tamaño máximo permitido.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise ValueError("La página supera el tamaño máximo permitido.")
                decoded = bytes(body).decode(response.encoding or "utf-8", errors="replace")
                facts = _facts(decoded, source["id"])
                return {"content_hash": hashlib.sha256(body).hexdigest(), "facts": json.dumps(facts),
                        "etag": response.headers.get("etag", "")[:1024],
                        "last_modified": response.headers.get("last-modified", "")[:1024]}
        raise ValueError("La fuente tiene demasiadas redirecciones.")

    async def refresh(self, force=False):
        if not self._refresh_lock.acquire(blocking=False):
            return self.status()
        try:
            previous = {row["id"]: row for row in self._rows()}
            current = datetime.now(UTC)
            selected = []
            for source in SOURCES:
                checked = previous[source["id"]]["checked_at"]
                try:
                    recent = checked and (current - datetime.fromisoformat(checked)).total_seconds() < REFRESH_INTERVAL_SECONDS
                except (ValueError, TypeError):
                    recent = False
                if force or not recent:
                    selected.append(source)
            async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5), follow_redirects=False, trust_env=False) as client:
                async def update(source):
                    row = previous[source["id"]]
                    try:
                        result = await asyncio.wait_for(self._fetch(client, source, row), timeout=20)
                    except (httpx.HTTPError, asyncio.TimeoutError):
                        error = "No se pudo consultar la fuente. Se conserva la última evidencia, sin presentarla como vigente."
                    except ValueError as exc:
                        error = str(exc)
                    else:
                        checked_at = stamp()
                        until = (datetime.fromisoformat(checked_at) + timedelta(hours=TTL_HOURS)).isoformat()
                        changed_at = checked_at if result["content_hash"] != row["content_hash"] else row["changed_at"]
                        with self.store.connect() as db:
                            db.execute("UPDATE knowledge_sources SET content_hash=?,facts=?,checked_at=?,success_at=?,changed_at=?,valid_until=?,last_error='',etag=?,last_modified=?,verification_method='direct_http' WHERE id=?",
                                       (result["content_hash"], result["facts"], checked_at, checked_at, changed_at, until,
                                        result["etag"], result["last_modified"], source["id"]))
                        return
                    with self.store.connect() as db:
                        db.execute("UPDATE knowledge_sources SET checked_at=?,last_error=? WHERE id=?", (stamp(), error, source["id"]))
                await asyncio.gather(*(update(source) for source in selected))
        finally:
            self._refresh_lock.release()
        return self.status()

    def import_reviewed_snapshot(self, source_id, topics, reviewed_at):
        """Explicit operator-only import after independently reviewing the page.

        The timestamp belongs to the review and is never refreshed on startup.
        This does not clear a direct HTTP failure or pretend an HTTP success.
        Callers must enforce administrator authorization if exposed over HTTP.
        """
        permitted = {"home": {"services", "battery", "process"}, "company": {"company"}, "locations": {"locations"}}
        if source_id not in permitted or not isinstance(topics, list) or not topics or any(not isinstance(topic, str) or topic not in permitted[source_id] for topic in topics):
            raise ValueError("Selecciona una fuente y hechos revisados del catálogo permitido.")
        try:
            reviewed = datetime.fromisoformat(reviewed_at)
            if reviewed.utcoffset() is None or reviewed > datetime.now(UTC) + timedelta(minutes=1):
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError("La revisión requiere su fecha real, con zona horaria y sin fechas futuras.") from None
        facts = json.dumps(sorted(set(topics)))
        fingerprint = hashlib.sha256(("reviewed:" + source_id + ":" + facts).encode()).hexdigest()
        with self.store.connect() as db:
            row = db.execute("SELECT success_at,content_hash,changed_at FROM knowledge_sources WHERE id=?", (source_id,)).fetchone()
            if row["success_at"] and datetime.fromisoformat(row["success_at"]) > reviewed:
                raise ValueError("Una revisión antigua no puede reemplazar evidencia más reciente.")
            db.execute("UPDATE knowledge_sources SET content_hash=?,facts=?,success_at=?,changed_at=?,valid_until=?,verification_method='web_review',etag='',last_modified='' WHERE id=?",
                       (fingerprint, facts, reviewed.isoformat(), reviewed.isoformat() if row["content_hash"] != fingerprint else row["changed_at"], (reviewed + timedelta(hours=TTL_HOURS)).isoformat(), source_id))
        return self.status()

    def answer(self, query):
        if not isinstance(query, str) or len(query) > 4000:
            return None
        clean = normalize(query)
        if re.search(r"\b(precio|precios|cuesta|costo|costos|oferta|ofertas|promocion|financi\w*|garantia|garantias|ahorr\w*|incentiv\w*|credito|interes|descuento|pago|pagos)\b", clean):
            return None
        if any(term in clean for term in ("tienda", "ubicacion", "direccion", "localizacion", "sucursal", "horario de tienda")):
            topic = "locations"
        elif any(term in clean for term in ("bateria", "respaldo", "apagon", "apagones")):
            topic = "battery"
        elif any(term in clean for term in ("proceso", "instala", "etapa", "visita tecnica", "interconexion")):
            topic = "process"
        elif any(term in clean for term in ("servicio", "producto", "solucion", "apartamento", "comercial", "negocio", "ofrecen", "venden")):
            topic = "services"
        elif any(term in clean for term in ("power solar", "empresa", "quienes son", "quien es", "compan")):
            topic = "company"
        else:
            return None
        for row in self._rows():
            if self._fresh(row) and topic in json.loads(row["facts"]):
                return {"text": ANSWERS[topic], "sources": [{"title": row["title"], "url": row["url"], "checked_at": row["success_at"], "verification_method": row["verification_method"]}], "stale": False}
        return None

    @staticmethod
    def _technical_topic(clean):
        if re.search(r"\b(?:medicion neta|net metering|neteo)\b", clean):
            return "net_metering_puerto_rico"
        if "luma" in clean and re.search(r"\b(?:factura|recibo|cargo|tarifa|kwh|medidor)\b", clean):
            return "luma_billing"
        if re.search(r"\b(?:dimension\w*|tamano del sistema|cuantos paneles|cuanta produccion|"
                     r"cuantos kwh|produccion mensual|produccion anual)\b", clean):
            return "preliminary_sizing"
        if re.search(r"\b(?:vida util|cuanto dura|duracion de|anos dura|degradacion)\b", clean):
            return "component_lifespan"
        if re.search(r"\b(?:mantenimiento|limpieza de paneles|mantenimiento preventivo)\b", clean):
            return "maintenance"
        if re.search(r"\b(?:seguridad electrica|riesgo electrico|instalar.*(?:cable|inversor|panel)|"
                     r"trabajar con electricidad)\b", clean):
            return "electrical_safety"
        if re.search(r"\b(?:eficiencia|rendimiento del sistema|perdidas del sistema)\b", clean):
            return "efficiency"
        if re.search(r"\b(?:hibrid\w*|sistema mixto)\b", clean):
            return "hybrid_system"
        if re.search(r"\b(?:apagon|apagones|corte de luz|se va la luz|interrupcion electrica)\b", clean):
            return "grid_outage"
        if re.search(r"\bmicroinversor(?:es)?\b", clean):
            return "microinverter"
        if re.search(r"\binversor(?:es)?\b|\binverter\b", clean):
            return "inverter"
        if re.search(r"\b(?:kw\s*(?:y|vs\.?|versus)\s*kwh|kwh\s*(?:y|vs\.?|versus)\s*kw|"
                     r"diferencia.*\bkw\b|\bkw\b.*\bkwh\b|\bkwh\b.*\bkw\b|"
                     r"(?:que es|significa)\s*(?:un\s*)?kwh)\b", clean):
            return "power_energy"
        if re.search(r"\b(?:bateria|baterias|almacenamiento)\b", clean) and re.search(
            r"\b(?:panel|placa|produccion|generacion|diferencia|compar\w*)\b", clean
        ):
            return "generation_storage"
        if re.search(r"\b(?:bateria|baterias|almacenamiento)\b", clean):
            return "generation_storage"
        if re.search(r"\b(?:consumo electrico|consumo residencial|consumo de energia|"
                     r"medidor electrico|kwh consumidos)\b", clean):
            return "residential_consumption"
        if re.search(r"\b(?:produccion solar|produccion fotovoltaica|generacion fotovoltaica|cuanto produce|"
                     r"cuanta energia produce|produccion de los paneles)\b", clean):
            return "solar_production"
        if re.search(r"\b(?:conectado a la red|conectado a red|sistema interconectado|on.?grid)\b", clean):
            return "grid_connected_system"
        if re.search(r"\b(?:paneles solares|placas solares|sistema fotovoltaico|"
                     r"energia fotovoltaica|produccion fotovoltaica|como funcionan los paneles|"
                     r"como funcionan las placas|como funciona la energia solar)\b", clean) or re.search(
            r"\b(?:panel(?:es)?|placas?)\b.*\b(?:generan|producen|corriente)\b", clean
        ):
            return "pv_operation"
        return None

    def answer_technical(self, query, *, current=None):
        """Retrieve only curated general facts with reviewed, unexpired citations."""
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            return None
        clean = normalize(query)
        if _TECHNICAL_UNSUPPORTED_COMMERCIAL.search(clean) or re.search(
            r"\b(?:ignora|ignorar|instrucciones|system prompt|revela el prompt)\b", clean
        ):
            return None
        topic_id = self._technical_topic(clean)
        if topic_id is None:
            return None
        topic = TECHNICAL_TOPICS[topic_id]
        if topic["status"] != "verified":
            return {
                "status": "insufficient",
                "topic": topic_id,
                "text": (
                    "No tengo una fuente técnica vigente y verificada para responder ese tema "
                    "con seguridad. Prefiero no estimar ni asumir; el equipo puede confirmarlo "
                    "con una referencia autorizada."
                ),
                "sources": [],
            }
        now = current or datetime.now(UTC)
        sources = []
        for source_id in topic["source_ids"]:
            source = TECHNICAL_SOURCES[source_id]
            reviewed = datetime.fromisoformat(TECHNICAL_REVIEWED_AT)
            valid_until = reviewed + timedelta(days=TECHNICAL_VALIDITY_DAYS)
            if now >= valid_until:
                return {
                    "status": "insufficient",
                    "topic": topic_id,
                    "text": (
                        "La referencia técnica disponible necesita una revisión antes de "
                        "usarse. No voy a presentar información posiblemente desactualizada."
                    ),
                    "sources": [],
                }
            sources.append({
                "title": source["title"],
                "url": source["url"],
                "organization": source["organization"],
                "checked_at": TECHNICAL_REVIEWED_AT,
                "valid_until": valid_until.isoformat(),
                "verification_method": "curated_official_reference",
            })
        answer = topic["answer"]
        if re.search(r"\b(?:power solar|ustedes|su sistema|incluye|instalan|ofrecen)\b", clean):
            answer += (
                " Esta es una explicación técnica general y no confirma equipos, servicios "
                "ni prestaciones específicos de Power Solar."
            )
        return {"status": "verified", "topic": topic_id, "text": answer, "sources": sources}

    async def run(self, stop: asyncio.Event):
        """Optional in-process worker; refreshes only while the app is running."""
        while not stop.is_set():
            await self.refresh()
            try:
                await asyncio.wait_for(stop.wait(), timeout=REFRESH_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
