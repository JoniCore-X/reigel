"""Persistent team productivity, additive migrations and scoped reporting.

No delivery workers or external providers are involved. Notifications are derived
from persisted records when requested and deduplicated in SQLite.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta


def _core():
    from . import core
    return core


def _error(message, status=422):
    raise _core().DomainError(message, status)


def timestamp(value, field, *, optional=True):
    if optional and value in (None, ""):
        return None
    if not isinstance(value, str):
        _error(f"{field} requiere una fecha con hora y zona horaria.")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(UTC).isoformat()
    except (ValueError, TypeError, OverflowError):
        _error(f"{field} requiere una fecha con hora y zona horaria.")


def number(value, field, maximum, *, optional=True):
    if optional and value in (None, ""):
        return None
    try:
        if isinstance(value, bool):
            raise ValueError()
        parsed = float(value)
        if not math.isfinite(parsed) or not 0 <= parsed <= maximum:
            raise ValueError()
        return parsed
    except (ValueError, TypeError, OverflowError):
        _error(f"{field} debe estar entre cero y {maximum}.")


def bounded_int(value, field, minimum, maximum):
    try:
        if isinstance(value, bool) or str(int(value)) != str(value):
            raise ValueError()
        result = int(value)
        if not minimum <= result <= maximum:
            raise ValueError()
        return result
    except (ValueError, TypeError, OverflowError):
        _error(f"{field} debe ser un entero entre {minimum} y {maximum}.")


def migrate_operations(db):
    """Apply versioned, additive DDL atomically, without rewriting old stages."""
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY,applied_at TEXT NOT NULL)")
    db.execute("BEGIN IMMEDIATE")
    if db.execute("SELECT 1 FROM schema_migrations WHERE version='team_caguas_operations_v1'").fetchone():
        return
    existing = {row["name"] for row in db.execute("PRAGMA table_info(leads)")}
    for name, definition in {
        "interest": "TEXT NOT NULL DEFAULT ''", "monthly_kwh": "REAL",
        "last_contact_at": "TEXT", "next_followup_at": "TEXT", "opportunity_value": "REAL",
    }.items():
        if name not in existing:
            db.execute(f"ALTER TABLE leads ADD COLUMN {name} {definition}")
    statements = (
        """CREATE TABLE IF NOT EXISTS lead_activities (
            id TEXT PRIMARY KEY,lead_id TEXT NOT NULL REFERENCES leads(id),actor_id TEXT REFERENCES users(id),
            type TEXT NOT NULL,description TEXT NOT NULL,outcome TEXT NOT NULL DEFAULT '',
            occurred_at TEXT NOT NULL,created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS lead_history (
            id TEXT PRIMARY KEY,lead_id TEXT NOT NULL REFERENCES leads(id),actor_id TEXT REFERENCES users(id),
            field TEXT NOT NULL,old_value TEXT,new_value TEXT,created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,lead_id TEXT REFERENCES leads(id),owner_id TEXT NOT NULL REFERENCES users(id),
            type TEXT NOT NULL,priority TEXT NOT NULL DEFAULT 'normal',due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',description TEXT NOT NULL,outcome TEXT NOT NULL DEFAULT '',
            completed_at TEXT,reminder_hours INTEGER NOT NULL DEFAULT 24,
            created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS internal_notifications (
            id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),event_key TEXT NOT NULL,
            type TEXT NOT NULL,title TEXT NOT NULL,entity_id TEXT NOT NULL,lead_id TEXT REFERENCES leads(id),
            read_at TEXT,created_at TEXT NOT NULL,UNIQUE(user_id,event_key))""",
        """CREATE TABLE IF NOT EXISTS appointment_reminders (
            appointment_id TEXT PRIMARY KEY REFERENCES appointments(id),hours INTEGER NOT NULL DEFAULT 24)""",
        "CREATE INDEX IF NOT EXISTS lead_activities_timeline ON lead_activities(lead_id,occurred_at DESC)",
        "CREATE INDEX IF NOT EXISTS lead_history_timeline ON lead_history(lead_id,created_at DESC)",
        "CREATE INDEX IF NOT EXISTS tasks_owner_due ON tasks(owner_id,status,due_at)",
        "CREATE INDEX IF NOT EXISTS tasks_lead ON tasks(lead_id)",
        "CREATE INDEX IF NOT EXISTS notification_user_time ON internal_notifications(user_id,created_at DESC)",
        "CREATE INDEX IF NOT EXISTS leads_followup ON leads(advisor_id,next_followup_at)",
    )
    for statement in statements:
        db.execute(statement)
    db.execute("INSERT INTO schema_migrations VALUES(?,?)", ("team_caguas_operations_v1", _core().stamp()))


TASK_TYPES = ("call", "send_info", "confirm_appointment", "prepare_orientation", "follow_up", "review_proposal", "referral", "documents")
TASK_PRIORITIES = ("low", "normal", "high")
TASK_STATES = ("pending", "completed", "cancelled")


class OperationsMixin:
    def query_leads(self, actor, *, q="", stage="", advisor_id="", sort="created_at", order="desc", limit=100, offset=0):
        core = _core()
        query = core.text(q, "búsqueda", limit=150)
        stage = core.text(stage, "etapa", limit=60)
        advisor_id = core.text(advisor_id, "asesor", limit=100)
        if stage and stage not in core.STAGES:
            _error("Etapa no válida.")
        if sort not in {"created_at", "name", "next_followup_at", "updated_at"} or order not in {"asc", "desc"}:
            _error("Orden no válido.")
        limit = bounded_int(limit, "Límite", 1, 500)
        offset = bounded_int(offset, "Desplazamiento", 0, 1000000)
        clause, args = self._scope(actor, "l")
        values = list(args)
        if query:
            clause += (" AND (l.name LIKE ? ESCAPE '\\' OR l.email LIKE ? ESCAPE '\\' OR l.phone LIKE ? ESCAPE '\\' OR l.municipality LIKE ? ESCAPE '\\'"
                       " OR EXISTS (SELECT 1 FROM appointments ar WHERE ar.lead_id=l.id AND ar.reference=?))")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values.extend(["%" + escaped + "%"] * 4)
            values.append(core.normalize_reference(query) or "-")
        if stage:
            clause += " AND l.stage=?"
            values.append(stage)
        if advisor_id:
            if actor["role"] != "admin" and advisor_id != actor["id"]:
                _error("No tienes acceso a los prospectos de otro asesor.", 403)
            clause += " AND l.advisor_id=?"
            values.append(advisor_id)
        with self.connect() as db:
            total = db.execute(f"SELECT count(*) FROM leads l WHERE {clause}", values).fetchone()[0]
            rows = db.execute(f"""SELECT l.*,u.name advisor_name FROM leads l LEFT JOIN users u ON u.id=l.advisor_id
                WHERE {clause} ORDER BY l.{sort} IS NULL,l.{sort} {order},l.id {order} LIMIT ? OFFSET ?""", (*values, limit, offset))
            leads = [{**dict(row), "consent": bool(row["consent"])} for row in rows]
        return {"leads": leads, "total": total, "limit": limit, "offset": offset}

    def _lead_metadata(self, data):
        core = _core()
        values = {}
        if "interest" in data:
            values["interest"] = core.text(data["interest"], "interés", limit=500)
        for key, maximum, label in (("monthly_kwh", 1000000, "Consumo mensual"), ("opportunity_value", 100000000, "Valor de oportunidad")):
            if key in data:
                values[key] = number(data[key], label, maximum)
        for key, label in (("last_contact_at", "Último contacto"), ("next_followup_at", "Próximo seguimiento")):
            if key in data:
                values[key] = timestamp(data[key], label)
        if values.get("last_contact_at") and values["last_contact_at"] > core.stamp():
            _error("El último contacto no puede estar en el futuro.")
        return values

    def offboard_user(self, user_id, data, actor):
        """Cut access and hand every open responsibility to one active colleague, atomically.

        Future confirmed appointments, assigned leads, pending tasks and linked
        conversations move to the receiving account; sessions are deleted in the
        same transaction, so a departing person loses access immediately.
        """
        core = _core()
        self.require_admin(actor)
        if not isinstance(data, dict) or set(data) - {"target_id"}:
            _error("Indica quién recibe los prospectos de esta cuenta.")
        target_id = core.text(data.get("target_id"), "cuenta que recibe", limit=100, required=True)
        if user_id == actor["id"]:
            _error("No puedes dar de baja tu propia cuenta.", 409)
        if target_id == user_id:
            _error("Elige otra cuenta para recibir los prospectos.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            leaving = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not leaving:
                _error("Cuenta no encontrada.", 404)
            if leaving["is_owner"]:
                _error("La cuenta del propietario no se puede dar de baja.", 409)
            if leaving["role"] == "admin" and not actor.get("is_owner"):
                _error("Solo el propietario puede dar de baja a un administrador.", 403)
            if not leaving["active"]:
                _error("Esta cuenta ya está desactivada.", 409)
            if not db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (target_id,)).fetchone():
                _error("La cuenta que recibe debe estar activa.")
            now = core.stamp()
            appointments = db.execute(
                "SELECT start_at,end_at FROM appointments WHERE advisor_id=? AND status='confirmed' AND end_at>?",
                (user_id, now)).fetchall()
            clashes = sum(1 for row in appointments if db.execute(
                "SELECT 1 FROM appointments WHERE advisor_id=? AND status='confirmed' AND start_at<? AND end_at>?",
                (target_id, row["end_at"], row["start_at"])).fetchone())
            if clashes:
                _error(f"{clashes} cita(s) pendiente(s) chocan con la agenda de quien recibe. "
                       "Reprográmalas o elige a otra persona.", 409)
            leads = [row["id"] for row in db.execute("SELECT id FROM leads WHERE advisor_id=?", (user_id,))]
            db.execute("UPDATE appointments SET advisor_id=? WHERE advisor_id=? AND status='confirmed' AND end_at>?",
                       (target_id, user_id, now))
            db.execute("""UPDATE conversations SET advisor_id=?,mode='human',updated_at=?
                WHERE advisor_id=? OR lead_id IN (SELECT id FROM leads WHERE advisor_id=?)""",
                       (target_id, now, user_id, user_id))
            tasks = db.execute("UPDATE tasks SET owner_id=?,updated_at=? WHERE owner_id=? AND status='pending'",
                               (target_id, now, user_id)).rowcount
            tasks += db.execute("""UPDATE tasks SET owner_id=?,updated_at=? WHERE status='pending' AND owner_id<>?
                AND lead_id IN (SELECT id FROM leads WHERE advisor_id=?)""", (target_id, now, target_id, user_id)).rowcount
            db.execute("UPDATE leads SET advisor_id=?,updated_at=? WHERE advisor_id=?", (target_id, now, user_id))
            for lead_id in leads:
                db.execute("INSERT INTO lead_history VALUES(?,?,?,?,?,?,?)",
                           (core.uid(), lead_id, actor["id"], "advisor_id", user_id, target_id, now))
            db.execute("UPDATE users SET active=0,public_booking=0 WHERE id=?", (user_id,))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self.audit(db, actor, "user.offboard", user_id)
            # /chat only offers schedules of active accounts with public booking enabled.
            booking = db.execute("SELECT count(*) FROM users WHERE active=1 AND public_booking=1").fetchone()[0]
            return {"user": core.user_dict(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()),
                    "moved": {"leads": len(leads), "appointments": len(appointments), "tasks": tasks},
                    "public_booking_accounts": booking}

    def _transfer_lead(self, db, lead, selected, actor):
        """Every ownership-changing path shares the same calendar/task boundary."""
        core = _core()
        if selected == lead["advisor_id"]:
            return
        conflict = db.execute("SELECT 1 FROM appointments WHERE lead_id=? AND status='confirmed' AND end_at>? AND advisor_id IS NOT ?", (lead["id"], core.stamp(), selected)).fetchone()
        if conflict:
            _error("Cancela o completa la cita pendiente antes de reasignar el prospecto.", 409)
        db.execute("UPDATE tasks SET owner_id=?,updated_at=? WHERE lead_id=? AND status='pending'", (selected or actor["id"], core.stamp(), lead["id"]))
        db.execute("UPDATE conversations SET advisor_id=?,mode='human',updated_at=? WHERE lead_id=?", (selected, core.stamp(), lead["id"]))

    def edit_lead(self, lead_id, data, actor):
        core = _core()
        allowed = {"name", "email", "phone", "municipality", "monthly_bill", "source", "stage", "advisor_id", "notes", "consent", "interest", "monthly_kwh", "last_contact_at", "next_followup_at", "opportunity_value"}
        if not isinstance(data, dict) or not data or set(data) - allowed:
            _error("Campos del contacto no válidos.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = self._lead(db, lead_id, actor)
            values = self._lead_metadata(data)
            contact_fields = {"name", "email", "phone", "municipality", "monthly_bill", "source"}
            if contact_fields.intersection(data):
                normalized = self.normalize_lead({**previous, **data})
                values.update({key: normalized[key] for key in contact_fields if key in data})
            if "stage" in data:
                if not isinstance(data["stage"], str) or data["stage"] not in core.STAGES:
                    _error("Etapa no válida.")
                values["stage"] = data["stage"]
            if "notes" in data:
                values["notes"] = core.text(data["notes"], "notas", limit=5000)
            if "consent" in data:
                if type(data["consent"]) is not bool:
                    _error("Consentimiento no válido.")
                values["consent"] = int(data["consent"])
                if not data["consent"]:
                    db.execute("UPDATE conversations SET mode='human' WHERE lead_id=?", (lead_id,))
            if "advisor_id" in data:
                self.require_admin(actor)
                selected = core.text(data["advisor_id"], "asesor", limit=100) or None
                if selected and not db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (selected,)).fetchone():
                    _error("Asesor no disponible.")
                self._transfer_lead(db, previous, selected, actor)
                values["advisor_id"] = selected
            changed = {key: value for key, value in values.items() if value != previous.get(key)}
            for key, value in changed.items():
                db.execute(f"UPDATE leads SET {key}=? WHERE id=?", (value, lead_id))
                db.execute("INSERT INTO lead_history VALUES(?,?,?,?,?,?,?)", (core.uid(), lead_id, actor["id"], key, None if previous.get(key) is None else str(previous[key]), None if value is None else str(value), core.stamp()))
            db.execute("UPDATE leads SET updated_at=? WHERE id=?", (core.stamp(), lead_id))
            self.audit(db, actor, "lead.update", lead_id)
            return self._lead(db, lead_id, actor)

    def lead_detail(self, lead_id, actor):
        core = _core()
        with self.connect() as db:
            lead = self._lead(db, lead_id, actor)
            activities = [dict(row) for row in db.execute("""SELECT a.*,u.name actor_name FROM lead_activities a LEFT JOIN users u ON u.id=a.actor_id
                WHERE a.lead_id=? ORDER BY a.occurred_at DESC,a.id DESC LIMIT 200""", (lead_id,))]
            history = [dict(row) for row in db.execute("""SELECT h.*,u.name actor_name FROM lead_history h LEFT JOIN users u ON u.id=h.actor_id
                WHERE h.lead_id=? ORDER BY h.created_at DESC,h.id DESC LIMIT 200""", (lead_id,))]
            clause, args = self._scope(actor, "l")
            duplicates = [dict(row) for row in db.execute(f"""SELECT l.id,l.name,l.stage FROM leads l WHERE {clause} AND l.id<>?
                AND ((?<>'' AND l.email=? COLLATE NOCASE) OR (?<>'' AND l.phone=?)) LIMIT 20""", (*args, lead_id, lead["email"], lead["email"], lead["phone"], lead["phone"]))]
        return {"lead": lead, "appointments": self.list_appointments(actor, lead_id), "activities": activities,
                "history": history, "tasks": self.query_tasks(actor, lead_id=lead_id)["tasks"], "duplicates": duplicates}

    def create_activity(self, lead_id, data, actor):
        core = _core()
        if not isinstance(data, dict) or set(data) - {"type", "description", "outcome", "occurred_at"}:
            _error("Datos de actividad no válidos.")
        kind = data.get("type", "note")
        if not isinstance(kind, str) or kind not in {"call", "message", "meeting", "note"}:
            _error("Tipo de actividad no válido.")
        description = core.text(data.get("description"), "descripción", limit=3000, required=True)
        outcome = core.text(data.get("outcome"), "resultado", limit=1500)
        occurred_at = timestamp(data.get("occurred_at") or core.stamp(), "Actividad", optional=False)
        if occurred_at > core.stamp():
            _error("Una actividad realizada no puede tener fecha futura; crea una tarea.")
        activity_id = core.uid()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lead = self._lead(db, lead_id, actor)
            db.execute("INSERT INTO lead_activities VALUES(?,?,?,?,?,?,?,?)", (activity_id, lead_id, actor["id"], kind, description, outcome, occurred_at, core.stamp()))
            if kind != "note" and (not lead["last_contact_at"] or occurred_at > lead["last_contact_at"]):
                db.execute("UPDATE leads SET last_contact_at=?,updated_at=? WHERE id=?", (occurred_at, core.stamp(), lead_id))
            self.audit(db, actor, "activity.record", activity_id)
            return dict(db.execute("SELECT * FROM lead_activities WHERE id=?", (activity_id,)).fetchone())

    def _task_scope(self, actor, prefix="t"):
        if actor["role"] == "admin":
            return "1=1", ()
        return f"{prefix}.owner_id=? AND ({prefix}.lead_id IS NULL OR l.advisor_id=?)", (actor["id"], actor["id"])

    def _task(self, db, task_id, actor):
        clause, args = self._task_scope(actor)
        row = db.execute(f"""SELECT t.*,l.name lead_name,u.name owner_name FROM tasks t LEFT JOIN leads l ON l.id=t.lead_id
            JOIN users u ON u.id=t.owner_id WHERE t.id=? AND {clause}""", (task_id, *args)).fetchone()
        if not row:
            _error("Tarea no encontrada.", 404)
        return {**dict(row), "overdue": row["status"] == "pending" and row["due_at"] < _core().stamp()}

    def query_tasks(self, actor, *, status="", lead_id="", owner_id="", limit=100, offset=0):
        core = _core()
        if status not in ("", "overdue", *TASK_STATES):
            _error("Estado de tarea no válido.")
        limit = bounded_int(limit, "Límite", 1, 500)
        offset = bounded_int(offset, "Desplazamiento", 0, 1000000)
        clause, args = self._task_scope(actor)
        values = list(args)
        if lead_id:
            self.get_lead(lead_id, actor)
            clause += " AND t.lead_id=?"
            values.append(core.text(lead_id, "prospecto", limit=100))
        if owner_id:
            if actor["role"] != "admin" and owner_id != actor["id"]:
                _error("No puedes consultar tareas de otro asesor.", 403)
            clause += " AND t.owner_id=?"
            values.append(core.text(owner_id, "responsable", limit=100))
        if status == "overdue":
            clause += " AND t.status='pending' AND t.due_at<?"
            values.append(core.stamp())
        elif status:
            clause += " AND t.status=?"
            values.append(status)
        base = f"FROM tasks t LEFT JOIN leads l ON l.id=t.lead_id JOIN users u ON u.id=t.owner_id WHERE {clause}"
        with self.connect() as db:
            total = db.execute(f"SELECT count(*) {base}", values).fetchone()[0]
            rows = db.execute(f"SELECT t.*,l.name lead_name,u.name owner_name {base} ORDER BY CASE t.status WHEN 'pending' THEN 0 ELSE 1 END,t.due_at,t.id LIMIT ? OFFSET ?", (*values, limit, offset))
            tasks = [{**dict(row), "overdue": row["status"] == "pending" and row["due_at"] < core.stamp()} for row in rows]
        return {"tasks": tasks, "total": total, "limit": limit, "offset": offset}

    def save_task(self, data, actor, task_id=None):
        core = _core()
        allowed = {"lead_id", "owner_id", "type", "priority", "due_at", "status", "description", "outcome", "reminder_hours"}
        if not isinstance(data, dict) or not data or set(data) - allowed:
            _error("Campos de tarea no válidos.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = self._task(db, task_id, actor) if task_id else {"lead_id": None, "owner_id": actor["id"], "type": "follow_up", "priority": "normal", "status": "pending", "description": "", "outcome": "", "reminder_hours": 24, "due_at": None, "completed_at": None}
            merged = {**previous, **data}
            lead_id = core.text(merged["lead_id"], "prospecto", limit=100) or None
            owner_id = core.text(merged["owner_id"], "responsable", limit=100, required=True)
            if actor["role"] != "admin" and owner_id != actor["id"]:
                _error("No puedes asignar tareas a otro asesor.", 403)
            if not db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (owner_id,)).fetchone():
                _error("Responsable no disponible.")
            if lead_id:
                lead = self._lead(db, lead_id, actor)
                if lead["advisor_id"] and lead["advisor_id"] != owner_id:
                    _error("El responsable debe ser el asesor asignado al prospecto.")
                if not lead["advisor_id"] and owner_id != actor["id"]:
                    _error("Asigna primero el prospecto al responsable de la tarea.")
                if not lead["advisor_id"] and actor["role"] != "admin":
                    _error("Prospecto no encontrado.", 404)
            for key, choices in (("type", TASK_TYPES), ("priority", TASK_PRIORITIES), ("status", TASK_STATES)):
                if not isinstance(merged[key], str) or merged[key] not in choices:
                    _error(f"Revisa {key} de la tarea.")
            due_at = timestamp(merged["due_at"], "Vencimiento", optional=False)
            description = core.text(merged["description"], "descripción", limit=3000, required=True)
            outcome = core.text(merged["outcome"], "resultado", limit=1500)
            reminder = bounded_int(merged["reminder_hours"], "Recordatorio", 0, 720)
            completed = (previous.get("completed_at") or core.stamp()) if merged["status"] == "completed" else None
            if not task_id:
                task_id = core.uid()
                db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (task_id, lead_id, owner_id, merged["type"], merged["priority"], due_at, merged["status"], description, outcome, completed, reminder, core.stamp(), core.stamp()))
            else:
                db.execute("""UPDATE tasks SET lead_id=?,owner_id=?,type=?,priority=?,due_at=?,status=?,description=?,outcome=?,completed_at=?,reminder_hours=?,updated_at=? WHERE id=?""", (lead_id, owner_id, merged["type"], merged["priority"], due_at, merged["status"], description, outcome, completed, reminder, core.stamp(), task_id))
            self.audit(db, actor, "task.save", task_id)
            return self._task(db, task_id, actor)

    def update_appointment(self, appointment_id, data, actor):
        core = _core()
        if not isinstance(data, dict) or not data or set(data) - {"status", "reminder_hours"}:
            _error("Campos de cita no válidos.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            appointment = self._appointment(db, appointment_id, actor)
            if "status" in data:
                status = data["status"]
                if not isinstance(status, str) or status not in {"cancelled", "completed", "no_show"}:
                    _error("Estado de cita no válido.")
                if appointment["status"] != "confirmed" and appointment["status"] != status:
                    _error("La cita ya tiene un resultado registrado.", 409)
                if status in {"completed", "no_show"} and appointment["end_at"] > core.stamp():
                    _error("La cita todavía no ha terminado.", 409)
                if appointment["status"] != status:
                    db.execute("UPDATE appointments SET status=? WHERE id=?", (status, appointment_id))
                    if status == "completed":
                        lead = self._lead(db, appointment["lead_id"], actor)
                        if lead["stage"] == "cita":
                            db.execute("UPDATE leads SET stage='cita_realizada',updated_at=? WHERE id=?", (core.stamp(), lead["id"]))
                            db.execute("INSERT INTO lead_history VALUES(?,?,?,?,?,?,?)", (core.uid(), lead["id"], actor["id"], "stage", "cita", "cita_realizada", core.stamp()))
                    self.audit(db, actor, "appointment.cancel" if status == "cancelled" else "appointment." + status, appointment_id)
            if "reminder_hours" in data:
                hours = bounded_int(data["reminder_hours"], "Recordatorio", 0, 720)
                db.execute("INSERT INTO appointment_reminders VALUES(?,?) ON CONFLICT(appointment_id) DO UPDATE SET hours=excluded.hours", (appointment_id, hours))
                self.audit(db, actor, "appointment.reminder", appointment_id)
            result = self._appointment(db, appointment_id, actor)
            row = db.execute("SELECT hours FROM appointment_reminders WHERE appointment_id=?", (appointment_id,)).fetchone()
            result["reminder_hours"] = row[0] if row else 24
            return result

    def _notification(self, db, actor, key, kind, title, entity_id, lead_id=None):
        core = _core()
        # Refresh the live relationship without resetting acknowledgement or age.
        db.execute("""INSERT INTO internal_notifications(id,user_id,event_key,type,title,entity_id,lead_id,created_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,event_key) DO UPDATE SET type=excluded.type,title=excluded.title,entity_id=excluded.entity_id,lead_id=excluded.lead_id""", (core.uid(), actor["id"], key, kind, title, entity_id, lead_id, core.stamp()))

    def list_notifications(self, actor, *, limit=100, offset=0):
        core = _core()
        limit = bounded_int(limit, "Límite", 1, 500)
        offset = bounded_int(offset, "Desplazamiento", 0, 1000000)
        clause, args = self._scope(actor, "l")
        task_clause, task_args = self._task_scope(actor)
        appointment_clause, appointment_args = self._scope(actor, "a")
        current = core.now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute(f"SELECT l.* FROM leads l WHERE {clause} AND l.advisor_id IS NOT NULL", args):
                self._notification(db, actor, f"lead:{row['id']}:{row['advisor_id']}", "lead_assigned", "Prospecto asignado", row["id"], row["id"])
                if row["next_followup_at"] and row["next_followup_at"] <= current.isoformat() and row["stage"] not in {"ganado", "perdido"}:
                    self._notification(db, actor, f"followup:{row['id']}:{row['next_followup_at']}", "followup_overdue", "Seguimiento vencido", row["id"], row["id"])
            rows = db.execute(f"SELECT t.* FROM tasks t LEFT JOIN leads l ON l.id=t.lead_id WHERE {task_clause} AND t.status='pending'", task_args).fetchall()
            for row in rows:
                if datetime.fromisoformat(row["due_at"]) - timedelta(hours=row["reminder_hours"]) <= current:
                    overdue = row["due_at"] < current.isoformat()
                    kind = "task_overdue" if overdue else "task_reminder"
                    self._notification(db, actor, f"task:{row['id']}:{row['due_at']}", kind, "Tarea vencida" if overdue else "Tarea próxima", row["id"], row["lead_id"])
            rows = db.execute(f"""SELECT a.*,coalesce(r.hours,24) reminder_hours FROM appointments a JOIN leads l ON l.id=a.lead_id
                LEFT JOIN appointment_reminders r ON r.appointment_id=a.id WHERE {appointment_clause} AND a.status='confirmed' AND a.end_at>?""", (*appointment_args, current.isoformat())).fetchall()
            for row in rows:
                if actor["role"] != "admin":
                    self._lead(db, row["lead_id"], actor)
                if datetime.fromisoformat(row["start_at"]) - timedelta(hours=row["reminder_hours"]) <= current:
                    self._notification(db, actor, f"appointment:{row['id']}:{row['start_at']}", "appointment_reminder", "Cita próxima", row["id"], row["lead_id"])
            conversation_clause, conversation_args = self._scope(actor, "c")
            for row in db.execute(f"SELECT c.* FROM conversations c WHERE {conversation_clause} AND c.mode='human'", conversation_args):
                self._notification(db, actor, f"human:{row['id']}", "human_attention", "Conversación en atención humana", row["id"], row["lead_id"])
            visible, visible_args = self._notification_scope(actor)
            total = db.execute(f"SELECT count(*) FROM internal_notifications n WHERE {visible}", visible_args).fetchone()[0]
            unread = db.execute(f"SELECT count(*) FROM internal_notifications n WHERE {visible} AND n.read_at IS NULL", visible_args).fetchone()[0]
            rows = db.execute(f"SELECT n.* FROM internal_notifications n WHERE {visible} ORDER BY n.created_at DESC,n.id DESC LIMIT ? OFFSET ?", (*visible_args, limit, offset))
            notifications = [{**dict(row), "read": bool(row["read_at"])} for row in rows]
        return {"notifications": notifications, "unread": unread, "total": total, "limit": limit, "offset": offset}

    def _notification_scope(self, actor):
        # Re-check live ownership and state: transferring a lead cannot leave an old
        # advisor with a notification that reveals another advisor's work.
        lead_clause, lead_args = self._scope(actor, "l")
        task_clause, task_args = self._task_scope(actor)
        conv_clause, conv_args = self._scope(actor, "c")
        app_clause, app_args = self._scope(actor, "a")
        clause = f"""n.user_id=? AND (n.lead_id IS NULL OR EXISTS(SELECT 1 FROM leads l WHERE l.id=n.lead_id AND {lead_clause}))
            AND (n.type NOT IN ('task_reminder','task_overdue') OR EXISTS(SELECT 1 FROM tasks t LEFT JOIN leads l ON l.id=t.lead_id WHERE t.id=n.entity_id AND t.status='pending' AND n.lead_id IS t.lead_id AND n.event_key='task:'||t.id||':'||t.due_at AND {task_clause}))
            AND (n.type<>'appointment_reminder' OR EXISTS(SELECT 1 FROM appointments a WHERE a.id=n.entity_id AND a.status='confirmed' AND a.end_at>? AND {app_clause}))
            AND (n.type<>'human_attention' OR EXISTS(SELECT 1 FROM conversations c WHERE c.id=n.entity_id AND c.mode='human' AND {conv_clause}))
            AND (n.type<>'followup_overdue' OR EXISTS(SELECT 1 FROM leads l WHERE l.id=n.entity_id AND l.next_followup_at IS NOT NULL AND l.next_followup_at<=? AND n.event_key='followup:'||l.id||':'||l.next_followup_at AND l.stage NOT IN ('ganado','perdido')))"""
        return clause, (actor["id"], *lead_args, *task_args, _core().stamp(), *app_args, *conv_args, _core().stamp())

    def mark_notification(self, notification_id, data, actor):
        core = _core()
        if not isinstance(data, dict) or set(data) != {"read"} or type(data["read"]) is not bool:
            _error("Indica si la notificación está leída.")
        clause, args = self._notification_scope(actor)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(f"SELECT 1 FROM internal_notifications n WHERE n.id=? AND {clause}", (notification_id, *args)).fetchone():
                _error("Notificación no encontrada.", 404)
            db.execute("UPDATE internal_notifications SET read_at=? WHERE id=?", (core.stamp() if data["read"] else None, notification_id))
            self.audit(db, actor, "notification.read", notification_id)
            row = db.execute("SELECT * FROM internal_notifications WHERE id=?", (notification_id,)).fetchone()
            return {**dict(row), "read": bool(row["read_at"])}

    def operations_dashboard(self, actor, *, period="all", start="", end=""):
        core = _core()
        tz = core.zone(self.settings()["timezone"])
        today = core.now().astimezone(tz).date()
        if period not in {"all", "today", "week", "month", "custom"}:
            _error("Periodo no válido.")
        if bool(start) != bool(end):
            _error("Indica las dos fechas del periodo.")
        if start and end:
            try:
                begin_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
                if begin_day > end_day or (end_day - begin_day).days > 3660:
                    raise ValueError()
            except (ValueError, TypeError):
                _error("Revisa el intervalo de fechas (máximo diez años).")
            period = "custom"
        elif period == "custom":
            _error("El periodo personalizado necesita ambas fechas.")
        else:
            begin_day = today if period == "today" else today - timedelta(days=today.weekday()) if period == "week" else today.replace(day=1)
            end_day = today
        begin = datetime.combine(begin_day, time.min, tz).astimezone(UTC).isoformat() if period != "all" else None
        finish = datetime.combine(end_day + timedelta(days=1), time.min, tz).astimezone(UTC).isoformat() if period != "all" else None
        lead_clause, lead_args = self._scope(actor, "l")
        lead_values = list(lead_args)
        if begin:
            lead_clause += " AND l.created_at>=? AND l.created_at<?"
            lead_values.extend([begin, finish])
        app_clause, app_args = self._scope(actor, "a")
        app_values = list(app_args)
        if actor["role"] != "admin":
            app_clause += " AND l.advisor_id=?"
            app_values.append(actor["id"])
        if begin:
            app_clause += " AND a.start_at>=? AND a.start_at<?"
            app_values.extend([begin, finish])
        task_clause, task_args = self._task_scope(actor)
        with self.connect() as db:
            counts = {row["stage"]: row["n"] for row in db.execute(f"SELECT l.stage,count(*) n FROM leads l WHERE {lead_clause} GROUP BY l.stage", lead_values)}
            lead_count = sum(counts.values())
            app_counts = {row["status"]: row["n"] for row in db.execute(f"SELECT a.status,count(*) n FROM appointments a JOIN leads l ON l.id=a.lead_id WHERE {app_clause} GROUP BY a.status", app_values)}
            upcoming = db.execute(f"SELECT count(*) FROM appointments a JOIN leads l ON l.id=a.lead_id WHERE {app_clause} AND a.status='confirmed' AND a.end_at>?", (*app_values, core.stamp())).fetchone()[0]
            conv_scope, conv_args = self._scope(actor, "c")
            conversations = db.execute(f"SELECT count(*) FROM conversations c WHERE {conv_scope}", conv_args).fetchone()[0]
            overdue = db.execute(f"SELECT count(*) FROM tasks t LEFT JOIN leads l ON l.id=t.lead_id WHERE {task_clause} AND t.status='pending' AND t.due_at<?", (*task_args, core.stamp())).fetchone()[0]
            value = db.execute(f"SELECT sum(l.opportunity_value) FROM leads l WHERE {lead_clause} AND l.stage NOT IN ('ganado','perdido')", lead_values).fetchone()[0]
            recent = [{**dict(row), "consent": bool(row["consent"])} for row in db.execute(f"SELECT l.*,u.name advisor_name FROM leads l LEFT JOIN users u ON u.id=l.advisor_id WHERE {lead_clause} ORDER BY l.created_at DESC LIMIT 5", lead_values)]
            appointments = [dict(row) for row in db.execute(f"SELECT a.*,l.name lead_name,u.name advisor_name FROM appointments a JOIN leads l ON l.id=a.lead_id JOIN users u ON u.id=a.advisor_id WHERE {app_clause} AND a.status='confirmed' AND a.end_at>? ORDER BY a.start_at LIMIT 5", (*app_values, core.stamp()))]
            contact_scope, contact_args = self._scope(actor, "l")
            contacts_sql = f"{contact_scope} AND l.last_contact_at IS NOT NULL"
            contacts_values = list(contact_args)
            if begin:
                contacts_sql += " AND l.last_contact_at>=? AND l.last_contact_at<?"
                contacts_values.extend([begin, finish])
            contacts = db.execute(f"SELECT count(*) FROM leads l WHERE {contacts_sql}", contacts_values).fetchone()[0]
            followup_count = db.execute(f"SELECT count(*) FROM leads l WHERE {contact_scope} AND l.next_followup_at<=? AND l.stage NOT IN ('ganado','perdido')", (*contact_args, core.stamp())).fetchone()[0]
            followups = [dict(row) for row in db.execute(f"SELECT l.id,l.name,l.next_followup_at FROM leads l WHERE {contact_scope} AND l.next_followup_at<=? AND l.stage NOT IN ('ganado','perdido') ORDER BY l.next_followup_at LIMIT 10", (*contact_args, core.stamp()))]
            missing = [dict(row) for row in db.execute(f"SELECT l.id,l.name FROM leads l WHERE {contact_scope} AND l.stage IN ('nuevo','contacto_pendiente') ORDER BY l.created_at LIMIT 5", contact_args)]
            activity_scope = contact_scope
            activity_values = list(contact_args)
            if begin:
                activity_scope += " AND x.occurred_at>=? AND x.occurred_at<?"
                activity_values.extend([begin, finish])
            activity = [dict(row) for row in db.execute(f"SELECT x.type,count(*) count FROM lead_activities x JOIN leads l ON l.id=x.lead_id WHERE {activity_scope} GROUP BY x.type", activity_values)]
        tasks = self.query_tasks(actor, status="pending", limit=10)["tasks"]
        priorities = [{"type": "task", "title": task["description"], "lead_id": task["lead_id"], "task_id": task["id"], "due_at": task["due_at"], "overdue": task["overdue"]} for task in tasks if task["due_at"] <= datetime.combine(today + timedelta(days=1), time.min, tz).astimezone(UTC).isoformat()]
        priorities += [{"type": "followup", "title": "Dar seguimiento a " + lead["name"], "lead_id": lead["id"], "due_at": lead["next_followup_at"], "overdue": True} for lead in followups]
        priorities += [{"type": "contact", "title": "Contactar a " + lead["name"], "lead_id": lead["id"]} for lead in missing]
        priorities += [{"type": "appointment", "title": "Revisar cita con " + appointment["lead_name"], "lead_id": appointment["lead_id"], "appointment_id": appointment["id"], "due_at": appointment["start_at"]} for appointment in appointments if appointment["start_at"] < datetime.combine(today + timedelta(days=1), time.min, tz).astimezone(UTC).isoformat()]
        return {"metrics": {"leads": lead_count, "appointments": upcoming, "conversations": conversations,
                    "conversion_rate": round(counts.get("ganado", 0) * 100 / lead_count, 1) if lead_count else 0,
                    "pending_leads": counts.get("nuevo", 0) + counts.get("contacto_pendiente", 0), "contacts": contacts,
                    "appointments_completed": app_counts.get("completed", 0), "appointments_scheduled": sum(app_counts.values()),
                    "overdue_tasks": overdue, "overdue_followups": followup_count, "open_opportunities": sum(n for stage, n in counts.items() if stage not in {"ganado", "perdido"}),
                    "sales": counts.get("ganado", 0), "opportunity_value": value},
                "stages": [{"stage": stage, "count": counts.get(stage, 0)} for stage in core.STAGES],
                "recent_leads": recent, "upcoming_appointments": appointments, "priorities": priorities[:20], "activity": activity,
                "period": {"name": period, "start": begin_day.isoformat() if begin else None, "end": end_day.isoformat() if begin else None, "timezone": str(tz)},
                "metric_basis": "Prospectos y etapas: cohorte registrada en el periodo; citas: fecha de cita; contactos: último contacto. Pendientes: estado actual."}
