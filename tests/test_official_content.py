"""Official Power Solar material is local, attributed and free of figures or offers."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reigel.api import create_app

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "frontend" / "assets" / "power-solar"
SYSTEM = ["placas", "microinversores", "bateria", "medicion-neta", "red-electrica", "electrodomesticos"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    return TestClient(create_app(tmp_path / "official.sqlite3"))


def test_contact_page_lists_every_service_center_beside_the_map(client):
    page = client.get("/contacto").text
    section = re.search(r'<section[^>]*id="centros".*?</section>', page, re.S).group(0)
    assert section.count("<li>") == 13
    for town in ("San Juan", "Bayamón", "Caguas", "Fajardo", "Guayama", "Ponce", "Yauco", "Mayagüez", "Moca", "Hatillo", "Isabela"):
        assert f"<strong>{town}</strong>" in section
    assert 'src="/static/assets/power-solar/mapa-centros-servicio-power-solar.png"' in section
    assert "powersolarpr.com" in section and "Confirma dirección y horario" in section
    image = client.get("/static/assets/power-solar/mapa-centros-servicio-power-solar.png")
    assert image.status_code == 200 and image.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_ia_system_cards_use_local_official_illustrations_and_ask_without_figures(client):
    page = client.get("/ia").text
    for name in SYSTEM:
        path = f"/static/assets/power-solar/sistema/{name}.png"
        assert f'src="{path}"' in page
        assert client.get(path).content[:8] == b"\x89PNG\r\n\x1a\n"
    prompts = re.findall(r'data-ia-prompt="([^"]+)"', page)
    assert len(prompts) >= 9
    # The /ia reply policy rejects figures; starters must not invite them.
    assert not any(re.search(r"\d|%|kWh|\bkW\b", prompt) for prompt in prompts)


def test_every_official_asset_has_a_recorded_source():
    sources = (ASSETS / "SOURCES.md").read_text(encoding="utf-8")
    files = [path.relative_to(ASSETS).as_posix() for path in ASSETS.rglob("*") if path.suffix in {".png", ".jpg"}]
    own = {"reigel-logo.png", "favicon-32.png", "favicon-180.png"}
    for name in files:
        if name in own:
            continue
        assert Path(name).name in sources, name
