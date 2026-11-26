"""Keep local dotenv configuration outside the test environment."""

import pytest

from reigel import api


@pytest.fixture(autouse=True)
def disable_dotenv_loading(monkeypatch):
    """Tests declare their configuration explicitly and never load real secrets."""
    monkeypatch.setattr(api, "load_environment", lambda path=None: None)
    # The team allowlist seed is read from the process environment; tests set it explicitly.
    monkeypatch.delenv("REIGEL_TEAM_ALLOWED_EMAILS", raising=False)
