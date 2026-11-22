"""Short appointment codes that anyone can read aloud and type."""
import re
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from reigel.core import (REFERENCE_ALPHABET, SCHEMA, Store, format_reference, migrate_appointment_reference,
                         normalize_reference)
from reigel.webchat import WebChat, spoken_datetime

from test_webchat import Knowledge, booking

CODE = re.compile(r"^[ACDEFGHJKMNPQRTUVWXY34679]{3}-[ACDEFGHJKMNPQRTUVWXY34679]{3}$")


@pytest.fixture
def chat(tmp_path):
    store = Store(tmp_path / "codes.db")
    admin = store.create_user({"name": "Asesora QA", "email": "admin@codes.test", "password": "codes-long-test-password", "role": "admin"}, bootstrap=True)
    store.update_user(admin["id"], {"public_booking": True, "work_days": list(range(7))}, admin)
    service = WebChat(store, Knowledge())
    token, _ = service.start()
    return service, store, admin, token


def test_alphabet_avoids_characters_that_look_alike():
    for confusing in "0O1IL2Z5S8B":
        assert confusing not in REFERENCE_ALPHABET
    assert format_reference("K7M4QX") == "K7M-4QX"
    assert normalize_reference(" k7m 4qx ") == "K7M4QX"
    assert normalize_reference("K7M-4QX") == "K7M4QX"
    assert normalize_reference("K0M-4QX") == ""
    assert normalize_reference("1b7af6f51aa04c4095335a15462caabf") == ""


def test_public_booking_shows_a_short_code_and_a_plain_date(chat):
    service, store, admin, token = chat
    result = service.book(token, booking(store, admin))
    code = result["appointment"]["reference"]
    assert CODE.match(code), code
    reply = result["messages"][-1]["text"]
    assert f"Código de tu cita: {code}" in reply
    assert "hora de Puerto Rico" in reply and "America/Puerto_Rico" not in reply
    assert result["appointment"]["id"] not in reply
    assert not re.search(r"\d{2}/\d{2}/\d{4}", reply)
    assert service.state(token)["appointment"]["reference"] == code


def test_team_finds_the_lead_by_code_typed_loosely(chat):
    service, store, admin, token = chat
    code = service.book(token, booking(store, admin))["appointment"]["reference"]
    for typed in (code, code.lower(), code.replace("-", " "), code.replace("-", "")):
        leads = store.query_leads(admin, q=typed)["leads"]
        assert [lead["name"] for lead in leads] == ["Cliente QA"], typed
    assert store.query_leads(admin, q="ZZZ-ZZZ")["leads"] == []


def test_team_bookings_get_codes_too_and_codes_are_unique(chat):
    _, store, admin, _ = chat
    day = (datetime.now(UTC) + timedelta(days=3)).date().isoformat()
    codes = set()
    for index, slot in enumerate(store.slots(admin["id"], day)["slots"][:5]):
        lead = store.create_lead({"name": f"Persona {index}", "email": f"p{index}@codes.test", "phone": f"+1787555{index:04d}",
                                  "municipality": "Caguas", "consent": True, "advisor_id": admin["id"]}, admin)
        appointment = store.book({"lead_id": lead["id"], "advisor_id": admin["id"], "start_at": slot["start_at"]}, source="equipo", actor=admin)
        codes.add(appointment["reference"])
    assert len(codes) == 5 and all(len(code) == 6 for code in codes)


def test_existing_appointments_receive_a_code_on_migration(tmp_path):
    db = sqlite3.connect(tmp_path / "legacy.db")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.execute("INSERT INTO users(id,name,email,password_hash,role,created_at) VALUES('u','U','u@x.test','x','admin','2026-01-01')")
    db.execute("INSERT INTO leads(id,name,created_at,updated_at) VALUES('l','L','2026-01-01','2026-01-01')")
    for index in range(3):
        db.execute("INSERT INTO appointments VALUES(?,?,?,?,?,?,?,?)",
                   (f"a{index}", "l", "u", f"2026-12-0{index + 1}T14:00:00+00:00", f"2026-12-0{index + 1}T14:30:00+00:00", "confirmed", "equipo", "2026-01-01"))
    migrate_appointment_reference(db)
    migrate_appointment_reference(db)
    codes = [row[0] for row in db.execute("SELECT reference FROM appointments")]
    assert len(set(codes)) == 3 and all(normalize_reference(code) == code for code in codes)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE appointments SET reference=? WHERE id='a1'", (codes[0],))
    db.close()


def test_spoken_datetime_in_spanish():
    assert spoken_datetime(datetime(2026, 11, 22, 10, 0)) == "domingo 22 de noviembre a las 10:00 a. m."
    assert spoken_datetime(datetime(2026, 11, 23, 15, 30)) == "lunes 23 de noviembre a las 3:30 p. m."
    assert spoken_datetime(datetime(2026, 11, 23, 0, 5)) == "lunes 23 de noviembre a las 12:05 a. m."
