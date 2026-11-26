"""The planner is pure: same lead and context, same decision, no database and no model."""
from datetime import UTC, datetime, timedelta

from reigel.agent import planner
from reigel.agent.policy import ACTIONS
from reigel.core import STAGES

NOW = datetime(2026, 11, 26, 15, 0, tzinfo=UTC)


def lead(**overrides):
    base = {
        "id": "lead-1", "name": "Prospecto sintético", "stage": "nuevo", "advisor_id": "advisor-1",
        "created_at": (NOW - timedelta(hours=2)).isoformat(), "last_contact_at": None,
        "next_followup_at": None, "opportunity_value": None, "monthly_bill": None,
    }
    return {**base, **overrides}


def actions(result):
    return [item["action"] for item in result]


def test_a_new_lead_gets_a_first_contact_decision():
    result = planner.evaluate(lead(), {}, NOW)
    assert actions(result) == ["first_contact"]
    assert result[0]["effect"] == "task" and result[0]["task_type"] == "call"
    assert result[0]["idempotency_key"] == "first_contact:lead-1:2026-11-26"


def test_closed_leads_are_never_touched():
    for stage in ("ganado", "perdido"):
        assert planner.evaluate(lead(stage=stage), {}, NOW) == []


def test_a_lead_without_an_advisor_is_only_routed_for_assignment():
    result = planner.evaluate(lead(advisor_id=None, stage="calificado"), {}, NOW)
    assert actions(result) == ["assign_advisor"]
    assert result[0]["effect"] == "notify" and result[0]["audience"] == "admin"


def test_an_overdue_followup_outranks_the_same_action_on_time():
    late = planner.evaluate(
        lead(stage="contactado", next_followup_at=(NOW - timedelta(days=9)).isoformat()), {}, NOW)
    fresh = planner.evaluate(
        lead(stage="contactado", next_followup_at=(NOW - timedelta(hours=1)).isoformat()), {}, NOW)
    assert actions(late) == actions(fresh) == ["followup"]
    assert late[0]["priority"] > fresh[0]["priority"]
    assert "9 días" in late[0]["reason"]


def test_a_followup_that_is_not_due_yet_produces_nothing():
    future = planner.evaluate(
        lead(stage="contactado", next_followup_at=(NOW + timedelta(days=1)).isoformat()), {}, NOW)
    assert future == []


def test_an_upcoming_appointment_is_the_most_urgent_decision():
    context = {"next_appointment_at": (NOW + timedelta(hours=20)).isoformat(), "next_appointment_id": "cita-7"}
    result = planner.evaluate(lead(stage="contactado"), context, NOW)
    assert result[0]["action"] == "confirm_appointment"
    assert result[0]["idempotency_key"].endswith(":cita-7")
    assert "20 horas" in result[0]["reason"]


def test_an_appointment_beyond_the_window_is_not_confirmed_yet():
    context = {"next_appointment_at": (NOW + timedelta(days=5)).isoformat(), "next_appointment_id": "cita-8"}
    assert "confirm_appointment" not in actions(planner.evaluate(lead(stage="contactado"), context, NOW))


def test_a_qualified_lead_with_an_appointment_is_not_asked_to_book_another():
    without = planner.evaluate(lead(stage="calificado"), {}, NOW)
    assert "propose_appointment" in actions(without)
    context = {"next_appointment_at": (NOW + timedelta(days=4)).isoformat(), "next_appointment_id": "cita-9"}
    assert "propose_appointment" not in actions(planner.evaluate(lead(stage="calificado"), context, NOW))


def test_a_pending_task_of_the_same_kind_stops_the_engine_from_insisting():
    assert planner.evaluate(lead(), {"open_task_types": {"call"}}, NOW) == []


def test_a_pending_task_never_blocks_an_internal_notice():
    result = planner.evaluate(
        lead(advisor_id="advisor-1", stage="negociacion",
             last_contact_at=(NOW - timedelta(days=8)).isoformat()),
        {"open_task_types": {"call", "follow_up"}}, NOW)
    assert actions(result) == ["escalate_stalled"]


