"""Tablas del motor. Migración aditiva e idempotente, como el resto del esquema.

Las decisiones se guardan con su clave de idempotencia: el motor puede volver a
pasar por el mismo registro las veces que haga falta sin duplicar trabajo.
"""
from __future__ import annotations

from . import policy

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_policies (
 action TEXT PRIMARY KEY,mode TEXT NOT NULL,max_per_day INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL,updated_by TEXT REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS agent_runtime (
 key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_cycles (
 id TEXT PRIMARY KEY,trigger TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,
 leads_seen INTEGER NOT NULL DEFAULT 0,decided INTEGER NOT NULL DEFAULT 0,
 executed INTEGER NOT NULL DEFAULT 0,held INTEGER NOT NULL DEFAULT 0,
 skipped INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS agent_decisions (
 id TEXT PRIMARY KEY,cycle_id TEXT NOT NULL REFERENCES agent_cycles(id),
 lead_id TEXT NOT NULL REFERENCES leads(id),advisor_id TEXT REFERENCES users(id),
 action TEXT NOT NULL,reason TEXT NOT NULL,priority REAL NOT NULL DEFAULT 0,
 mode TEXT NOT NULL,status TEXT NOT NULL,effect TEXT NOT NULL DEFAULT '',
 entity_id TEXT,due_at TEXT,idempotency_key TEXT NOT NULL UNIQUE,
 decided_at TEXT NOT NULL,resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS agent_decisions_lead ON agent_decisions(lead_id,decided_at DESC);
CREATE INDEX IF NOT EXISTS agent_decisions_status ON agent_decisions(status,priority DESC);
CREATE INDEX IF NOT EXISTS agent_cycles_time ON agent_cycles(started_at DESC);
"""

# Memoria del agente. Solo se inserta: una revisión crea una fila nueva y enlaza la
# anterior. `supersedes` y `superseded_by` forman la cadena en los dos sentidos.
MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_beliefs (
 id TEXT PRIMARY KEY,lead_id TEXT NOT NULL REFERENCES leads(id),subject TEXT NOT NULL,
 claim TEXT NOT NULL,source_kind TEXT NOT NULL,source_ref TEXT NOT NULL DEFAULT '',
 confidence REAL NOT NULL DEFAULT 1,observed_at TEXT NOT NULL,expires_at TEXT,
 supersedes TEXT REFERENCES agent_beliefs(id),superseded_by TEXT REFERENCES agent_beliefs(id),
 approved_by TEXT REFERENCES users(id),approved_at TEXT,
 retracted_at TEXT,retracted_reason TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS agent_beliefs_lead ON agent_beliefs(lead_id,observed_at DESC);
CREATE INDEX IF NOT EXISTS agent_beliefs_subject ON agent_beliefs(lead_id,subject,superseded_by);
"""

# Informe de necesidad: lo que el equipo recibe cuando el chat no pudo responder.
NEEDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_need_reports (
 id TEXT PRIMARY KEY,conversation_id TEXT REFERENCES conversations(id),lead_id TEXT REFERENCES leads(id),
 route TEXT NOT NULL,reason TEXT NOT NULL,topic TEXT NOT NULL,need TEXT NOT NULL,question TEXT NOT NULL,
 urgency TEXT NOT NULL DEFAULT 'normal',known_json TEXT NOT NULL DEFAULT '[]',
 missing_json TEXT NOT NULL DEFAULT '[]',asked_next_step INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'open',repeats INTEGER NOT NULL DEFAULT 1,
 owner_id TEXT REFERENCES users(id),claimed_at TEXT,resolved_at TEXT,
 resolution TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS agent_needs_open ON agent_need_reports(status,created_at DESC);
CREATE INDEX IF NOT EXISTS agent_needs_conversation ON agent_need_reports(conversation_id,topic,status);
"""

# Constancias de permiso para llamar. Solo se inserta: «no llamar» es una más, y la
# última manda. Nada se sobrescribe, así que el historial queda completo.
CALLS_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_call_consent (
 id TEXT PRIMARY KEY,lead_id TEXT NOT NULL REFERENCES leads(id),kind TEXT NOT NULL,
 evidence TEXT NOT NULL,captured_at TEXT NOT NULL,captured_by TEXT REFERENCES users(id),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS agent_call_consent_lead ON agent_call_consent(lead_id,captured_at DESC);
"""

VERSION = "team_caguas_agent_v1"
MEMORY_VERSION = "team_caguas_agent_memory_v2"
NEEDS_VERSION = "team_caguas_agent_needs_v3"
CALLS_VERSION = "team_caguas_agent_calls_v4"


def migrate_agent(db) -> None:
    """Crea las tablas y siembra la política por defecto, sin encender el motor."""
    from ..core import stamp

    db.executescript(SCHEMA)
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY,applied_at TEXT NOT NULL)")
    for action, mode in policy.defaults().items():
        db.execute(
            "INSERT OR IGNORE INTO agent_policies(action,mode,max_per_day,updated_at,updated_by) VALUES(?,?,0,?,NULL)",
            (action, mode, stamp()),
        )
    # Apagado por defecto. Encenderlo es una decisión explícita de administración.
    db.execute("INSERT OR IGNORE INTO agent_runtime(key,value,updated_at) VALUES('enabled','0',?)", (stamp(),))
    db.execute("INSERT OR IGNORE INTO schema_migrations VALUES(?,?)", (VERSION, stamp()))
    db.executescript(MEMORY_SCHEMA)
    db.execute("INSERT OR IGNORE INTO schema_migrations VALUES(?,?)", (MEMORY_VERSION, stamp()))
    db.executescript(NEEDS_SCHEMA)
    db.execute("INSERT OR IGNORE INTO schema_migrations VALUES(?,?)", (NEEDS_VERSION, stamp()))
    db.executescript(CALLS_SCHEMA)
    db.execute("INSERT OR IGNORE INTO schema_migrations VALUES(?,?)", (CALLS_VERSION, stamp()))
