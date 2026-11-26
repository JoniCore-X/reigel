"""Cola de aprendizaje con aprobación humana (tramo A): sin rutas ni modelo."""
from datetime import UTC, datetime, timedelta

import pytest

from reigel import core
from reigel.core import DomainError, Store
from reigel.learning import (
    LearningQueue, migrate_learning, novelty, priority, public_answer_problem, question_key, redact, topic_of,
)
from team_auth import allow, login as team_login

PASSWORD = "synthetic-password-learning"
GOOD_ANSWER = (
    "Ese trabajo lo hace el equipo de Power Solar. El equipo revisa la estructura del techo y su "
    "pendiente antes de proponer nada. Si quieres esa evaluación, pídela en «Citas y equipo»."
)


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path / "learning.sqlite3")
    admin = store.create_user({"name": "QA Admin", "email": "learn-admin@example.test", "password": PASSWORD, "role": "admin"}, bootstrap=True)
    allow(store, admin, "learn-advisor@example.test")
    advisor = store.create_user({"name": "QA Asesora", "email": "learn-advisor@example.test", "password": PASSWORD, "role": "advisor"}, admin)
    return LearningQueue(store), store, admin, advisor


def audit_actions(store):
    with store.connect() as db:
        return [row["action"] for row in db.execute("SELECT action FROM audit_events WHERE action LIKE 'learning.%' ORDER BY rowid")]


def test_migration_is_additive_and_idempotent(queue):
    learning, store, *_ = queue
    with store.connect() as db:
        migrate_learning(db)
    with store.connect() as db:
        migrate_learning(db)
        tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        versions = db.execute("SELECT count(*) FROM schema_migrations WHERE version='learning_queue_v1'").fetchone()[0]
        columns = {row["name"] for row in db.execute("PRAGMA table_info(learning_gaps)")}
    assert {"learning_gaps", "learning_proposals", "learning_eval_cases", "learning_eval_runs", "leads", "users"} <= tables
    assert versions == 1
    assert {"first_seen_at", "last_seen_at", "route", "reason", "question", "question_key",
            "occurrences", "topic", "priority", "status"} <= columns
    # Ninguna columna identifica a la persona ni a su conversación.
    assert not columns & {"conversation_id", "visitor_id", "ip", "cookie", "name", "email", "phone"}
    LearningQueue(store)  # una segunda instancia sobre la misma base no falla


def test_redaction_hides_contacts_addresses_long_numbers_and_names():
    raw = ("Hola, me llamo Juan Pérez Rivera. Vivo en Calle Luna 123, Urb. Las Flores, Caguas 00725. "
           "Escribe a juan.perez@example.test o al (787) 555-1234. Mi tarjeta es 4111 1111 1111 1111.")
    clean = redact(raw)
    for leaked in ("Juan", "Pérez", "Luna", "Flores", "00725", "juan.perez", "555", "1234", "4111", "1111"):
        assert leaked not in clean
    for marker in ("[nombre omitido]", "[dirección omitida]", "[número omitido]", "[correo omitido]", "[teléfono omitido]"):
        assert marker in clean
    assert "Caguas" in clean  # un municipio solo no identifica a la persona
    assert redact("¿Qué debo revisar si mi techo es de madera?") == "¿Qué debo revisar si mi techo es de madera?"


def test_record_gap_stores_redacted_text_only_and_groups_duplicates(queue):
    learning, store, admin, _ = queue
    first = learning.record_gap("ia", "fallback", "Hola, ¿qué debo revisar si mi techo es de MADERA? Soy Ana, 787-555-0101")
    second = learning.record_gap("ia", "blocked", "¿Que debo revisar si mi techo es de madera? Soy Ana, 787-555-0101!!")
    assert first["id"] == second["id"]
    assert second["occurrences"] == 2
    assert second["reason"] == "blocked"  # se conserva el motivo de mayor incertidumbre
    assert second["topic"] == "techo"
    assert "787" not in second["question"] and "Ana" not in second["question"]
    # Otra ruta es otro hueco; un texto vacío tras redactar no se guarda.
    assert learning.record_gap("chat", "fallback", "¿Qué debo revisar si mi techo es de madera?")["id"] != first["id"]
    assert learning.record_gap("ia", "fallback", "  ¡¡!!  ") is None
    with store.connect() as db:
        stored = [row["question"] for row in db.execute("SELECT question FROM learning_gaps")]
    assert all("555" not in value and "Ana" not in value for value in stored)
    with pytest.raises(DomainError):
        learning.record_gap("ia", "otro", "pregunta")
    with pytest.raises(DomainError):
        learning.record_gap("web", "fallback", "pregunta")