def test_a_presented_proposal_waits_the_silence_threshold():
    quiet = planner.evaluate(
        lead(stage="propuesta_presentada", last_contact_at=(NOW - timedelta(days=2)).isoformat()), {}, NOW)
    overdue = planner.evaluate(
        lead(stage="propuesta_presentada", last_contact_at=(NOW - timedelta(days=4)).isoformat()), {}, NOW)
    assert quiet == []
    assert actions(overdue) == ["followup_proposal"]


def test_a_long_silence_hands_the_lead_to_a_person_instead_of_queueing_work():
    """Beyond the dormant threshold only review_dormant applies, and it needs approval:
    the engine must not fill an advisor's day with leads nobody has touched in months."""
    result = planner.evaluate(
        lead(stage="contactado", last_contact_at=(NOW - timedelta(days=40)).isoformat()), {}, NOW)
    assert actions(result) == ["review_dormant"]
    assert ACTIONS["review_dormant"]["default_mode"] == "approval"


def test_a_scheduled_followup_still_wins_over_the_dormant_review():
    """An overdue date is a commitment a person made: that task is created anyway."""
    result = planner.evaluate(
        lead(stage="contactado", last_contact_at=(NOW - timedelta(days=40)).isoformat(),
             next_followup_at=(NOW - timedelta(days=35)).isoformat()), {}, NOW)
    assert result[0]["action"] == "followup" and "review_dormant" in actions(result)


def test_the_value_the_team_recorded_breaks_a_tie():
    plain = planner.evaluate(lead(), {}, NOW)[0]
    valued = planner.evaluate(lead(opportunity_value=50000), {}, NOW)[0]
    billed = planner.evaluate(lead(monthly_bill=500), {}, NOW)[0]
    assert valued["priority"] > billed["priority"] > plain["priority"]


def test_an_absent_or_broken_timestamp_never_raises():
    assert planner.evaluate(lead(created_at="no es una fecha"), {}, NOW)[0]["action"] == "first_contact"
    assert planner.evaluate(lead(created_at=None), {}, NOW)[0]["action"] == "first_contact"


def test_the_last_registered_activity_counts_as_contact():
    context = {"last_activity_at": (NOW - timedelta(hours=3)).isoformat()}
    assert planner.evaluate(lead(stage="contactado", last_contact_at=None), context, NOW) == []


def test_no_action_in_this_phase_reaches_a_person_outside_the_team():
    assert [name for name, spec in ACTIONS.items() if spec["outbound"]] == []


def test_every_open_stage_of_the_pipeline_produces_a_decision():
    """A neglected lead must never fall through the engine, whatever stage it sits in.
    This is what the synthetic preview caught: 'cita' and 'propuesta_preparacion' had no rule."""
    neglected = {"last_contact_at": (NOW - timedelta(days=10)).isoformat()}
    for stage in STAGES:
        result = planner.evaluate(lead(stage=stage, **neglected), {}, NOW)
        if stage in planner.TERMINAL_STAGES:
            assert result == [], stage
        else:
            assert result, f"la etapa {stage} no produce ninguna decisión"


def test_a_booked_appointment_in_the_future_needs_nothing_until_the_window():
    context = {"next_appointment_at": (NOW + timedelta(days=6)).isoformat(), "next_appointment_id": "cita-3"}
    assert planner.evaluate(lead(stage="cita"), context, NOW) == []


def test_a_stage_that_claims_an_appointment_without_one_is_flagged():
    result = planner.evaluate(lead(stage="cita"), {}, NOW)
    assert actions(result) == ["close_appointment"]
    assert "no hay ninguna confirmada" in result[0]["reason"]


def test_a_contacted_lead_with_no_next_step_is_not_left_behind():
    quiet = planner.evaluate(
        lead(stage="contactado", last_contact_at=(NOW - timedelta(hours=18)).isoformat()), {}, NOW)
    stalled = planner.evaluate(
        lead(stage="contactado", last_contact_at=(NOW - timedelta(days=5)).isoformat()), {}, NOW)
    assert quiet == []
    assert actions(stalled) == ["followup"] and "sin próximo paso" in stalled[0]["reason"]
