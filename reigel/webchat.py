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

from .core import DomainError, stamp, text, uid, zone


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
    def __init__(self, store, knowledge):
        self.store = store
        self.knowledge = knowledge
        with store.connect() as db:
            db.executescript(SCHEMA)

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

    def message(self, token, message_text, request_id):
        incoming = text(message_text, "mensaje", limit=2000, required=True)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, token)
            request_id, content_hash, previous = self._request(db, session, request_id, "message", {"text": incoming})
            if previous is not None:
                # A retry must not resurrect an old appointment, mode or opt-out
                # snapshot after staff or the visitor changed the conversation.
                return self._view(db, session)
            incoming = self._safe_customer_text(incoming)
            self._append(db, session["conversation_id"], "inbound", incoming)
            conversation = db.execute("SELECT * FROM conversations WHERE id=?", (session["conversation_id"],)).fetchone()
            value = normalized(incoming)
            profile = json.loads(session["profile_json"])
            reply, actions, sources = "", [], []
            command = re.sub(r"[.!¡¿?]", "", value).strip()
            optout = command in {"stop", "/stop", "baja", "detener", "parar", "salir", "unsubscribe", "cancelar mensajes"} or bool(re.search(
                r"\b(darme de baja|darme la baja|dejen? de (?:escribir|contactar)|no me (?:contact\w*|escrib\w*|llam\w*)|"
                r"no (?:quiero|deseo) (?:recibir )?(?:mas )?mensajes|no mas mensajes|elimin[ae] (?:mis )?datos)\b", value))
            human = bool(re.search(r"\b(humano|humana|una persona|un representante|hablar con (?:un |una )?asesor|quiero (?:un |una )?asesor)\b", value))
            if value == "/start":
                # Only an explicit command received through this visitor's bearer
                # session reopens assistance. Staff mode changes never lift a stop.
                db.execute("UPDATE web_chat_sessions SET opted_out=0 WHERE token_hash=?", (session["token_hash"],))
                db.execute("UPDATE conversations SET mode='ai',updated_at=? WHERE id=?", (stamp(), session["conversation_id"]))
                reply = "Has reanudado la asistencia automática de R.E.I.G.E.L. en este chat. Puedes volver a detenerla escribiendo /stop o pedir atención humana. " + self._next_question(profile)
                actions = ["book", "human"]
            elif optout:
                db.execute("UPDATE web_chat_sessions SET opted_out=1 WHERE token_hash=?", (session["token_hash"],))
                db.execute("UPDATE conversations SET mode='human' WHERE id=?", (session["conversation_id"],))
                reply = "He detenido la asistencia comercial automática en este chat. No enviaré más respuestas de venta. Si necesitas ayuda, puedes solicitar atención humana."
                actions = ["human"]
            elif session["opted_out"]:
                # Opting out is persistent; a sales phrase cannot silently undo it.
                reply = ""
                actions = ["human"]
            elif human:
                db.execute("UPDATE conversations SET mode='human' WHERE id=?", (session["conversation_id"],))
                reply = "Tu solicitud de atención humana quedó registrada en esta conversación. El equipo podrá responder aquí cuando esté disponible; no puedo prometer un tiempo de respuesta."
            elif conversation["mode"] == "human":
                # The advisor owns the floor; store inbound without an automated sales reply.
                reply = ""
            else:
                self._qualify(profile, value)
                reply, actions, sources = self._answer(value, profile, session, db)
            db.execute("UPDATE web_chat_sessions SET profile_json=?,sources_json=? WHERE token_hash=?", (json.dumps(profile, ensure_ascii=False), json.dumps(sources, ensure_ascii=False), session["token_hash"]))
            if reply:
                self._append(db, session["conversation_id"], "outbound", reply)
            session = self._session(db, token)
            result = self._view(db, session, reply, actions)
            self._save_request(db, session, request_id, "message", content_hash, result)
            return result

    @staticmethod
    def _qualify(profile, value):
        if profile.get("last_question") == "monthly_bill" and re.search(r"\b(omitir|omito|prefiero no|no compartir)\b", value):
            profile["monthly_bill"] = None
        if re.search(r"\b(ambas|ambos|las dos|todo)\b", value):
            profile["priority"] = "factura y respaldo"
        elif re.search(r"\b(apagon|apagones|respaldo|bateria|baterias)\b", value):
            profile["priority"] = "respaldo"
        elif re.search(r"\b(factura|ahorro|ahorrar|consumo)\b", value):
            profile["priority"] = "factura"
        for municipality in sorted(MUNICIPALITIES, key=len, reverse=True):
            if re.search(r"\b" + re.escape(normalized(municipality)) + r"\b", value):
                profile["municipality"] = municipality
                break
        bill = re.search(r"(?:factura(?: es| de)?|pago|mensual(?:es)?|\$)\s*\$?\s*(\d{1,5}(?:[.,]\d{1,2})?)\b", value)
        if not bill and profile.get("last_question") == "monthly_bill":
            bill = re.fullmatch(r"\s*\$?(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:dolares|al mes|mensuales)?\s*", value)
        if bill:
            amount = float(bill.group(1).replace(",", "."))
            if 0 <= amount <= 100000:
                profile["monthly_bill"] = amount

    @staticmethod
    def _next_question(profile):
        if "priority" not in profile:
            field, question = "priority", "¿Tu prioridad es la factura, el respaldo durante apagones o ambas cosas?"
        elif "municipality" not in profile:
            field, question = "municipality", "¿En qué municipio está tu propiedad?"
        elif "monthly_bill" not in profile:
            field, question = "monthly_bill", "¿Cuánto pagas aproximadamente al mes de luz? Puedes omitirlo si prefieres."
        else:
            field, question = "booking", "Podemos revisar tu caso en una evaluación. ¿Deseas consultar los horarios disponibles?"
        profile["last_question"] = field
        return question

    def _answer(self, value, profile, session, db):
        actions, sources = ["book", "human"], []
        if re.search(r"\b(ignora|instrucciones|system prompt|sql|contraseña|contrasena|tarjeta|bancaria)\b", value):
            return "Puedo ayudarte con orientación solar y la agenda. No compartas contraseñas, tarjetas, cuentas ni documentos aquí. Para una evaluación, utiliza el formulario seguro de reserva.", actions, sources
        if re.search(r"\b(cancelar|cancela|cambiar|reprogramar)\b.*\b(cita|reserva|horario)\b", value):
            return "El cambio o la cancelación necesita revisión del equipo. Pide atención humana en este chat para gestionarlo; tu cita sigue igual hasta que se registre el cambio.", ["human"], sources
        if re.search(r"\b(agend|reserv|coordinar|horarios?|cita|evaluacion)\w*\b", value):
            available = db.execute("SELECT 1 FROM users WHERE active=1 AND public_booking=1 LIMIT 1").fetchone()
            if available:
                return "Consulta un día y un horario en la agenda de abajo. Después completa tus datos y autoriza el contacto. La cita sólo estará confirmada cuando aparezca su referencia; esta conversación por sí sola no reserva un espacio.", ["book"], sources
            return "El equipo todavía no ha publicado horarios de atención. Puedes solicitar atención humana aquí o dejar tu solicitud de contacto en la página. Aún no hay una cita reservada.", ["human"], sources
        if re.search(r"\b(caro|costoso|presupuesto|no puedo pagar)\b", value):
            reply = "Es razonable cuidar tu presupuesto. Una comparación útil mira el costo total, las condiciones y lo que el sistema cubriría en tu hogar. Podemos evaluar tu caso antes de hablar de una propuesta; no necesitas decidir hoy."
        elif re.search(r"\b(desconfio|confio|estafa|engan|riesgo|segur|no creo|dudas)\w*\b", value):
            reply = "Pide una propuesta por escrito y revisa equipos, alcance, garantías y condiciones antes de comprometerte. Tus preguntas merecen respuestas concretas. Podemos comenzar por la duda que más te preocupa y, si hace falta, pasarla a una persona del equipo."
        elif re.search(r"\b(pensarlo|no estoy listo|despues|luego|otro momento)\b", value):
            return "Tómate el tiempo que necesites. Si te ayuda a comparar opciones, podemos aclarar una duda concreta o consultar una evaluación cuando tú lo decidas. No hay una reserva ni una compra por conversar aquí.", actions, sources
        elif re.search(r"\b(precio|precios|oferta|promocion|descuento|financi|credito|incentivo|garantia|ahorro|ahorrar|gratis|costo|cuesta)\w*\b", value):
            reply = "No tengo una propuesta vigente y validada para tu hogar, así que no puedo prometer precios, aprobación, ahorros, incentivos ni condiciones de garantía. Lo útil es revisar tu consumo y tus prioridades para pedir una propuesta por escrito y comparar sus condiciones."
        elif re.search(r"\b(apagon|apagones|bateria|baterias|respaldo)\b", value):
            reply = "Si buscas respaldo durante apagones, hay que evaluar batería, diseño y las cargas que quieres mantener encendidas. Los paneles conectados a la red, por sí solos, no garantizan respaldo. ¿Qué equipos te importa mantener funcionando?"
            profile["last_question"] = "loads"
            return reply, actions, sources
        elif re.search(r"\b(ya tengo|tengo placas|tengo sistema|servicio tecnico|averia|reparacion)\b", value):
            return "Para un sistema existente o una avería, el equipo necesita revisar tu caso. Pide atención humana y describe el problema sin compartir números de cuenta ni documentos. Este chat no diagnostica fallas eléctricas ni confirma una visita técnica.", ["human"], sources
        else:
            answer = self.knowledge.answer(value)
            if answer and isinstance(answer.get("text"), str):
                reply, sources = answer["text"], answer.get("sources", [])
            elif re.search(r"\b(power solar|empresa|tiendas?|localiza|telefono|direccion|actualizada|actualizado)\b", value):
                return "No tengo información vigente verificada para responder esa pregunta sobre Power Solar. Puedo solicitar que el equipo la confirme; prefiero no darte direcciones, ofertas o condiciones sin comprobarlas.", ["human"], sources
            elif re.search(r"\b(hola|buenas|saludos|buenos dias|buenas tardes)\b", value):
                reply = "Hola. Soy R.E.I.G.E.L., asistente virtual de Power Solar. Vamos a empezar por lo que necesita tu hogar."
            elif profile.get("last_question") == "loads":
                reply = "Esas prioridades ayudarán al equipo a evaluar el respaldo. La capacidad y la autonomía necesitan una revisión técnica; no las puedo calcular sólo con este chat."
            elif "municipality" in profile and re.search(r"\b" + re.escape(normalized(profile["municipality"])) + r"\b", value):
                reply = f"Gracias. Tomo {profile['municipality']} como referencia para esta conversación. La viabilidad y la propuesta se determinan durante la evaluación."
            elif "monthly_bill" in profile or "priority" in profile:
                reply = "Con ese contexto podemos enfocar mejor la evaluación. El siguiente paso es revisar datos de tu hogar antes de prometer resultados."
            else:
                reply = "Mi función es orientarte sobre la evaluación solar y ayudarte con una cita. Podemos revisar tu factura, tu necesidad de respaldo o una duda sobre el proceso."
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