def test_question_key_ignores_case_accents_punctuation_and_greetings():
    assert question_key("¡Hola! ¿Qué debo revisar, por favor?") == question_key("que debo revisar")


def test_priority_heuristic_is_bounded_and_ordered():
    now = datetime(2026, 11, 25, 12, tzinfo=UTC)
    fresh = now.isoformat()
    old = (now - timedelta(days=120)).isoformat()
    assert 0 <= priority("blocked", "techo", 1, fresh, current=now) <= 100
    assert priority("staff_flag", "techo", 50, fresh, cost=0, current=now) == 100.0
    assert priority("blocked", "techo", 1, fresh, current=now) > priority("fallback", "techo", 1, fresh, current=now)
    assert priority("fallback", "techo", 1, fresh, current=now) > priority("model_error", "techo", 1, fresh, current=now)
    assert priority("blocked", "techo", 1, fresh, current=now) > priority("blocked", "general", 1, fresh, current=now)
    assert priority("blocked", "techo", 8, fresh, current=now) > priority("blocked", "techo", 1, fresh, current=now)
    assert priority("blocked", "techo", 1, fresh, current=now) > priority("blocked", "techo", 1, old, current=now)
    assert priority("blocked", "techo", 1, fresh, cost=1, current=now) < priority("blocked", "techo", 1, fresh, cost=0, current=now)
    assert 0 < novelty(1, fresh, now) <= 1
    assert topic_of("¿Cuánto cuesta el contrato?") == "contrato"
    assert topic_of("¿Qué tal?") == "general"
    with pytest.raises(ValueError):
        LearningQueue.__init__(object.__new__(LearningQueue), None, cost=-1)


def test_list_is_team_only_filterable_and_sorted_by_priority(queue):
    learning, _, admin, advisor = queue
    low = learning.record_gap("ia", "model_error", "¿Qué tal el clima?")
    high = learning.record_gap("ia", "blocked", "¿Dónde pongo las placas en el techo?")
    learning.record_gap("chat", "fallback", "¿Cómo leo mi factura?")
    listing = learning.list(admin)
    assert [gap["id"] for gap in listing["gaps"]][0] == high["id"]
    assert listing["gaps"][-1]["id"] == low["id"]
    assert listing["timezone"] == "America/Puerto_Rico"
    assert listing["gaps"][0]["last_seen_local"]
    assert "question_key" not in listing["gaps"][0]
    assert {gap["route"] for gap in learning.list(admin, route="chat")["gaps"]} == {"chat"}
    assert [gap["id"] for gap in learning.list(admin, reason="model_error")["gaps"]] == [low["id"]]
    # Asesores ven la cola (ya redactada) para poder proponer; sin cuenta, nadie.
    assert [gap["id"] for gap in learning.list(advisor)["gaps"]] == [gap["id"] for gap in listing["gaps"]]
    assert learning.proposals(advisor, high["id"]) == []
    for outsider in (None, {"id": "x", "role": "visitor"}, {**advisor, "active": False}):
        with pytest.raises(DomainError) as denied:
            learning.list(outsider)
        assert denied.value.status == 403
    with pytest.raises(DomainError):
        learning.list(admin, status="borrado")


