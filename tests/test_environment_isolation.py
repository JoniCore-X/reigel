"""An app built on an explicit database path never reads the project .env.

conftest.py already replaces api.load_environment for every test; here a spy
replaces it again to observe whether create_app calls it. No test calls
create_app() without a path: that would open the commercial database.
"""
from reigel import api


def spy(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "load_environment", lambda path=None: calls.append(path))
    return calls


def test_explicit_database_path_does_not_load_dotenv(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    api.create_app(tmp_path / "aislada.sqlite3")
    assert calls == []


def test_explicit_path_can_opt_in_to_dotenv(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    api.create_app(tmp_path / "con-entorno.sqlite3", load_env=True)
    assert calls == [None]
