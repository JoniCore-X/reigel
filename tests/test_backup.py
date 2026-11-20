"""scripts/backup.py copies the database exactly as it is, before any migration.

Every database here is synthetic and temporary; .env loading is disabled.
"""
import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from reigel import api
from reigel.core import SCHEMA, Store

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def backup(monkeypatch):
    monkeypatch.setattr(api, "load_environment", lambda path=None: None)
    monkeypatch.delenv("REIGEL_DB_PATH", raising=False)
    spec = importlib.util.spec_from_file_location("reigel_backup_script", ROOT / "scripts" / "backup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_environment", lambda path=None: None, raising=False)

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["backup.py", *argv])
        module.main()

    return run


def old_database(path):
    """A database from before the operations migration: base schema only, in WAL."""
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    db.execute("INSERT INTO settings(key,value) VALUES('name','Sintética antigua')")
    db.commit()
    db.close()


def schema(path):
    db = sqlite3.connect(f"{Path(path).as_uri()}?mode=ro", uri=True)
    try:
        return sorted(db.execute("SELECT type,name,sql FROM sqlite_master").fetchall(), key=str)
    finally:
        db.close()


def settings(path):
    db = sqlite3.connect(f"{Path(path).as_uri()}?mode=ro", uri=True)
    try:
        return dict(db.execute("SELECT key,value FROM settings").fetchall())
    finally:
        db.close()


def test_backup_does_not_migrate_the_source_before_copying(backup, tmp_path, monkeypatch, capsys):
    source = tmp_path / "antigua.db"
    old_database(source)
    before = schema(source)
    before_settings = settings(source)
    monkeypatch.setenv("REIGEL_DB_PATH", str(source))
    destination = tmp_path / "copias" / "antes-de-migrar.db"

    backup("--output", str(destination))

    assert schema(source) == before, "the backup changed the source schema"
    assert settings(source) == before_settings, "the backup wrote default settings into the source"
    names = {name for _, name, _ in schema(source)}
    assert "schema_migrations" not in names and "lead_activities" not in names
    assert schema(destination) == before
    assert settings(destination) == before_settings
    out = capsys.readouterr().out
    assert hashlib.sha256(destination.read_bytes()).hexdigest() in out


def test_explicit_database_argument_and_restoration_of_the_copy(backup, tmp_path):
    source = tmp_path / "activa.db"
    Store(source)  # current schema, migrated, synthetic
    destination = tmp_path / "copia.db"
    backup("--db", str(source), "--output", str(destination))
    assert schema(destination) == schema(source)

    # Restoring means pointing the application at the copy; it opens normally.
    restored = Store(destination)
    assert restored.settings()["timezone"] == "America/Puerto_Rico"


def test_copy_includes_changes_still_in_the_wal(backup, tmp_path):
    source = tmp_path / "viva.db"
    old_database(source)
    writer = sqlite3.connect(source)
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO settings(key,value) VALUES('pendiente','en el WAL')")
        writer.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        destination = tmp_path / "copia.db"
        backup("--db", str(source), "--output", str(destination))
    finally:
        writer.close()
    assert settings(destination)["pendiente"] == "en el WAL"


def test_missing_source_is_an_error_and_creates_nothing(backup, tmp_path):
    missing = tmp_path / "no-existe" / "reigel.db"
    with pytest.raises(SystemExit):
        backup("--db", str(missing), "--output", str(tmp_path / "copia.db"))
    assert not missing.parent.exists()
    assert not (tmp_path / "copia.db").exists()


def test_existing_destination_or_same_file_is_refused(backup, tmp_path):
    source = tmp_path / "activa.db"
    old_database(source)
    taken = tmp_path / "ocupada.db"
    taken.write_bytes(b"no tocar")
    with pytest.raises(SystemExit):
        backup("--db", str(source), "--output", str(taken))
    assert taken.read_bytes() == b"no tocar"
    with pytest.raises(SystemExit):
        backup("--db", str(source), "--output", str(source))