def test_advisor_proposes_but_only_admin_approves_or_rejects(queue):
    learning, store, admin, advisor = queue
    gap = learning.record_gap("ia", "blocked", "¿Qué debo revisar si mi techo es de madera y de baja pendiente?")
    proposal = learning.propose(gap["id"], {"proposed_answer": GOOD_ANSWER, "source_note": "Criterio del titular: el equipo instala."}, advisor)
    assert proposal["status"] == "pending" and proposal["created_by"] == advisor["id"]
    for action in (learning.approve, learning.reject):
        with pytest.raises(DomainError) as denied:
            action(proposal["id"], advisor)
        assert denied.value.status == 403
    for action in (learning.reject_gap, learning.resolve):
        with pytest.raises(DomainError) as denied:
            action(gap["id"], advisor)
        assert denied.value.status == 403
    with pytest.raises(DomainError):
        learning.propose(gap["id"], {"proposed_answer": GOOD_ANSWER, "source_note": "x"}, None)
    approved = learning.approve(proposal["id"], admin, "Revisado.")
    assert approved["status"] == "approved" and approved["reviewed_by"] == admin["id"] and approved["reviewed_at"]
    assert learning.list(admin, status="approved")["gaps"][0]["id"] == gap["id"]
    with pytest.raises(DomainError) as twice:
        learning.approve(proposal["id"], admin)
    assert twice.value.status == 409
    with pytest.raises(DomainError):
        learning.propose(gap["id"], {"proposed_answer": GOOD_ANSWER, "source_note": "otra"}, advisor)
    answers = learning.approved_answers("ia")
    assert [item["proposal_id"] for item in answers] == [proposal["id"]]
    learning.resolve(gap["id"], admin)
    assert learning.list(admin, status="resolved")["gaps"][0]["id"] == gap["id"]
    # Si el hueco vuelve a aparecer tras resolverse, se reabre.
    assert learning.record_gap("ia", "fallback", "¿Qué debo revisar si mi techo es de madera y de baja pendiente?")["status"] == "open"


def test_reject_reopens_gap_and_reject_gap_closes_it(queue):
    learning, _, admin, advisor = queue
    gap = learning.record_gap("ia", "fallback", "¿Cómo funciona el inversor?")
    proposal = learning.propose(gap["id"], {"proposed_answer": "Texto incompleto.", "source_note": "borrador"}, advisor)
    assert learning.list(admin)["gaps"][0]["status"] == "proposed"
    rejected = learning.reject(proposal["id"], admin, "Falta la fuente oficial.")
    assert rejected["status"] == "rejected" and rejected["review_note"] == "Falta la fuente oficial."
    assert learning.list(admin)["gaps"][0]["status"] == "open"
    learning.propose(gap["id"], {"proposed_answer": "Otro texto.", "source_note": "borrador"}, advisor)
    learning.reject_gap(gap["id"], admin, "No era un fallo.")
    assert learning.list(admin)["gaps"][0]["status"] == "rejected"
    assert all(item["status"] == "rejected" for item in learning.proposals(admin, gap["id"]))


@pytest.mark.parametrize("answer", [
    "El sistema cuesta 15,000 dólares.",
    "Con placas ahorrarás en tu factura.",
    "Te garantizamos el resultado.",
    "Escríbenos a ventas@example.test para más detalles.",
    "Llama al 787-555-0100 y te atienden.",
    "Tenemos financiamiento disponible para tu caso.",
    "Puedes colocar las placas tú mismo en el techo.",
    "Tu cita está confirmada para mañana.",
])
def test_approval_requires_public_validators(queue, answer):
    learning, store, admin, advisor = queue
    assert public_answer_problem(answer)
    gap = learning.record_gap("ia", "blocked", "pregunta sintética")
    proposal = learning.propose(gap["id"], {"proposed_answer": answer, "source_note": "prueba"}, advisor)
    with pytest.raises(DomainError) as blocked:
        learning.approve(proposal["id"], admin)
    assert blocked.value.status == 422 and blocked.value.detail.startswith("No se puede aprobar:")
    assert learning.proposals(admin, gap["id"])[0]["status"] == "pending"
    assert "learning.proposal.approve_blocked" in audit_actions(store)


def test_good_answer_passes_public_validators():
    assert public_answer_problem(GOOD_ANSWER) is None


