"""Owned web consultation: deterministic advice and transactional appointment tools.

The conversational motor never calls a remote model. Only the booking tool can
confirm an appointment, after explicit consent and a real availability check.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta

from .conversation import IntentDecision, classify_message
from .core import DomainError, stamp, text, uid, zone
from . import privacy


WELCOME = (
    "Soy R.E.I.G.E.L., asistente virtual de Power Solar. Puedo orientarte, atender tus dudas "
    "y ayudarte a reservar una evaluación en un horario disponible. También puedes pedir atención humana. "
    "¿Qué te interesa más: reducir tu factura, tener respaldo durante apagones o ambas cosas? "
    "No compartas documentos, cuentas ni datos bancarios por el chat."
)
MUNICIPALITIES = (
    "Adjuntas", "Aguada", "Aguadilla", "Aguas Buenas", "Aibonito", "Añasco", "Arecibo", "Arroyo", "Barceloneta",
    "Barranquitas", "Bayamón", "Cabo Rojo", "Caguas", "Camuy", "Canóvanas", "Carolina", "Cataño", "Cayey",
    "Ceiba", "Ciales", "Cidra", "Coamo", "Comerío", "Corozal", "Culebra", "Dorado", "Fajardo", "Florida",
    "Guánica", "Guayama", "Guayanilla", "Guaynabo", "Gurabo", "Hatillo", "Hormigueros", "Humacao", "Isabela",
    "Jayuya", "Juana Díaz", "Juncos", "Lajas", "Lares", "Las Marías", "Las Piedras", "Loíza", "Luquillo",
    "Manatí", "Maricao", "Maunabo", "Mayagüez", "Moca", "Morovis", "Naguabo", "Naranjito", "Orocovis",
    "Patillas", "Peñuelas", "Ponce", "Quebradillas", "Rincón", "Río Grande", "Sabana Grande", "Salinas",
    "San Germán", "San Juan", "San Lorenzo", "San Sebastián", "Santa Isabel", "Toa Alta", "Toa Baja",
    "Trujillo Alto", "Utuado", "Vega Alta", "Vega Baja", "Vieques", "Villalba", "Yabucoa", "Yauco",
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS web_chat_sessions (
 token_hash TEXT PRIMARY KEY, conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(id),
 expires_at TEXT NOT NULL, opted_out INTEGER NOT NULL DEFAULT 0,
 profile_json TEXT NOT NULL DEFAULT '{}', appointment_id TEXT REFERENCES appointments(id),
 sources_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS web_chat_requests (
 token_hash TEXT NOT NULL REFERENCES web_chat_sessions(token_hash) ON DELETE CASCADE,
 request_id TEXT NOT NULL, kind TEXT NOT NULL, payload_hash TEXT NOT NULL,
 response_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(token_hash, request_id)
);
"""


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class WebChat:
    # The local model may only replace the deterministic fallback for messages
    # the classifier cannot place. Booking, consent, opt-out and verified
    # commercial answers never depend on model output.
    AI_FALLBACK_INTENTS = frozenset({"unsupported_or_ambiguous"})

    def __init__(self, store, knowledge):
        self.store = store
        self.knowledge = knowledge
        with store.connect() as db:
            db.executescript(SCHEMA)
        privacy.initialize(store)

    @staticmethod
    def _token_hash(token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token):
            raise DomainError("La sesión del chat ha terminado. Abre de nuevo el asistente.", 401)
        return digest(token)

    def _session(self, db, token):
        key = self._token_hash(token)
        row = db.execute("SELECT * FROM web_chat_sessions WHERE token_hash=? AND expires_at>?", (key, stamp())).fetchone()
        if not row:
            raise DomainError("La sesión del chat ha terminado. Abre de nuevo el asistente.", 401)
        return row

    def _view(self, db, session, reply="", actions=None):
        conversation = db.execute("SELECT * FROM conversations WHERE id=?", (session["conversation_id"],)).fetchone()
        rows = db.execute("""SELECT direction,text,created_at FROM messages WHERE conversation_id=?
            AND (direction='inbound' OR (direction='outbound' AND status='sent'))
            ORDER BY created_at DESC,rowid DESC LIMIT 60""", (session["conversation_id"],)).fetchall()
        profile = json.loads(session["profile_json"])
        result = {
            "conversation_id": session["conversation_id"], "messages": [dict(r) for r in reversed(rows)],
            "mode": conversation["mode"], "opted_out": bool(session["opted_out"]),
            "engine": "motor_comercial_local", "knowledge": self.knowledge.public_status(),
            "reply": reply, "actions": actions or [], "sources": json.loads(session["sources_json"]),
            "profile": {key: profile[key] for key in ("priority", "municipality", "monthly_bill") if key in profile},
            "privacy_requests": privacy.public_requests(db, session["conversation_id"]),
        }
        if session["appointment_id"]:
            appointment = db.execute("""SELECT a.id,a.start_at,a.end_at,a.status,u.name advisor_name
                FROM appointments a JOIN users u ON u.id=a.advisor_id WHERE a.id=?""", (session["appointment_id"],)).fetchone()
            if appointment:
                result["appointment"] = dict(appointment)
        return result

    @staticmethod
    def _append(db, conversation_id, direction, value):
        db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)", (uid(), conversation_id, direction, value, "received" if direction == "inbound" else "sent", None, stamp()))
        db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (stamp(), conversation_id))

    def start(self, token=None):
        with self.store.connect() as db:
            if token:
                try:
                    session = self._session(db, token)
                    return token, self._view(db, session)
                except DomainError:
                    pass
            db.execute("BEGIN IMMEDIATE")
            token = secrets.token_urlsafe(32)
            key, conversation_id = digest(token), uid()
            advisor = db.execute("""SELECT u.id,count(c.id) n FROM users u LEFT JOIN conversations c ON c.advisor_id=u.id
                WHERE u.active=1 AND u.public_booking=1 GROUP BY u.id ORDER BY n,u.created_at LIMIT 1""").fetchone()
            db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?,?,?)", (conversation_id, "web", uid(), "Visitante web", None, advisor["id"] if advisor else None, "ai", stamp()))
            expiry = (datetime.now(UTC) + timedelta(days=7)).isoformat()
            db.execute("INSERT INTO web_chat_sessions(token_hash,conversation_id,expires_at) VALUES(?,?,?)", (key, conversation_id, expiry))
            self._append(db, conversation_id, "outbound", WELCOME)
            session = self._session(db, token)
            return token, self._view(db, session, WELCOME, ["book", "human"])

    def state(self, token):
        with self.store.connect() as db:
            return self._view(db, self._session(db, token))

    def reply_allowed(self, conversation_id):
        """Staff guards use the same persistent opt-out as the automatic motor."""
        with self.store.connect() as db:
            row = db.execute("SELECT opted_out FROM web_chat_sessions WHERE conversation_id=?", (conversation_id,)).fetchone()
            # An arbitrary conversation identifier must never bypass the web guard.
            return bool(row is not None and not row["opted_out"])

    @staticmethod
    def _ai_fingerprint(db, session):
        count = db.execute("SELECT count(*) FROM messages WHERE conversation_id=?", (session["conversation_id"],)).fetchone()[0]
        return digest(f"{session['conversation_id']}|{count}|{session['profile_json']}")

    def ai_brief(self, token, message_text, request_id):
        """Return context for an optional model reply without writing state."""
        incoming = text(message_text, "mensaje", limit=2000, required=True)
        with self.store.connect() as db:
            session = self._session(db, token)
            _, _, previous = self._request(db, session, request_id, "message", {"text": incoming})
            if previous is not None or session["opted_out"]:
                return None
            conversation = db.execute("SELECT * FROM conversations WHERE id=?", (session["conversation_id"],)).fetchone()
            if not conversation or conversation["mode"] != "ai":
                return None
            profile = json.loads(session["profile_json"])
            if "monthly_bill" in profile and "bill_period" not in profile:
                profile["bill_amount"] = profile["monthly_bill"]
                profile["bill_period"] = "monthly"
            clean = self._safe_customer_text(incoming)
            if classify_message(normalized(clean), context=profile).intent not in self.AI_FALLBACK_INTENTS:
                return None
            rows = db.execute("""SELECT direction,text FROM messages WHERE conversation_id=?
                AND (direction='inbound' OR (direction='outbound' AND status='sent'))
                ORDER BY created_at DESC,rowid DESC LIMIT 12""", (session["conversation_id"],)).fetchall()
            verified = self.knowledge.answer(clean)
            return {
                "incoming": clean,
                "history": [dict(row) for row in reversed(rows)],
                "profile": profile,
                "verified": verified.get("text", "") if isinstance(verified, dict) else "",
                "fingerprint": self._ai_fingerprint(db, session),
            }

    @staticmethod
    def _request(db, session, request_id, kind, payload):
        request_id = text(request_id, "referencia de solicitud", limit=100, required=True)
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,100}", request_id):
            raise DomainError("La referencia de la solicitud no es válida.", 422)
        content_hash = digest(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
        existing = db.execute("SELECT * FROM web_chat_requests WHERE token_hash=? AND request_id=?", (session["token_hash"], request_id)).fetchone()
        if existing:
            if existing["kind"] != kind or existing["payload_hash"] != content_hash:
                raise DomainError("Esta referencia ya corresponde a otra solicitud.", 409)
            return request_id, content_hash, json.loads(existing["response_json"])
        return request_id, content_hash, None

    @staticmethod
    def _save_request(db, session, request_id, kind, content_hash, result):
        db.execute("INSERT INTO web_chat_requests VALUES(?,?,?,?,?,?)", (session["token_hash"], request_id, kind, content_hash, json.dumps(result, ensure_ascii=False), stamp()))

    @staticmethod
    def _safe_customer_text(value):
        # Contacts belong in the consented appointment form, not in pre-consent history.
        value = re.sub(r"[^\s@]+@[^\s@]+\.[^\s@]+", "[correo omitido; usa el formulario de cita]", value)
        value = re.sub(r"(?<!\w)\+?(?:\d[ ()-]*){7,16}(?!\w)", "[número omitido; usa el formulario de cita]", value)
        return value

    def message(self, token, message_text, request_id, ai_reply=None, ai_fingerprint=None):
        incoming = text(message_text, "mensaje", limit=2000, required=True)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, token)
            request_id, content_hash, previous = self._request(db, session, request_id, "message", {"text": incoming})
            if previous is not None:
                # A retry must not resurrect an old appointment, mode or opt-out
                # snapshot after staff or the visitor changed the conversation.
                return self._view(db, session)
            if ai_reply and ai_fingerprint != self._ai_fingerprint(db, session):
                # State changed while the optional model was drafting; ignore it.
                ai_reply = None
            incoming = self._safe_customer_text(incoming)
            self._append(db, session["conversation_id"], "inbound", incoming)
            conversation = db.execute("SELECT * FROM conversations WHERE id=?", (session["conversation_id"],)).fetchone()
            value = normalized(incoming)
            profile = json.loads(session["profile_json"])
            if "monthly_bill" in profile and "bill_period" not in profile:
                # Profiles created before bill-period confirmation already used
                # the explicitly monthly question and retain that meaning.
                profile["bill_amount"] = profile["monthly_bill"]
                profile["bill_period"] = "monthly"
            decision = classify_message(value, context=profile)
            reply, actions, sources = "", [], []
            command = re.sub(r"[.!¡¿?]", "", value).strip()
            if value == "/start":
                # Only an explicit command received through this visitor's bearer
                # session reopens assistance. Staff mode changes never lift a stop.
                db.execute("UPDATE web_chat_sessions SET opted_out=0 WHERE token_hash=?", (session["token_hash"],))
                db.execute("UPDATE conversations SET mode='ai',updated_at=? WHERE id=?", (stamp(), session["conversation_id"]))
                reply = "Has reanudado la asistencia automática de R.E.I.G.E.L. en este chat. Puedes volver a detenerla escribiendo /stop o pedir atención humana. " + self._next_question(profile)
                actions = ["book", "human"]
            elif decision.intent == "privacy_request":
                kind = decision.entities["request_kind"]
                registered, created = privacy.create_session_request(db, session, kind, incoming, self.store)
                db.execute("UPDATE conversations SET mode='human' WHERE id=?", (session["conversation_id"],))
                labels = {"access": "acceso a tus datos", "correction": "corrección de tus datos", "deletion": "eliminación de tus datos"}
                reply = f"Tu solicitud de {labels[kind]} {'quedó registrada' if created else 'ya está registrada y pendiente de revisión'} con referencia {registered['id']}. "
                reply += "El equipo debe verificar tu identidad y revisar el alcance y la conservación aplicable. No se han eliminado, modificado ni entregado datos automáticamente. No compartas documentos de identidad por este chat."
                if kind == "deletion":
                    db.execute("UPDATE web_chat_sessions SET opted_out=1 WHERE token_hash=?", (session["token_hash"],))
                    reply += " Además, la asistencia comercial en este chat queda detenida; esa baja es independiente de la solicitud de eliminación."
                actions = ["human"]
            elif decision.intent == "opt_out":
                db.execute("UPDATE web_chat_sessions SET opted_out=1 WHERE token_hash=?", (session["token_hash"],))
                db.execute("UPDATE conversations SET mode='human' WHERE id=?", (session["conversation_id"],))
                reply = "He detenido la asistencia comercial automática en este chat. No enviaré más respuestas de venta. Si necesitas ayuda, puedes solicitar atención humana."
                actions = ["human"]
            elif session["opted_out"]:
                # Opting out is persistent; a sales phrase cannot silently undo it.
                reply = ""
                actions = ["human"]
            elif decision.intent == "human":
                db.execute("UPDATE conversations SET mode='human' WHERE id=?", (session["conversation_id"],))
                reply = "Tu solicitud de atención humana quedó registrada en esta conversación. El equipo podrá responder aquí cuando esté disponible; no puedo prometer un tiempo de respuesta."
            elif conversation["mode"] == "human":
                # The advisor owns the floor; store inbound without an automated sales reply.
                reply = ""
            else:
                updated_facts = []
                if decision.intent != "contradiction":
                    updated_facts = self._qualify(profile, value, decision)
                reply, actions, sources = self._answer(
                    value, profile, session, db, decision, updated_facts, ai_reply=ai_reply
                )
            db.execute("UPDATE web_chat_sessions SET profile_json=?,sources_json=? WHERE token_hash=?", (json.dumps(profile, ensure_ascii=False), json.dumps(sources, ensure_ascii=False), session["token_hash"]))
            if reply:
                self._append(db, session["conversation_id"], "outbound", reply)
            session = self._session(db, token)
            result = self._view(db, session, reply, actions)
            self._save_request(db, session, request_id, "message", content_hash, result)
            return result

    @staticmethod
    def _qualify(profile, value, decision: IntentDecision | None = None):
        original = dict(profile)
        decision = decision or classify_message(value, context=profile)
        if profile.get("last_question") == "monthly_bill" and re.search(r"\b(omitir|omito|prefiero no|no compartir)\b", value):
            profile.pop("monthly_bill", None)
            profile.pop("bill_amount", None)
            profile["bill_period"] = "declined"
        elif profile.get("last_question") == "bill_period":
            if decision.intent == "bill_confirmation":
                if "bill_amount" in profile:
                    profile["monthly_bill"] = profile["bill_amount"]
                profile["bill_period"] = "monthly"
            elif re.search(r"\b(?:anual|por ano|cada ano)\b", value):
                profile.pop("monthly_bill", None)
                profile["bill_period"] = "annual"
            elif decision.intent == "bill_uncertain":
                profile.pop("monthly_bill", None)
                profile.pop("bill_amount", None)
                profile["bill_period"] = "declined"
        if re.search(r"\b(ambas|ambos|las dos|todo)\b", value):
            profile["priority"] = "factura y respaldo"
        elif re.search(r"\b(?:no quiero|no necesito|sin)\s+(?:el )?(?:respaldo|bateria)\b", value) and re.search(r"\b(factura|ahorro|ahorrar|consumo)\b", value):
            profile["priority"] = "factura"
        elif re.search(r"\b(apagon|apagones|respaldo|bateria|baterias)\b", value):
            profile["priority"] = "respaldo"
        elif re.search(r"\b(factura|ahorro|ahorrar|consumo)\b", value):
            profile["priority"] = "factura"
        municipality_matches = []
        for municipality in MUNICIPALITIES:
            match = re.search(r"\b" + re.escape(normalized(municipality)) + r"\b", value)
            if match:
                municipality_matches.append((match.start(), municipality))
        if municipality_matches:
            # A correction or explicit contrast is resolved by the final place
            # mentioned, not whichever municipality sorts first.
            if decision.intent == "correction" or re.search(r"\b(?:no|pero|sino)\b", value):
                profile["municipality"] = max(municipality_matches)[1]
            else:
                profile["municipality"] = min(municipality_matches)[1]

        bill_matches = list(re.finditer(
            r"(?:factura(?:\s+(?:es\s+de|de|es))?|pago|mensual(?:es)?(?:\s+(?:es|de))?|al mes|\$)\s*\$?\s*(\d{1,5}(?:[.,]\d{1,2})?)\b|"
            r"(?<!\w)\$?(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:dolares|al mes|mensual(?:es)?)\b",
            value,
        ))
        if decision.intent == "bill_answer" and "bill_amount" in decision.entities:
            amount = decision.entities["bill_amount"]
            profile["bill_amount"] = amount
            profile["monthly_bill"] = amount
            profile["bill_period"] = "monthly"
        elif not bill_matches and profile.get("last_question") == "monthly_bill":
            bill_matches = list(re.finditer(r"\$?(\d{1,5}(?:[.,]\d{1,2})?)", value))
            if len(bill_matches) != 1 or not re.fullmatch(
                r"\s*(?:\$?\s*\d{1,5}(?:[.,]\d{1,2})?\s*(?:dolares|al mes|mensuales)?|si|mensual|al mes)\s*",
                value,
            ):
                bill_matches = []
        if bill_matches:
            selected = bill_matches[-1] if decision.intent == "correction" else bill_matches[0]
            amount_text = selected.group(1) or selected.group(2)
            amount = float(amount_text.replace(",", "."))
            if 0 <= amount <= 100000:
                profile["bill_amount"] = amount
                if re.search(r"\b(?:mensual(?:es)?|al mes|por mes|cada mes)\b", value) or profile.get("last_question") == "monthly_bill":
                    profile["monthly_bill"] = amount
                    profile["bill_period"] = "monthly"
                else:
                    profile.pop("monthly_bill", None)
                    profile["bill_period"] = "unknown"
                    profile["last_question"] = "bill_period"
        loads = [
            label
            for pattern, label in (
                (r"\b(?:nevera|refrigerador)\b", "nevera"),
                (r"\b(?:abanicos?|ventiladores?)\b", "abanicos"),
                (r"\b(?:luces|iluminacion)\b", "luces"),
                (r"\b(?:bomba(?: de agua)?)\b", "bomba"),
                (r"\b(?:aire acondicionado|ac)\b", "aire acondicionado"),
                (r"\b(?:equipo medico|equipo medico)\b", "equipo medico"),
                (r"\b(?:router|internet|wifi)\b", "internet"),
                (r"\b(?:televisor|television|tv)\b", "television"),
            )
            if re.search(pattern, value)
        ]
        if loads:
            profile["backup_loads"] = loads
        return [
            key
            for key in ("priority", "municipality", "bill_amount", "monthly_bill", "bill_period", "backup_loads")
            if profile.get(key) != original.get(key)
        ]

    @staticmethod
    def _next_question(profile):
        if "priority" not in profile:
            field, question = "priority", "¿Tu prioridad es la factura, el respaldo durante apagones o ambas cosas?"
        elif "municipality" not in profile:
            field, question = "municipality", "¿En qué municipio está tu propiedad?"
        elif profile.get("bill_period") == "unknown":
            field, question = "bill_period", "¿Ese importe corresponde a tu factura mensual?"
        elif "monthly_bill" not in profile:
            if profile.get("bill_period") in {"annual", "declined"}:
                field, question = "booking", "Podemos continuar sin ese dato y revisar tu caso en una evaluación. ¿Deseas consultar los horarios disponibles?"
            else:
                field, question = "monthly_bill", "¿Cuánto pagas aproximadamente al mes de luz? Puedes omitirlo si prefieres."
        else:
            field, question = "booking", "Podemos revisar tu caso en una evaluación. ¿Deseas consultar los horarios disponibles?"
        profile["last_question"] = field
        return question

    def _answer(
        self,
        value,
        profile,
        session,
        db,
        decision: IntentDecision | None = None,
        updated_facts: list[str] | None = None,
        ai_reply: str | None = None,
    ):
        decision = decision or classify_message(value, context=profile)
        actions, sources = ["book", "human"], []
        if decision.intent == "safety":
            return "Puedo ayudarte con orientación solar y la agenda. No compartas contraseñas, tarjetas, cuentas ni documentos aquí. Para una evaluación, utiliza el formulario seguro de reserva.", actions, sources
        if decision.intent == "appointment_change":
            return "El cambio o la cancelación necesita revisión del equipo. Pide atención humana en este chat para gestionarlo; tu cita sigue igual hasta que se registre el cambio.", ["human"], sources
        if decision.intent == "booking":
            available = db.execute("SELECT 1 FROM users WHERE active=1 AND public_booking=1 LIMIT 1").fetchone()
            if available:
                return "Consulta un día y un horario en la agenda de abajo. Después completa tus datos y autoriza el contacto. La cita sólo estará confirmada cuando aparezca su referencia; esta conversación por sí sola no reserva un espacio.", ["book"], sources
            return "El equipo todavía no ha publicado horarios de atención. Puedes solicitar atención humana aquí o dejar tu solicitud de contacto en la página. Aún no hay una cita reservada.", ["human"], sources
        if decision.intent == "technical_question":
            answer = self.knowledge.answer_technical(value)
            if answer and answer["status"] == "verified":
                return answer["text"], actions, answer["sources"]
            if answer:
                return answer["text"], ["human"], answer["sources"]
            return "No encontré una respuesta técnica clara en las fuentes verificadas disponibles. ¿Qué equipo o concepto específico quieres consultar?", ["human"], sources
        if decision.intent == "contradiction":
            profile["last_question"] = "monthly_bill"
            return "Mencionaste más de un importe y no quiero asumir cuál corresponde a tu factura. ¿Cuánto pagas aproximadamente al mes? Puedes omitir el dato.", ["book", "human"], sources
        if decision.intent == "correction":
            if updated_facts:
                reply = "Gracias por la corrección. Actualicé ese dato para esta conversación y no asumiré resultados de ahorro."
            else:
                return "Quiero actualizarlo correctamente. ¿Qué dato o importe debo corregir?", actions, sources
        elif decision.intent == "bill_confirmation":
            amount = profile.get("monthly_bill")
            if amount is not None:
                reply = f"Perfecto, tomaré ${amount:g} como tu factura mensual para esta conversación."
            else:
                reply = "Gracias por confirmarlo."
        elif decision.intent == "bill_answer":
            amount = profile.get("monthly_bill")
            reply = (
                f"Gracias, anoto ${amount:g} como importe mensual para esta conversación."
                if amount is not None
                else "No pude registrar ese importe con certeza. Puedes escribirlo de nuevo o continuar sin ese dato."
            )
        elif decision.intent == "bill_uncertain":
            reply = "No pasa nada; podemos continuar sin ese dato. No hace falta que compartas la factura ni documentos por el chat."
        elif decision.intent == "decline":
            return "Entendido. No insistiré ni iniciaré una reserva. Si más adelante quieres orientación, puedes volver a escribir.", [], sources
        elif decision.intent == "budget_objection":
            reply = "Es razonable cuidar tu presupuesto. Una comparación útil mira el costo total, las condiciones y lo que el sistema cubriría en tu hogar. Podemos evaluar tu caso antes de hablar de una propuesta; no necesitas decidir hoy."
        elif decision.intent == "trust_objection":
            reply = "Pide una propuesta por escrito y revisa equipos, alcance, garantías y condiciones antes de comprometerte. Tus preguntas merecen respuestas concretas. Podemos comenzar por la duda que más te preocupa y, si hace falta, pasarla a una persona del equipo."
        elif decision.intent == "defer":
            return "Tómate el tiempo que necesites. Si te ayuda a comparar opciones, podemos aclarar una duda concreta o consultar una evaluación cuando tú lo decidas. No hay una reserva ni una compra por conversar aquí.", actions, sources
        elif decision.intent in {"commercial_terms", "financing", "guaranteed_savings"}:
            reply = "No tengo una propuesta vigente y validada para tu hogar, así que no puedo prometer precios, aprobación, ahorros, incentivos ni condiciones de garantía. Lo útil es revisar tu consumo y tus prioridades para pedir una propuesta por escrito y comparar sus condiciones."
        elif decision.intent == "maintenance":
            technical = self.knowledge.answer_technical(value)
            if technical:
                return technical["text"], ["human"], technical["sources"]
            return "Para mantenimiento o una avería, el equipo necesita revisar tu caso. Describe el problema sin compartir números de cuenta ni documentos. Este chat no diagnostica fallas eléctricas ni confirma una visita técnica.", ["human"], sources
        elif decision.intent == "existing_system":
            return "Para un sistema existente o una avería, el equipo necesita revisar tu caso. Pide atención humana y describe el problema sin compartir números de cuenta ni documentos. Este chat no diagnostica fallas eléctricas ni confirma una visita técnica.", ["human"], sources
        elif decision.intent == "backup":
            technical = self.knowledge.answer_technical(value)
            if technical:
                if technical["status"] == "verified":
                    return technical["text"], actions, technical["sources"]
                return technical["text"], ["human"], technical["sources"]
            if profile.get("backup_loads"):
                return "Gracias por indicar esas cargas. La capacidad y la autonomía dependen del diseño y requieren evaluación técnica; este chat no puede calcularlas con certeza. Si quieres, podemos pasar la consulta al equipo.", ["book", "human"], sources
            answer = self.knowledge.answer(value)
            if answer and isinstance(answer.get("text"), str):
                reply, sources = answer["text"], answer.get("sources", [])
                reply += " ¿Qué equipos te importa mantener funcionando?"
            else:
                reply = "Si buscas respaldo durante apagones, hay que evaluar batería, diseño y las cargas que quieres mantener encendidas. Los paneles conectados a la red, por sí solos, no garantizan respaldo. ¿Qué equipos te importa mantener funcionando?"
            profile["last_question"] = "loads"
            return reply, actions, sources
        elif decision.intent == "consumption":
            technical = self.knowledge.answer_technical(value)
            if technical:
                if technical["status"] == "verified":
                    return technical["text"], actions, technical["sources"]
                return technical["text"], ["human"], technical["sources"]
            reply = "No hace falta que conozcas los kWh ahora. Una factura reciente puede ayudar al equipo a evaluar el consumo, pero no la compartas por este chat. Si sabes el importe mensual aproximado, puedes indicarlo; también puedes omitirlo."
            profile["last_question"] = "monthly_bill"
            return reply, actions, sources
        elif decision.intent == "company_information":
            answer = self.knowledge.answer(value)
            if answer and isinstance(answer.get("text"), str):
                reply, sources = answer["text"], answer.get("sources", [])
            else:
                return "No tengo información vigente verificada para responder esa pregunta específica sobre Power Solar. Puedo pedir al equipo que la confirme; prefiero no inventar direcciones, ofertas ni condiciones.", ["human"], sources
        elif decision.intent == "greeting":
            reply = "Hola. Soy R.E.I.G.E.L., asistente virtual de Power Solar. ¿Qué te interesa revisar hoy: tu factura, respaldo durante apagones o una pregunta sobre el proceso?"
            return reply, actions, sources
        elif decision.intent == "contextual_follow_up":
            if "municipality" in (updated_facts or []):
                reply = (
                    f"Gracias, tomo {profile['municipality']} como referencia para esta conversación. "
                    "La viabilidad y la propuesta se determinan durante la evaluación."
                )
                return reply + " " + self._next_question(profile), actions, sources
            if profile.get("last_question") == "loads":
                self._qualify(profile, value, decision)
                if profile.get("backup_loads"):
                    return "Gracias, tomo esas cargas como referencia. La autonomía y la capacidad dependen del diseño y requieren evaluación técnica.", actions, sources
                return "No entendí con certeza qué equipos quieres mantener encendidos. ¿Puedes mencionarlos o prefieres pasar la consulta al equipo?", actions, sources
            if profile.get("last_question") == "bill_period":
                return "No quiero asumir la frecuencia de ese importe. ¿Corresponde a un mes, a un año o prefieres omitir ese dato?", actions, sources
            return "No entendí con certeza tu respuesta. ¿Puedes aclararla con otras palabras o prefieres continuar sin ese dato?", actions, sources
        elif profile.get("bill_period") == "unknown":
            amount = profile.get("bill_amount")
            return f"Anoto ${amount:g} como importe indicado, sin asumir la frecuencia. ¿Corresponde a tu factura mensual?" if amount is not None else "¿Ese importe corresponde a tu factura mensual?", actions, sources
        else:
            if ai_reply:
                reply = ai_reply if "?" in ai_reply else ai_reply + " " + self._next_question(profile)
                return reply, actions, sources
            if decision.intent == "company_information":
                answer = None
            else:
                answer = self.knowledge.answer(value)
            if answer and isinstance(answer.get("text"), str):
                reply, sources = answer["text"], answer.get("sources", [])
            elif "municipality" in profile and re.search(r"\b" + re.escape(normalized(profile["municipality"])) + r"\b", value):
                reply = f"Gracias. Tomo {profile['municipality']} como referencia para esta conversación. La viabilidad y la propuesta se determinan durante la evaluación."
            elif "monthly_bill" in profile or "priority" in profile:
                reply = "Con ese contexto podemos enfocar mejor la evaluación. El siguiente paso es revisar datos de tu hogar antes de prometer resultados."
            else:
                reply = "No entendí con certeza qué necesitas. Puedo orientarte sobre factura eléctrica, respaldo, sistemas solares o coordinar una evaluación; también puedo pedir ayuda al equipo."
                return reply, actions, sources
        return reply + " " + self._next_question(profile), actions, sources

    def human(self, token):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, token)
            current = db.execute("SELECT mode FROM conversations WHERE id=?", (session["conversation_id"],)).fetchone()
            reply = ""
            if current["mode"] != "human":
                reply = "Tu solicitud de atención humana quedó registrada. El equipo podrá responder en este chat cuando esté disponible; no puedo prometer un tiempo de respuesta."
                db.execute("UPDATE conversations SET mode='human',updated_at=? WHERE id=?", (stamp(), session["conversation_id"]))
                self._append(db, session["conversation_id"], "outbound", reply)
            return self._view(db, session, reply)

    def book(self, token, data):
        if not isinstance(data, dict):
            raise DomainError("Revisa los datos de la reserva.", 422)
        clean = {key: value for key, value in data.items() if key != "request_id"}
        # Validate before locking; this never creates a lead.
        lead_data = self.store.normalize_lead(clean, public=True)
        advisor_id = text(clean.get("advisor_id"), "asesor", limit=100, required=True)
        try:
            selected = datetime.fromisoformat(clean.get("start_at", ""))
            if selected.tzinfo is None or selected.utcoffset() is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise DomainError("La cita necesita fecha, hora y zona horaria válidas.", 422) from None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, token)
            request_id, content_hash, previous = self._request(db, session, data.get("request_id"), "book", clean)
            if previous is not None:
                # Return current reservation status if staff cancelled it after the
                # original request; an old idempotency key must not reconfirm it.
                return self._view(db, session, actions=["human"])
            if session["opted_out"]:
                raise DomainError("La asistencia comercial está detenida. Pide atención humana para gestionar una cita.", 409)
            # One active appointment per browser consultation prevents repeated clicks
            # with different request identifiers from creating unwanted extra leads.
            if session["appointment_id"]:
                previous_appointment = db.execute("SELECT status FROM appointments WHERE id=?", (session["appointment_id"],)).fetchone()
                if previous_appointment and previous_appointment["status"] == "confirmed":
                    raise DomainError("Este chat ya tiene una cita confirmada. Pide atención humana para cambiarla.", 409)
            advisor = self.store._advisor(db, advisor_id, True)
            day = selected.astimezone(zone(advisor["timezone"])).date().isoformat()
            slots = self.store._slots(db, advisor, day)["slots"]
            match = next((slot for slot in slots if datetime.fromisoformat(slot["start_at"]) == selected), None)
            if match is None:
                raise DomainError("Ese horario ya no está disponible. Selecciona otro.", 409)
            begin = selected.astimezone(UTC).isoformat()
            end = datetime.fromisoformat(match["end_at"]).astimezone(UTC).isoformat()
            duplicate = db.execute("""SELECT 1 FROM appointments a JOIN leads l ON l.id=a.lead_id
                WHERE a.status='confirmed' AND a.start_at<? AND a.end_at>?
                AND ((?<>'' AND l.email=? COLLATE NOCASE) OR (?<>'' AND l.phone=?))""",
                (end, begin, lead_data["email"], lead_data["email"], lead_data["phone"], lead_data["phone"])).fetchone()
            if duplicate:
                raise DomainError("Ya existe una cita para este contacto en ese horario.", 409)
            lead_id = self.store._insert_lead(db, lead_data, advisor_id)
            appointment_id = uid()
            db.execute("INSERT INTO appointments VALUES(?,?,?,?,?,?,?,?)", (appointment_id, lead_id, advisor_id, begin, end, "confirmed", "web_chat", stamp()))
            db.execute("UPDATE leads SET stage='cita',updated_at=? WHERE id=?", (stamp(), lead_id))
            db.execute("UPDATE conversations SET lead_id=?,advisor_id=?,contact_name=?,updated_at=? WHERE id=?", (lead_id, advisor_id, lead_data["name"], stamp(), session["conversation_id"]))
            db.execute("UPDATE web_chat_sessions SET appointment_id=? WHERE token_hash=?", (appointment_id, session["token_hash"]))
            self.store.audit(db, None, "appointment.book.web_chat", appointment_id)
            local = selected.astimezone(zone(advisor["timezone"]))
            reply = f"Tu cita quedó confirmada en la agenda de Power Solar para el {local.strftime('%d/%m/%Y a las %H:%M')} ({advisor['timezone']}), con {advisor['name']}. Referencia: {appointment_id}. Guarda esta confirmación."
            self._append(db, session["conversation_id"], "outbound", reply)
            session = self._session(db, token)
            result = self._view(db, session, reply, ["human"])
            self._save_request(db, session, request_id, "book", content_hash, result)
            return result
