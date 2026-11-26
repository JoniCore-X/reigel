"""Task reminders follow current relationships without exposing stale links."""

from datetime import UTC, datetime, timedelta

import pytest

from reigel import core
from reigel.core import DomainError, Store
from team_auth import allow, login as team_login


@pytest.fixture
def task_notice(tmp_path, monkeypatch):
    fixed = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
    monkeypatch.setattr(core, "now", lambda: fixed)
    store = Store(tmp_path / "task-notifications.sqlite3")
    password = "synthetic-task-notice-password"
    admin = store.create_user(
        {"name": "QA Admin", "email": "notice-admin@example.test", "password": password, "role": "admin"},
        bootstrap=True,
    )
    allow(store, admin, "notice-advisor@example.test", "notice-outsider@example.test")
    advisor = store.create_user(
        {"name": "QA Advisor", "email": "notice-advisor@example.test", "password": password, "role": "advisor"},
        admin,
    )
    outsider = store.create_user(
        {"name": "QA Outsider", "email": "notice-outsider@example.test", "password": password, "role": "advisor"},
        admin,
    )
    leads = [
        store.create_lead(
            {"name": f"Synthetic prospect {number}", "email": f"prospect-{number}@example.test", "consent": True, "advisor_id": advisor["id"]},
            admin,
        )
        for number in (1, 2)
    ]
    task = store.save_task(
        {"lead_id": leads[0]["id"], "owner_id": advisor["id"], "description": "Synthetic follow-up", "due_at": "2026-11-05T16:00:00+00:00", "reminder_hours": 2},
        admin,
    )
    notice = next(
        row for row in store.list_notifications(advisor)["notifications"]
        if row["entity_id"] == task["id"]
    )
    notice = store.mark_notification(notice["id"], {"read": True}, advisor)
    return store, admin, advisor, outsider, leads, task, notice, fixed


def task_notices(store, advisor, task):
    return [
        row for row in store.list_notifications(advisor)["notifications"]
        if row["entity_id"] == task["id"]
    ]


def assert_preserved_notice(current, original):
    for key in ("id", "event_key", "entity_id", "created_at", "read_at"):
        assert current[key] == original[key]
    assert current["read"] is True


def test_task_notice_moves_with_task_and_survives_previous_lead_transfer(task_notice, monkeypatch):
    store, admin, advisor, outsider, leads, task, original, fixed = task_notice
    store.save_task({"lead_id": leads[1]["id"]}, advisor, task["id"])
    monkeypatch.setattr(core, "now", lambda: fixed + timedelta(minutes=1))

    notices = task_notices(store, advisor, task)

    assert len(notices) == 1
    assert notices[0]["lead_id"] == leads[1]["id"]
    assert_preserved_notice(notices[0], original)
    store.update_lead(leads[0]["id"], {"advisor_id": outsider["id"]}, admin)
    notices = task_notices(store, advisor, task)
    assert len(notices) == 1
    assert notices[0]["lead_id"] == leads[1]["id"]
    assert_preserved_notice(notices[0], original)
    assert store.query_tasks(advisor, lead_id=leads[1]["id"])["tasks"][0]["id"] == task["id"]
    assert store.query_tasks(outsider)["total"] == 0
    with pytest.raises(DomainError) as denied:
        store.mark_notification(original["id"], {"read": False}, outsider)
    assert denied.value.status == 404


def test_task_notice_removes_previous_lead_link_when_task_becomes_internal(task_notice):
    store, admin, advisor, outsider, leads, task, original, _ = task_notice
    store.save_task({"lead_id": None}, advisor, task["id"])
    store.update_lead(leads[0]["id"], {"advisor_id": outsider["id"]}, admin)

    notices = task_notices(store, advisor, task)

    assert len(notices) == 1
    assert notices[0]["lead_id"] is None
    assert_preserved_notice(notices[0], original)
    assert store.query_tasks(advisor)["tasks"][0]["lead_id"] is None
    with pytest.raises(DomainError) as denied:
        store.mark_notification(original["id"], {"read": False}, outsider)
    assert denied.value.status == 404


@pytest.mark.parametrize("internal", [False, True])
def test_stale_task_notice_is_inaccessible_until_current_link_can_be_regenerated(task_notice, monkeypatch, internal):
    store, _, advisor, _, leads, task, original, fixed = task_notice
    linked_lead = None if internal else leads[1]["id"]
    store.save_task({"lead_id": linked_lead, "reminder_hours": 0}, advisor, task["id"])

    with pytest.raises(DomainError) as denied:
        store.mark_notification(original["id"], {"read": False}, advisor)
    assert denied.value.status == 404
    assert task_notices(store, advisor, task) == []

    monkeypatch.setattr(core, "now", lambda: fixed + timedelta(hours=1, minutes=1))
    notices = task_notices(store, advisor, task)
    assert len(notices) == 1
    assert notices[0]["lead_id"] == linked_lead
    assert notices[0]["type"] == "task_overdue"
    assert_preserved_notice(notices[0], original)