def test_every_action_is_audited(queue):
    learning, store, admin, advisor = queue
    gap = learning.record_gap("ia", "blocked", "¿Dónde van las placas?")
    learning.record_gap("ia", "blocked", "¿Dónde van las placas?")
    flagged = learning.record_gap("chat", "staff_flag", "Respuesta mala sobre baterías", actor=advisor)
    first = learning.propose(gap["id"], {"proposed_answer": "Texto.", "source_note": "borrador"}, advisor)
    learning.reject(first["id"], admin)
    second = learning.propose(gap["id"], {"proposed_answer": GOOD_ANSWER, "source_note": "titular"}, advisor)
    learning.approve(second["id"], admin)
    learning.resolve(gap["id"], admin)
    learning.reject_gap(flagged["id"], admin)
    learning.purge_expired(admin)
    assert audit_actions(store) == [
        "learning.gap.create", "learning.gap.repeat", "learning.gap.create",
        "learning.proposal.create", "learning.proposal.reject", "learning.proposal.create",
        "learning.proposal.approve", "learning.gap.resolve", "learning.gap.reject", "learning.gap.purge",
    ]
    with store.connect() as db:
        actor = db.execute("SELECT actor_id FROM audit_events WHERE action='learning.proposal.approve'").fetchone()[0]
    assert actor == admin["id"]
    with pytest.raises(DomainError):
        learning.record_gap("ia", "staff_flag", "sin cuenta")


def test_retention_deletes_only_unapproved_gaps_older_than_ninety_days(queue, monkeypatch):
    learning, store, admin, advisor = queue
    past = datetime(2026, 7, 1, 12, tzinfo=UTC)
    monkeypatch.setattr(core, "now", lambda: past)
    stale_open = learning.record_gap("ia", "fallback", "pregunta vieja abierta")
    stale_proposed = learning.record_gap("ia", "fallback", "pregunta vieja propuesta")
    learning.propose(stale_proposed["id"], {"proposed_answer": "Texto.", "source_note": "borrador"}, advisor)
    stale_approved = learning.record_gap("ia", "blocked", "pregunta vieja aprobada")
    good = learning.propose(stale_approved["id"], {"proposed_answer": GOOD_ANSWER, "source_note": "titular"}, advisor)
    learning.approve(good["id"], admin)
    recent_time = past + timedelta(days=89)
    monkeypatch.setattr(core, "now", lambda: recent_time)
    recent = learning.record_gap("ia", "fallback", "pregunta reciente")
    later = past + timedelta(days=91)
    with pytest.raises(DomainError):
        learning.purge_expired(advisor, current=later)
    assert learning.purge_expired(current=later) == 2
    with store.connect() as db:
        remaining = {row["id"] for row in db.execute("SELECT id FROM learning_gaps")}
        orphans = db.execute("SELECT count(*) FROM learning_proposals WHERE gap_id NOT IN (SELECT id FROM learning_gaps)").fetchone()[0]
    assert remaining == {stale_approved["id"], recent["id"]}
    assert stale_open["id"] not in remaining and orphans == 0


def test_reviewed_for_returns_only_related_approved_answers(queue):
    learning, _, admin, advisor = queue
    gap = learning.record_gap("ia", "blocked", "¿Qué debo revisar si mi techo es de madera y de baja pendiente?")
    proposal = learning.propose(gap["id"], {"proposed_answer": GOOD_ANSWER, "source_note": "titular"}, advisor)
    assert learning.reviewed_for("¿Qué revisan en un techo de madera?", "ia") == []  # aún sin aprobar
    learning.approve(proposal["id"], admin)
    related = learning.reviewed_for("Mi techo es de madera, ¿qué revisan?", "ia")
    assert related == [{"question": gap["question"], "answer": GOOD_ANSWER}]
    assert learning.reviewed_for("¿Cómo funciona una batería?", "ia") == []
    assert learning.reviewed_for("Mi techo es de madera, ¿qué revisan?", "chat") == []


def test_purge_is_throttled_and_silent_when_nothing_expires(queue):
    learning, store, *_ = queue
    assert learning.maybe_purge() == 0
    assert learning.maybe_purge() is None
    assert "learning.gap.purge" not in audit_actions(store)
