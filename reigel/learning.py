"""Cola de aprendizaje con aprobación humana: huecos, propuestas y banco de preguntas.

R.E.I.G.E.L. registra lo que no supo responder bien (un «hueco»), una persona del
equipo propone una respuesta y solo un administrador la aprueba. Aprender y
publicar son pasos separados: este módulo no publica nada, no llama al modelo y no
cambia sus instrucciones. El uso de lo aprobado se conecta en otro tramo y sigue
sujeto a los validadores de respuestas públicas.

Privacidad: la pregunta se guarda ya redactada (correos, teléfonos, direcciones,
números largos y nombres presentados) y nunca con IDs de conversación o visitante,
IP, cookies ni nombres de la persona. ``purge_expired`` borra los huecos no
aprobados tras ``RETENTION_DAYS``. Esa limpieza es higiene de la cola: no sustituye
ni atiende las solicitudes de acceso, corrección o eliminación de ``privacy.py``.

Prioridad: ``P = 100 × U × R × N / (1 + C)``, recortada a 0..100. Es una
heurística para ordenar la cola, no una ley ni una medida de impacto:

- U, incertidumbre (0..1), según el motivo del hueco (``UNCERTAINTY``).
- R, relevancia comercial (0..1), según el tema detectado con los mismos patrones
  de ``suggestions.TOPICS`` (``RELEVANCE``); sin tema, ``DEFAULT_RELEVANCE``.
- N, novedad (0..1): mitad frecuencia (crece con las apariciones y satura en
  ``FREQUENCY_SATURATION``) y mitad recencia (decae con la antigüedad de la última
  aparición, ``RECENCY_DAYS``).
- C, costo fijo de revisar un hueco (``DEFAULT_COST``), configurable por instancia.
"""
from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .core import DomainError, stamp, text, uid
from .ia_workspace import hide_contacts
from .suggestions import TOPICS

ROUTES = ("ia", "chat")
REASONS = ("blocked", "fallback", "no_knowledge", "model_error", "staff_flag")
GAP_STATES = ("open", "proposed", "approved", "rejected", "resolved")
PROPOSAL_STATES = ("pending", "approved", "rejected", "superseded")
RETENTION_DAYS = 90
MAX_QUESTION = 1000
MAX_ANSWER = 900  # el validador de /chat no acepta más de 900 caracteres
MAX_NOTE = 500
LIST_SCAN = 2000
DISPLAY_ZONE = "America/Puerto_Rico"

# --- Prioridad (heurística, no ley) -------------------------------------------
UNCERTAINTY = {
    "staff_flag": 1.0,    # una persona del equipo señaló la respuesta
    "blocked": 0.9,       # el validador retiró la respuesta del modelo
    "no_knowledge": 0.9,  # no había fuente verificada para contestar
    "fallback": 0.6,      # se usó la respuesta de respaldo
    "model_error": 0.3,   # fallo técnico del modelo, no necesariamente de conocimiento
}
RELEVANCE = {
    "techo": 1.0, "instalacion": 1.0, "contrato": 1.0,
    "factura": 0.9, "bateria": 0.9, "apagon": 0.9,
    "placas": 0.8, "medicion": 0.8, "mantenimiento": 0.8,
    "inversor": 0.7, "comparar": 0.7,
}
DEFAULT_RELEVANCE = 0.4
DEFAULT_TOPIC = "general"
FREQUENCY_SATURATION = 10
RECENCY_DAYS = 30.0
DEFAULT_COST = 0.25

SCHEMA_VERSION = "learning_queue_v1"


