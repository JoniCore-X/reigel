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
from .core import DomainError, format_reference, new_reference, stamp, text, uid, zone
from . import privacy, safety, voice


# Saludo mínimo pedido por el titular: los temas de inicio y la nota al pie ya
# orientan y advierten sobre datos sensibles.
WELCOME = "Hola, ¿en qué te ayudo?"
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
            "next_step": self.next_step_ready(profile, conversation, session),
        }
        if session["appointment_id"]:
            appointment = db.execute("""SELECT a.id,a.reference,a.start_at,a.end_at,a.status,u.name advisor_name
                FROM appointments a JOIN users u ON u.id=a.advisor_id WHERE a.id=?""", (session["appointment_id"],)).fetchone()
            if appointment:
                result["appointment"] = {**dict(appointment), "reference": format_reference(appointment["reference"])}
        return result

    @staticmethod
    def next_step_ready(profile, conversation, session):
        """Offer «Coordinar evaluación» / «Hablar con el equipo» once the visitor is prospected.

        Prospected: we know what they want to solve plus one more fact (town, bill
        or loads to back up). The visitor asking for an appointment or a person,
        an existing appointment or a human-handled conversation also qualify.
        """
        qualified = bool(profile.get("priority")) and any(
            profile.get(key) for key in ("municipality", "bill_amount", "monthly_bill", "backup_loads")
        ) or profile.get("bill_period") == "declined" and bool(profile.get("priority"))
        return bool(qualified or profile.get("asked_next_step") or session["appointment_id"]
                    or conversation["mode"] == "human" or session["opted_out"])

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
                # Sin prospecto vinculado no hay memoria que consultar: una visita
                # anónima no arrastra lo que el equipo sabe de otra persona.
                "lead_id": conversation["lead_id"],
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

    # Una baja comercial y una solicitud de privacidad no alimentan la memoria: quien
    # pide parar o pide sus datos no está contando algo para que lo recordemos.
    NO_MEMORY_INTENTS = {"opt_out", "privacy_request"}

    def message(self, token, message_text, request_id, ai_reply=None, ai_fingerprint=None, gaps=None, needs=None,
                beliefs=None):
        """``gaps``, when given, receives ``(reason, text)`` for answers the learning queue
        should see (no verified knowledge, generic fallback). The caller records them
        after this transaction commits; the text is the already-masked message.

        ``needs`` receives the context for a need report when the conversation moves to a
        person: the reason, the conversation, its lead and what the visitor has answered
        so far. The caller builds and stores the report after the commit, for the same
        reason as ``gaps``: this transaction stays short.

        ``beliefs`` receives the raw material for the agent's memory: the conversation,
        its lead, what the visitor has answered and the message itself. The caller runs
        the extraction after the commit, and nothing is collected from a visitor who
        opted out or asked about their data."""
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
            if decision.intent in {"booking", "human", "appointment_change"}:
                # The visitor asked for the next step: offer it even before qualifying.
                profile["asked_next_step"] = True
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
                reply = "¡Listo! Tu solicitud de atención humana quedó registrada. Alguien del equipo te responderá por este mismo chat cuando esté disponible; no puedo prometer un tiempo de respuesta."
                if needs is not None:
                    needs.append(self._need_context("human_requested", conversation, profile, incoming))
            elif conversation["mode"] == "human":
                # The advisor owns the floor; store inbound without an automated sales reply.
                reply = ""
            else:
                updated_facts = []
                if decision.intent != "contradiction":
                    updated_facts = self._qualify(profile, value, decision)
                reasons = []
                reply, actions, sources = self._answer(
                    value, profile, session, db, decision, updated_facts, ai_reply=ai_reply, gaps=reasons
                )
                if gaps is not None:
                    gaps.extend((reason, incoming) for reason in reasons)
                if needs is not None and reasons:
                    needs.append(self._need_context(reasons[0], conversation, profile, incoming))
            if (beliefs is not None and conversation["lead_id"] and not session["opted_out"]
                    and decision.intent not in self.NO_MEMORY_INTENTS):
                beliefs.append({
                    "conversation_id": conversation["id"], "lead_id": conversation["lead_id"],
                    "profile": dict(profile), "message": incoming,
                })
            db.execute("UPDATE web_chat_sessions SET profile_json=?,sources_json=? WHERE token_hash=?", (json.dumps(profile, ensure_ascii=False), json.dumps(sources, ensure_ascii=False), session["token_hash"]))
            if reply:
                self._append(db, session["conversation_id"], "outbound", reply)
            session = self._session(db, token)
            result = self._view(db, session, reply, actions)
            self._save_request(db, session, request_id, "message", content_hash, result)
            return result

    @staticmethod
    def _need_context(reason, conversation, profile, incoming):
        """Lo que hace falta para armar el informe, recogido dentro de la transacción."""
        return {
            "reason": reason, "route": "chat",
            "conversation_id": conversation["id"], "lead_id": conversation["lead_id"],
            "profile": dict(profile), "question": incoming,
            "asked_next_step": bool(profile.get("asked_next_step")),
        }

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
            field, question = "priority", "¿Qué buscas solucionar: las alzas en la factura, las interrupciones del servicio o ambas?"
        elif "municipality" not in profile:
            field, question = "municipality", "Te pregunto, ¿en qué pueblo está tu hogar?"
        elif profile.get("bill_period") == "unknown":
            field, question = "bill_period", "¿Ese importe corresponde a tu factura mensual?"
        elif "monthly_bill" not in profile:
            if profile.get("bill_period") in {"annual", "declined"}:
                field, question = "booking", "¡Sin problema! Eso lo vemos en la evaluación. ¿Quieres ver los horarios disponibles o prefieres hablar con alguien del equipo?"
            else:
                field, question = "monthly_bill", "¿Más o menos cuánto pagas de luz al mes? Si prefieres no decirlo, está bien."
        else:
            field, question = "booking", "¡Excelente! Con eso ya podemos revisar tu caso en una evaluación. ¿Quieres ver los horarios disponibles o prefieres hablar con alguien del equipo?"
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
        gaps: list | None = None,
    ):
        gaps = gaps if gaps is not None else []
        decision = decision or classify_message(value, context=profile)
        actions, sources = ["book", "human"], []
        fixed = safety.reply_for(value, safety.HANDOFF_CHAT)
        if fixed:
            return fixed, ["human"], sources
        if decision.intent == "safety":
            return "Por tu seguridad, no compartas contraseñas, tarjetas, cuentas ni documentos por aquí. Te ayudo con tus dudas de energía solar y con la agenda; para una evaluación usa el formulario seguro de reserva.", actions, sources
        if decision.intent == "appointment_change":
            return "¡Claro! Un cambio o una cancelación lo revisa el equipo. Pide atención humana aquí mismo y lo gestionan; mientras tanto, tu cita sigue igual.", ["human"], sources
        if decision.intent == "booking":
            available = db.execute("SELECT 1 FROM users WHERE active=1 AND public_booking=1 LIMIT 1").fetchone()
            if available:
                return "¡Perfecto! Abajo puedes escoger el día y la hora. Luego completas tus datos y autorizas el contacto. La cita queda confirmada cuando te aparezca su código; esta conversación por sí sola no separa el espacio.", ["book"], sources
            return "Ahora mismo el equipo no tiene horarios publicados. Puedes pedir atención humana aquí o dejar tus datos en la página de contacto. Todavía no hay una cita reservada.", ["human"], sources
        if decision.intent == "technical_question":
            answer = self.knowledge.answer_technical(value)
            if answer and answer["status"] == "verified":
                return answer["text"], actions, answer["sources"]
            if answer:
                return answer["text"], ["human"], answer["sources"]
            gaps.append("no_knowledge")
            return "No encontré una respuesta clara en las fuentes verificadas. ¿Qué equipo o concepto quieres consultar?", ["human"], sources
        if decision.intent == "contradiction":
            profile["last_question"] = "monthly_bill"
            return "Veo más de una cantidad y no quiero asumir cuál es tu factura. ¿Más o menos cuánto pagas al mes? Si prefieres, lo omitimos.", ["book", "human"], sources
        if decision.intent == "correction":
            if updated_facts:
                reply = "¡Gracias por la corrección! Ya lo actualicé y no asumiré resultados de ahorro."
            else:
                return "Quiero anotarlo bien. ¿Qué dato o cantidad debo corregir?", actions, sources
        elif decision.intent == "bill_confirmation":
            amount = profile.get("monthly_bill")
            if amount is not None:
                reply = f"¡Perfecto! Tomo ${amount:g} como tu factura mensual."
            else:
                reply = "¡Gracias por confirmarlo!"
        elif decision.intent == "bill_answer":
            amount = profile.get("monthly_bill")
            reply = (
                f"¡Gracias! Anoto ${amount:g} como tu pago mensual de luz."
                if amount is not None
                else "No pude anotar esa cantidad con seguridad. ¿Me la escribes de nuevo o seguimos sin ese dato?"
            )
        elif decision.intent == "bill_uncertain":
            reply = "¡No pasa nada! Seguimos sin ese dato. No hace falta que compartas la factura ni documentos por aquí."
        elif decision.intent == "decline":
            return "¡Entendido! No insistiré ni haré ninguna reserva. Cuando quieras orientación, aquí estoy.", [], sources
        elif decision.intent == "budget_objection":
            reply = "Te entiendo, es normal cuidar el presupuesto. Para comparar bien hay que mirar el costo total, las condiciones y lo que el sistema cubriría en tu hogar. Eso se revisa en una evaluación antes de hablar de una propuesta, y no tienes que decidir hoy."
        elif decision.intent == "trust_objection":
            reply = "Te entiendo. Pide siempre la propuesta por escrito y revisa equipos, alcance, garantías y condiciones antes de comprometerte. Empecemos por lo que más te preocupa y, si hace falta, se lo paso a una persona del equipo."
        elif decision.intent == "defer":
            return "¡Tómate tu tiempo! Si te ayuda a comparar, aclaramos una duda puntual o vemos una evaluación cuando tú decidas. Conversar aquí no es una reserva ni una compra.", actions, sources
        elif decision.intent in {"commercial_terms", "financing", "guaranteed_savings"}:
            reply = "Todavía no tengo una propuesta validada para tu hogar, así que no puedo prometer precios, aprobación, ahorros, incentivos ni condiciones de garantía. Lo que sí ayuda es revisar tu consumo y lo que buscas resolver, y pedir la propuesta por escrito para comparar."
        elif decision.intent == "maintenance":
            technical = self.knowledge.answer_technical(value)
            if technical:
                return technical["text"], ["human"], technical["sources"]
            return "Para mantenimiento o una avería, alguien del equipo tiene que revisar tu caso. Cuéntame qué pasa, sin compartir números de cuenta ni documentos. Por aquí no puedo diagnosticar fallas eléctricas ni confirmar una visita técnica.", ["human"], sources
        elif decision.intent == "existing_system":
            return "Para un sistema existente o una avería, alguien del equipo tiene que revisar tu caso. Pide atención humana y cuéntales qué pasa, sin compartir números de cuenta ni documentos. Por aquí no puedo diagnosticar fallas eléctricas ni confirmar una visita técnica.", ["human"], sources
        elif decision.intent == "backup":
            technical = self.knowledge.answer_technical(value)
            if technical:
                if technical["status"] == "verified":
                    return technical["text"], actions, technical["sources"]
                return technical["text"], ["human"], technical["sources"]
            if profile.get("backup_loads"):
                return "¡Gracias por decirme esos equipos! Cuánto respaldo tendrías depende del diseño y se calcula en la evaluación técnica; por aquí no puedo calcularlo con certeza. ¿Quieres que se lo pase al equipo?", ["book", "human"], sources
            answer = self.knowledge.answer(value)
            if answer and isinstance(answer.get("text"), str):
                reply, sources = answer["text"], answer.get("sources", [])
                reply += " ¿Qué equipos quieres mantener prendidos cuando se va la luz?"
            else:
                reply = "¡Perfecto! Para tener respaldo en los apagones se evalúan la batería, el diseño y los equipos que quieres mantener prendidos. Las placas conectadas a la red, por sí solas, no garantizan respaldo. ¿Qué equipos quieres mantener prendidos cuando se va la luz?"
            profile["last_question"] = "loads"
            return reply, actions, sources
        elif decision.intent == "consumption":
            technical = self.knowledge.answer_technical(value)
            if technical:
                if technical["status"] == "verified":
                    return technical["text"], actions, technical["sources"]
                return technical["text"], ["human"], technical["sources"]
            reply = "No hace falta que sepas cuánta luz gastas exactamente. Una factura reciente ayuda al equipo a ver tu consumo, pero no la compartas por aquí. Si sabes más o menos cuánto pagas al mes, me lo dices; si no, lo omitimos."
            profile["last_question"] = "monthly_bill"
            return reply, actions, sources
        elif decision.intent == "company_information":
            answer = self.knowledge.answer(value)
            if answer and isinstance(answer.get("text"), str):
                reply, sources = answer["text"], answer.get("sources", [])
            else:
                gaps.append("no_knowledge")
                return "No tengo información vigente verificada para contestar eso sobre Power Solar. Se lo puedo pasar al equipo para que lo confirme; prefiero no inventar direcciones, ofertas ni condiciones.", ["human"], sources
        elif decision.intent == "greeting":
            reply = (f"¡Hola, {voice.greeting()}! Soy R.E.I.G.E.L., el asistente virtual de Power Solar. "
                     "¿Qué buscas solucionar: las alzas en la factura o las interrupciones del servicio?")
            return reply, actions, sources
        elif decision.intent == "contextual_follow_up":
            if "municipality" in (updated_facts or []):
                reply = (
                    f"¡Perfecto, {profile['municipality']}! Lo tomo en cuenta. "
                    "En la evaluación se ve qué opción le conviene a tu casa."
                )
                return reply + " " + self._next_question(profile), actions, sources
            if profile.get("last_question") == "loads":
                self._qualify(profile, value, decision)
                if profile.get("backup_loads"):
                    return "¡Gracias! Tomo esos equipos en cuenta. Cuánto respaldo tendrías depende del diseño y se determina en la evaluación técnica.", actions, sources
                return "No entendí bien qué equipos quieres mantener prendidos. ¿Me los mencionas o prefieres que se lo pase al equipo?", actions, sources
            if profile.get("last_question") == "bill_period":
                return "No quiero asumir de qué período es esa cantidad. ¿Es de un mes, de un año o prefieres omitirla?", actions, sources
            return "No te entendí bien. ¿Me lo dices de otra forma o seguimos sin ese dato?", actions, sources
        elif profile.get("bill_period") == "unknown":
            amount = profile.get("bill_amount")
            return f"Anoto ${amount:g}, sin asumir el período. ¿Corresponde a tu factura mensual?" if amount is not None else "¿Ese importe corresponde a tu factura mensual?", actions, sources
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
                reply = f"¡Perfecto, {profile['municipality']}! Lo tomo en cuenta. En la evaluación se ve qué opción le conviene a tu casa."
            elif "monthly_bill" in profile or "priority" in profile:
                reply = "¡Súper! Hay diferentes opciones para ayudarte con eso; primero revisamos los datos de tu hogar, sin prometer resultados."
            else:
                gaps.append("fallback")
                reply = "No te entendí bien. Te puedo orientar sobre la factura de luz, el respaldo en apagones o los sistemas solares, coordinar una evaluación o pasarte con alguien del equipo. ¿Qué prefieres?"
                return reply, actions, sources
        return reply + " " + self._next_question(profile), actions, sources

    def human(self, token):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, token)
            current = db.execute("SELECT mode FROM conversations WHERE id=?", (session["conversation_id"],)).fetchone()
            reply = ""
            if current["mode"] != "human":
                reply = "¡Listo! Tu solicitud de atención humana quedó registrada. Alguien del equipo te responderá por este mismo chat cuando esté disponible; no puedo prometer un tiempo de respuesta."
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
            reference = new_reference(db)
            db.execute("""INSERT INTO appointments(id,lead_id,advisor_id,start_at,end_at,status,source,created_at,reference)
                VALUES(?,?,?,?,?,?,?,?,?)""", (appointment_id, lead_id, advisor_id, begin, end, "confirmed", "web_chat", stamp(), reference))
            db.execute("UPDATE leads SET stage='cita',updated_at=? WHERE id=?", (stamp(), lead_id))
            db.execute("UPDATE conversations SET lead_id=?,advisor_id=?,contact_name=?,updated_at=? WHERE id=?", (lead_id, advisor_id, lead_data["name"], stamp(), session["conversation_id"]))
            db.execute("UPDATE web_chat_sessions SET appointment_id=? WHERE token_hash=?", (appointment_id, session["token_hash"]))
            self.store.audit(db, None, "appointment.book.web_chat", appointment_id)
            local = selected.astimezone(zone(advisor["timezone"]))
            reply = (f"Tu cita quedó confirmada en la agenda de Power Solar para el {spoken_datetime(local)} "
                     f"({zone_label(advisor['timezone'])}), con {advisor['name']}. "
                     f"Código de tu cita: {format_reference(reference)}. Guárdalo; si llamas o escribes al equipo, dales este código.")
            self._append(db, session["conversation_id"], "outbound", reply)
            session = self._session(db, token)
            result = self._view(db, session, reply, ["human"])
            self._save_request(db, session, request_id, "book", content_hash, result)
            return result


_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre")


def spoken_datetime(local):
    """'domingo 22 de noviembre a las 10:00 a. m.' — easier to read than 22/11/2026 10:00."""
    hour = local.hour % 12 or 12
    suffix = "a. m." if local.hour < 12 else "p. m."
    return (f"{_WEEKDAYS[local.weekday()]} {local.day} de {_MONTHS[local.month - 1]} "
            f"a las {hour}:{local.minute:02d} {suffix}")


def zone_label(name):
    return "hora de Puerto Rico" if name == "America/Puerto_Rico" else f"hora de {name}"