def migrate_learning(db):
    """DDL aditiva, versionada e idempotente, al estilo de ``migrate_operations``."""
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY,applied_at TEXT NOT NULL)")
    db.execute("BEGIN IMMEDIATE")
    if db.execute("SELECT 1 FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,)).fetchone():
        return
    statements = (
        """CREATE TABLE IF NOT EXISTS learning_gaps (
            id TEXT PRIMARY KEY,
            first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,
            route TEXT NOT NULL CHECK(route IN ('ia','chat')),
            reason TEXT NOT NULL CHECK(reason IN ('blocked','fallback','no_knowledge','model_error','staff_flag')),
            question TEXT NOT NULL,question_key TEXT NOT NULL,
            occurrences INTEGER NOT NULL DEFAULT 1,
            topic TEXT NOT NULL DEFAULT 'general',
            priority REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','proposed','approved','rejected','resolved')),
            UNIQUE(route,question_key))""",
        """CREATE TABLE IF NOT EXISTS learning_proposals (
            id TEXT PRIMARY KEY,
            gap_id TEXT NOT NULL REFERENCES learning_gaps(id) ON DELETE CASCADE,
            proposed_answer TEXT NOT NULL,source_note TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','superseded')),
            created_by TEXT REFERENCES users(id),created_at TEXT NOT NULL,
            reviewed_by TEXT REFERENCES users(id),reviewed_at TEXT,review_note TEXT NOT NULL DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS learning_eval_cases (
            id TEXT PRIMARY KEY,
            route TEXT NOT NULL CHECK(route IN ('ia','chat')),
            question TEXT NOT NULL,expectations TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'seed',
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS learning_eval_runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,finished_at TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',route TEXT NOT NULL DEFAULT 'ia',
            total INTEGER NOT NULL,passed INTEGER NOT NULL,failed INTEGER NOT NULL,
            results TEXT NOT NULL,summary TEXT NOT NULL,
            created_by TEXT REFERENCES users(id))""",
        "CREATE INDEX IF NOT EXISTS learning_gaps_status ON learning_gaps(status,priority DESC)",
        "CREATE INDEX IF NOT EXISTS learning_gaps_seen ON learning_gaps(last_seen_at)",
        "CREATE INDEX IF NOT EXISTS learning_proposals_gap ON learning_proposals(gap_id,status)",
        "CREATE INDEX IF NOT EXISTS learning_eval_runs_time ON learning_eval_runs(finished_at DESC)",
    )
    for statement in statements:
        db.execute(statement)
    db.execute("INSERT INTO schema_migrations VALUES(?,?)", (SCHEMA_VERSION, stamp()))


# --- Ocultamiento ---------------------------------------------------------------
# Correos y teléfonos: el mismo ocultamiento que ya usa /ia (ia_workspace.hide_contacts).
# Encima: direcciones postales de Puerto Rico, números largos y nombres presentados.
_ADDRESS = re.compile(
    r"(?<!\w)(?:calle|c/|avenida|ave\.?|av\.|carretera|carr\.?|urbanizaci[oó]n|urb\.|"
    r"barrio|bo\.|condominio|cond\.|residencial|res\.|apartamento|apto\.?|apt\.|"
    r"p\.?\s?o\.?\s?box|apartado(?: postal)?|camino|parcelas?|edificio|edif\.|km\.?|kil[oó]metro)"
    r"(?=[\s\d])[^,.;:?!¿¡\n]{0,60}",
    re.I,
)
_VERY_LONG_NUMBER = re.compile(r"(?<!\w)\d(?:[\s.\-/]?\d){15,}(?!\w)")
_LONG_NUMBER = re.compile(r"(?<!\w)\d(?:[\s.\-/]?\d){4,}(?!\w)")
_NAME = re.compile(
    r"\b((?i:me llamo|mi nombre es|mi nombre:|soy|habla|le escribe|te escribe|atentamente,?))"
    r"\s+(?:[A-ZÁÉÍÓÚÑ][\wáéíóúñü'-]*)(?:\s+(?:de\s+(?:la\s+)?|del\s+)?[A-ZÁÉÍÓÚÑ][\wáéíóúñü'-]*){0,3}",
)


def redact(value) -> str:
    """Texto sin correos, teléfonos, direcciones, números largos ni nombres presentados."""
    # Primero los números muy largos (tarjetas, cuentas), para que el patrón de
    # teléfono no se lleve solo una parte y deje dígitos sueltos.
    hidden = _VERY_LONG_NUMBER.sub("[número omitido]", str(value or ""))
    hidden = hide_contacts(hidden)
    hidden = _NAME.sub(lambda m: m.group(1) + " [nombre omitido]", hidden)
    hidden = _ADDRESS.sub("[dirección omitida]", hidden)
    hidden = _LONG_NUMBER.sub("[número omitido]", hidden)
    return " ".join(hidden.split())[:MAX_QUESTION]


_FILLER = {
    "hola", "buenas", "buenos", "dias", "tardes", "noches", "saludos", "oye", "mira",
    "por", "favor", "gracias", "porfa", "porfavor", "disculpa", "disculpe",
}


def _plain(value) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def question_key(value) -> str:
    """Clave para agrupar la misma pregunta: sin tildes, mayúsculas, signos ni saludos."""
    words = re.findall(r"[a-z0-9ñ]+", _plain(value))
    kept = [word for word in words if word not in _FILLER]
    return " ".join(kept or words)[:300]


def topic_of(value) -> str:
    """Tema comercial de mayor relevancia según ``suggestions.TOPICS``; ``general`` si no hay."""
    found = [topic for topic, pattern in TOPICS.items() if re.search(pattern, str(value or ""), re.I)]
    if not found:
        return DEFAULT_TOPIC
    return max(found, key=lambda topic: (RELEVANCE.get(topic, DEFAULT_RELEVANCE), -list(TOPICS).index(topic)))


def novelty(occurrences, last_seen_at, current=None) -> float:
    occurrences = max(1, int(occurrences or 1))
    frequency = min(1.0, math.log1p(occurrences) / math.log1p(FREQUENCY_SATURATION))
    try:
        seen = datetime.fromisoformat(last_seen_at)
        age_days = max(0.0, ((current or datetime.now(UTC)) - seen).total_seconds() / 86400)
    except (TypeError, ValueError):
        age_days = RECENCY_DAYS * 10
    recency = math.exp(-age_days / RECENCY_DAYS)
    return 0.5 * frequency + 0.5 * recency


def priority(reason, topic, occurrences, last_seen_at, *, cost=DEFAULT_COST, current=None) -> float:
    """``P = 100 × U × R × N / (1 + C)`` en 0..100. Heurística de orden, no una ley."""
    u = UNCERTAINTY.get(reason, 0.5)
    r = RELEVANCE.get(topic, DEFAULT_RELEVANCE)
    n = novelty(occurrences, last_seen_at, current)
    value = 100.0 * u * r * n / (1.0 + max(0.0, float(cost)))
    return round(min(100.0, max(0.0, value)), 1)


def public_answer_problem(value):
    """Motivo por el que una respuesta no pasaría a un cliente, o None si pasa.

    Aplica los dos validadores existentes de respuestas públicas (``/chat`` y
    ``/ia``) con ``verified=True``, porque la respuesta llega revisada por el
    equipo con su fuente; así siguen vetadas cifras, precios, promesas,
    garantías, contactos, enlaces, gestiones afirmadas y la instrucción de
    instalar. Además se rechaza cualquier mención de financiación, que los
    validadores solo vetan como «financiamiento aprobado».
    """
    from . import ai_chat  # lectura: no se modifica ai_chat

    for validator in (ai_chat.validate_reply, ai_chat.validate_workspace_reply):
        try:
            validator(value, verified=True)
        except ValueError as error:
            return str(error)
    if re.search(r"financ\w*", _plain(value)):
        return "El texto menciona financiación, que requiere confirmación del equipo con cada cliente."
    return None


def _local(value, tz):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(tz).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def _require_staff(actor):
    if not actor or actor.get("role") not in {"admin", "advisor"} or actor.get("active") is False:
        raise DomainError("Esta acción requiere una cuenta del equipo.", 403)


class LearningQueue:
    """Cola de huecos y propuestas sobre el ``Store`` existente (misma base SQLite)."""

    def __init__(self, store, *, cost=DEFAULT_COST):
        try:
            cost = float(cost)
            if not math.isfinite(cost) or not 0 <= cost <= 10:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError("El costo de revisión debe estar entre cero y diez.") from None
        self.store = store
        self.cost = cost
        self._last_purge = 0.0
        with store.connect() as db:
            migrate_learning(db)

    def _zone(self):
        try:
            return ZoneInfo(self.store.settings().get("timezone") or DISPLAY_ZONE)
        except Exception:
            return ZoneInfo(DISPLAY_ZONE)

    def _gap_dict(self, row, tz, current=None):
        item = dict(row)
        item["priority"] = priority(item["reason"], item["topic"], item["occurrences"], item["last_seen_at"],
                                    cost=self.cost, current=current)
        item["first_seen_local"] = _local(item["first_seen_at"], tz)
        item["last_seen_local"] = _local(item["last_seen_at"], tz)
        item.pop("question_key", None)
        return item

    # --- huecos -------------------------------------------------------------
    def record_gap(self, route, reason, question, actor=None):
        """Registra o agrupa un hueco. Sin datos personales; ``actor`` solo para ``staff_flag``.

        Devuelve el hueco o None si la pregunta queda vacía tras redactarla.
        """
        if route not in ROUTES:
            raise DomainError("Ruta de aprendizaje no válida.", 422)
        if reason not in REASONS:
            raise DomainError("Motivo de aprendizaje no válido.", 422)
        if reason == "staff_flag":
            _require_staff(actor)
        if not isinstance(question, str):
            raise DomainError("La pregunta debe ser texto.", 422)
        clean = redact(question)
        key = question_key(clean)
        if not key:
            return None
        topic = topic_of(clean)
        current = stamp()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM learning_gaps WHERE route=? AND question_key=?", (route, key)).fetchone()
            if row:
                # Se conserva el motivo de mayor incertidumbre; un hueco resuelto que vuelve se reabre.
                strongest = max((row["reason"], reason), key=lambda item: UNCERTAINTY.get(item, 0))
                status = "open" if row["status"] == "resolved" else row["status"]
                occurrences = row["occurrences"] + 1
                value = priority(strongest, row["topic"], occurrences, current, cost=self.cost)
                db.execute(
                    "UPDATE learning_gaps SET last_seen_at=?,occurrences=?,reason=?,priority=?,status=? WHERE id=?",
                    (current, occurrences, strongest, value, status, row["id"]),
                )
                gap_id = row["id"]
                action = "learning.gap.repeat" if status == row["status"] else "learning.gap.reopen"
            else:
                gap_id = uid()
                value = priority(reason, topic, 1, current, cost=self.cost)
                db.execute(
                    "INSERT INTO learning_gaps(id,first_seen_at,last_seen_at,route,reason,question,question_key,"
                    "occurrences,topic,priority,status) VALUES(?,?,?,?,?,?,?,1,?,?,'open')",
                    (gap_id, current, current, route, reason, clean, key, topic, value),
                )
                action = "learning.gap.create"
            self.store.audit(db, actor, action, gap_id)
            saved = db.execute("SELECT * FROM learning_gaps WHERE id=?", (gap_id,)).fetchone()
            return self._gap_dict(saved, self._zone())

    def list(self, actor, *, status="", route="", reason="", topic="", limit=100, offset=0):
        """Huecos filtrados y ordenados por prioridad actual (la recencia cambia con el tiempo).

        Asesores y administradores: tras redactarla, la cola no contiene datos de visitantes,
        y un asesor necesita verla para proponer.
        """
        _require_staff(actor)
        filters, values = [], []
        for field, value, allowed in (("status", status, GAP_STATES), ("route", route, ROUTES), ("reason", reason, REASONS)):
            if value:
                if value not in allowed:
                    raise DomainError("Filtro de aprendizaje no válido.", 422)
                filters.append(f"{field}=?")
                values.append(value)
        if topic:
            if topic != DEFAULT_TOPIC and topic not in TOPICS:
                raise DomainError("Tema de aprendizaje no válido.", 422)
            filters.append("topic=?")
            values.append(topic)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise DomainError("Límite no válido.", 422)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= LIST_SCAN:
            raise DomainError("Desplazamiento no válido.", 422)
        where = " AND ".join(filters) or "1=1"
        tz = self._zone()
        current = datetime.now(UTC)
        with self.store.connect() as db:
            rows = db.execute(
                f"SELECT * FROM learning_gaps WHERE {where} ORDER BY last_seen_at DESC LIMIT ?",
                (*values, LIST_SCAN),
            ).fetchall()
            pending = {row["gap_id"]: row["n"] for row in db.execute(
                "SELECT gap_id,count(*) n FROM learning_proposals WHERE status='pending' GROUP BY gap_id")}
        gaps = [self._gap_dict(row, tz, current) for row in rows]
        for gap in gaps:
            gap["pending_proposals"] = pending.get(gap["id"], 0)
        gaps.sort(key=lambda gap: gap["last_seen_at"], reverse=True)
        gaps.sort(key=lambda gap: gap["priority"], reverse=True)  # estable: empates, lo más reciente primero
        return {
            "gaps": gaps[offset:offset + limit],
            "total": len(gaps),
            "timezone": str(tz),
            "priority_formula": "P = 100 × U × R × N / (1 + C); heurística de orden, no una ley.",
            "cost": self.cost,
        }

    def proposals(self, actor, gap_id):
        _require_staff(actor)
        tz = self._zone()
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM learning_proposals WHERE gap_id=? ORDER BY created_at", (gap_id,)).fetchall()
        return [dict(row) | {"created_local": _local(row["created_at"], tz), "reviewed_local": _local(row["reviewed_at"], tz)}
                for row in rows]

    # --- propuestas ---------------------------------------------------------
    def propose(self, gap_id, data, actor):
        """Asesor o administrador propone una respuesta con su fuente o criterio."""
        _require_staff(actor)
        if not isinstance(data, dict) or set(data) - {"proposed_answer", "source_note"}:
            raise DomainError("Propuesta no válida.", 422)
        answer = text(data.get("proposed_answer"), "respuesta propuesta", limit=MAX_ANSWER, required=True)
        source = text(data.get("source_note"), "fuente o criterio", limit=MAX_NOTE, required=True)
        current = stamp()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            gap = db.execute("SELECT status FROM learning_gaps WHERE id=?", (gap_id,)).fetchone()
            if not gap:
                raise DomainError("Hueco no encontrado.", 404)
            if gap["status"] not in {"open", "proposed"}:
                raise DomainError("Este hueco ya no admite propuestas.", 409)
            proposal_id = uid()
            db.execute(
                "INSERT INTO learning_proposals(id,gap_id,proposed_answer,source_note,status,created_by,created_at)"
                " VALUES(?,?,?,?,'pending',?,?)",
                (proposal_id, gap_id, answer, source, actor["id"], current),
            )
            db.execute("UPDATE learning_gaps SET status='proposed' WHERE id=?", (gap_id,))
            self.store.audit(db, actor, "learning.proposal.create", proposal_id)
            return dict(db.execute("SELECT * FROM learning_proposals WHERE id=?", (proposal_id,)).fetchone())

    def _pending_proposal(self, db, proposal_id):
        row = db.execute("SELECT * FROM learning_proposals WHERE id=?", (proposal_id,)).fetchone()
        if not row:
            raise DomainError("Propuesta no encontrada.", 404)
        if row["status"] != "pending":
            raise DomainError("Esta propuesta ya fue revisada.", 409)
        return row

    def approve(self, proposal_id, actor, note=""):
        """Solo un administrador. La respuesta debe pasar los validadores públicos."""
        self.store.require_admin(actor)
        note = text(note, "nota de revisión", limit=MAX_NOTE)
        with self.store.connect() as db:
            row = self._pending_proposal(db, proposal_id)
        problem = public_answer_problem(row["proposed_answer"])
        if problem:
            with self.store.connect() as db:
                self.store.audit(db, actor, "learning.proposal.approve_blocked", proposal_id)
            raise DomainError("No se puede aprobar: " + problem + " Corrige la propuesta y vuelve a enviarla.", 422)
        current = stamp()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._pending_proposal(db, proposal_id)
            db.execute(
                "UPDATE learning_proposals SET status='superseded',review_note=CASE WHEN review_note='' "
                "THEN 'Sustituida por otra propuesta aprobada.' ELSE review_note END,"
                "reviewed_by=coalesce(reviewed_by,?),reviewed_at=coalesce(reviewed_at,?) "
                "WHERE gap_id=? AND id<>? AND status IN ('pending','approved')",
                (actor["id"], current, row["gap_id"], proposal_id),
            )
            db.execute(
                "UPDATE learning_proposals SET status='approved',reviewed_by=?,reviewed_at=?,review_note=? WHERE id=?",
                (actor["id"], current, note, proposal_id),
            )
            db.execute("UPDATE learning_gaps SET status='approved' WHERE id=?", (row["gap_id"],))
            self.store.audit(db, actor, "learning.proposal.approve", proposal_id)
            return dict(db.execute("SELECT * FROM learning_proposals WHERE id=?", (proposal_id,)).fetchone())

    def reject(self, proposal_id, actor, note=""):
        """Solo un administrador rechaza una propuesta; el hueco vuelve a quedar abierto."""
        self.store.require_admin(actor)
        note = text(note, "nota de revisión", limit=MAX_NOTE)
        current = stamp()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._pending_proposal(db, proposal_id)
            db.execute(
                "UPDATE learning_proposals SET status='rejected',reviewed_by=?,reviewed_at=?,review_note=? WHERE id=?",
                (actor["id"], current, note, proposal_id),
            )
            remaining = db.execute(
                "SELECT count(*) FROM learning_proposals WHERE gap_id=? AND status='pending'", (row["gap_id"],)
            ).fetchone()[0]
            if not remaining:
                db.execute("UPDATE learning_gaps SET status='open' WHERE id=? AND status='proposed'", (row["gap_id"],))
            self.store.audit(db, actor, "learning.proposal.reject", proposal_id)
            return dict(db.execute("SELECT * FROM learning_proposals WHERE id=?", (proposal_id,)).fetchone())

    def reject_gap(self, gap_id, actor, note=""):
        """Solo un administrador descarta un hueco (no era un fallo real); sus propuestas pendientes se rechazan."""
        self.store.require_admin(actor)
        note = text(note, "nota de revisión", limit=MAX_NOTE)
        current = stamp()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            gap = db.execute("SELECT status FROM learning_gaps WHERE id=?", (gap_id,)).fetchone()
            if not gap:
                raise DomainError("Hueco no encontrado.", 404)
            if gap["status"] not in {"open", "proposed"}:
                raise DomainError("Este hueco ya fue revisado.", 409)
            db.execute(
                "UPDATE learning_proposals SET status='rejected',reviewed_by=?,reviewed_at=?,review_note=? "
                "WHERE gap_id=? AND status='pending'",
                (actor["id"], current, note or "Hueco descartado.", gap_id),
            )
            db.execute("UPDATE learning_gaps SET status='rejected' WHERE id=?", (gap_id,))
            self.store.audit(db, actor, "learning.gap.reject", gap_id)

    def resolve(self, gap_id, actor):
        """Solo un administrador marca resuelto un hueco aprobado (por ejemplo, tras comprobarlo en el banco)."""
        self.store.require_admin(actor)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            gap = db.execute("SELECT status FROM learning_gaps WHERE id=?", (gap_id,)).fetchone()
            if not gap:
                raise DomainError("Hueco no encontrado.", 404)
            if gap["status"] != "approved":
                raise DomainError("Solo un hueco aprobado puede marcarse resuelto.", 409)
            db.execute("UPDATE learning_gaps SET status='resolved' WHERE id=?", (gap_id,))
            self.store.audit(db, actor, "learning.gap.resolve", gap_id)

    def approved_answers(self, route=None, limit=50):
        """Respuestas aprobadas vigentes, revalidadas al leerlas; para el tramo de integración."""
        clause, values = "p.status='approved' AND g.status IN ('approved','resolved')", []
        if route:
            if route not in ROUTES:
                raise DomainError("Ruta de aprendizaje no válida.", 422)
            clause += " AND g.route=?"
            values.append(route)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT g.id gap_id,g.route,g.question,g.topic,p.id proposal_id,p.proposed_answer answer,p.reviewed_at "
                f"FROM learning_proposals p JOIN learning_gaps g ON g.id=p.gap_id WHERE {clause} "
                "ORDER BY p.reviewed_at DESC LIMIT ?",
                (*values, max(1, min(int(limit), 200))),
            ).fetchall()
        return [dict(row) for row in rows if public_answer_problem(row["answer"]) is None]

    def reviewed_for(self, question, route, limit=3):
        """Hasta ``limit`` respuestas aprobadas cuya pregunta comparte palabras con ``question``.

        Coincidencia por palabras de la clave normalizada (sin las muy cortas); no es
        búsqueda semántica. Lo devuelto ya pasó los validadores al leerlo.
        """
        words = {word for word in question_key(redact(question)).split() if len(word) > 3}
        if not words:
            return []
        scored = []
        for item in self.approved_answers(route, limit=200):
            other = {word for word in question_key(item["question"]).split() if len(word) > 3}
            overlap = len(words & other)
            if overlap >= 2 or (overlap and overlap == len(other)):
                scored.append((overlap / len(words | other), item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [{"question": item["question"], "answer": item["answer"]} for _, item in scored[:limit]]

    # --- retención ----------------------------------------------------------
    def maybe_purge(self, interval_seconds=86400):
        """Limpieza de retención como mucho una vez por intervalo en este proceso."""
        current = time.monotonic()
        if self._last_purge and current - self._last_purge < interval_seconds:
            return None
        self._last_purge = current
        return self.purge_expired()

    def purge_expired(self, actor=None, *, current=None, days=RETENTION_DAYS):
        """Borra huecos no aprobados cuya última aparición supera ``days`` días, con sus propuestas.

        Explícita: nada la llama sola. No sustituye las solicitudes de ``privacy.py``.
        """
        if actor is not None:
            self.store.require_admin(actor)
        cutoff = ((current or datetime.now(UTC)) - timedelta(days=days)).isoformat()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ids = [row["id"] for row in db.execute(
                "SELECT id FROM learning_gaps WHERE status IN ('open','proposed','rejected') AND last_seen_at<?",
                (cutoff,))]
            for gap_id in ids:
                db.execute("DELETE FROM learning_proposals WHERE gap_id=?", (gap_id,))
                db.execute("DELETE FROM learning_gaps WHERE id=?", (gap_id,))
            if ids or actor is not None:  # sin ruido en auditoría cuando no hay nada que borrar
                self.store.audit(db, actor, "learning.gap.purge", str(len(ids)))
        return len(ids)

    # --- banco de preguntas -------------------------------------------------
    def seed_cases(self, cases):
        """Inserta o actualiza los casos iniciales (``source='seed'``); no toca casos del equipo."""
        current = stamp()
        with self.store.connect() as db:
            for case in cases:
                db.execute(
                    "INSERT INTO learning_eval_cases(id,route,question,expectations,source,active,created_at,updated_at)"
                    " VALUES(?,?,?,?,'seed',1,?,?) ON CONFLICT(id) DO UPDATE SET route=excluded.route,"
                    "question=excluded.question,expectations=excluded.expectations,updated_at=excluded.updated_at "
                    "WHERE learning_eval_cases.source='seed'",
                    (case["id"], case["route"], case["question"], json.dumps(case["expectations"], ensure_ascii=False),
                     current, current),
                )

    def eval_cases(self, route=None):
        clause, values = "active=1", []
        if route:
            clause += " AND route=?"
            values.append(route)
        with self.store.connect() as db:
            rows = db.execute(f"SELECT * FROM learning_eval_cases WHERE {clause} ORDER BY id", values).fetchall()
        return [dict(row) | {"expectations": json.loads(row["expectations"])} for row in rows]

    def save_run(self, *, started_at, model, route, results, actor=None):
        passed = sum(1 for item in results if item["ok"])
        total = len(results)
        failed_ids = [item["case_id"] for item in results if not item["ok"]]
        replaced = [item["case_id"] for item in results if item.get("replaced")]
        summary = f"{passed} de {total} casos pasan." + (" Fallan: " + ", ".join(failed_ids) + "." if failed_ids else "")
        if replaced:
            # Una sustitución protege a la persona, pero indica que el modelo no contestó bien.
            summary += (f" {len(replaced)} con la respuesta del modelo retirada y sustituida por el mensaje seguro: "
                        + ", ".join(replaced) + ".")
        run_id = uid()
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO learning_eval_runs(id,started_at,finished_at,model,route,total,passed,failed,results,summary,created_by)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, started_at, stamp(), model, route, total, passed, total - passed,
                 json.dumps(results, ensure_ascii=False), summary, actor["id"] if actor else None),
            )
            self.store.audit(db, actor, "learning.eval.run", run_id)
        return self.latest_run(run_id=run_id)

    def latest_run(self, run_id=None):
        with self.store.connect() as db:
            if run_id:
                row = db.execute("SELECT * FROM learning_eval_runs WHERE id=?", (run_id,)).fetchone()
            else:
                row = db.execute("SELECT * FROM learning_eval_runs ORDER BY finished_at DESC LIMIT 1").fetchone()
        if not row:
            return None
        tz = self._zone()
        return dict(row) | {"results": json.loads(row["results"]), "finished_local": _local(row["finished_at"], tz)}
