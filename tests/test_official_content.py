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


def test_solutions_page_walks_through_the_battery_system_with_official_illustrations(client):
    page = client.get("/soluciones").text
    section = re.search(r'<section[^>]*id="como-funciona".*?</section>', page, re.S).group(0)
    steps = re.findall(r'<li class="corp-system-step">.*?</li>', section, re.S)
    assert len(steps) == len(SYSTEM)
    for name, step in zip(SYSTEM, steps):
        assert f'src="/static/assets/power-solar/sistema/{name}.png"' in step
    text = re.sub(r"<[^>]+>", " ", section)
    text = text.replace("19 de noviembre de 2026", "")
    # Own explanatory text: no figures, prices or savings promises.
    assert not re.search(r"\d|%|\$|ahorr|garant|gratis", text, re.I)
    assert "powersolarpr.com/placas-solares-para-casas" in section
    assert "data-open-chat" in section and "data-chat-prefill" in section


def test_company_page_attributes_published_facts_without_customer_or_staff_figures(client):
    page = client.get("/empresa").text
    company = re.search(r'<section class="corp-company".*?</section>', page, re.S).group(0)
    projects = re.search(r'<section[^>]*corp-projects.*?</section>', page, re.S).group(0)
    for fact in ("puertorriqueña", "2018", "Power Group", "Hogar", "Apartamentos", "Comercial", "Techos"):
        assert fact in company, fact
    for partner in ("Tesla", "UNIRAC", "EcoFlow"):
        assert f"<strong>{partner}</strong>" in company, partner
    assert "Canadian" not in page
    assert "<strong>Tesla</strong><span>Placas solares, inversores y baterías Powerwall" in company
    assert "powersolarpr.com/conoce-a-power-solar" in company
    assert "no es un sitio oficial" in company
    for section in (company, projects):
        text = re.sub(r"<[^>]+>", " ", section)
        text = re.sub(r"\b(2018|19|21) de noviembre de 2026\b|\b2018\b", "", text)
        assert not re.search(r"\d|%|\$|ahorr|financ", text, re.I), text
    assert projects.count("<li>") == 23
    assert 'src="/static/assets/power-solar/mapa-proyectos-power-solar.png"' in projects


def test_discontinued_panel_brand_is_absent_from_every_public_and_private_surface():
    """Canadian Solar, Enphase y Fortress Power ya no se ofrecen (noviembre de 2026): los equipos son Tesla."""
    roots = [ROOT / "frontend", ROOT / "reigel"]
    offenders = [
        str(path.relative_to(ROOT))
        for base in roots
        for path in base.rglob("*")
        if path.suffix in {".html", ".js", ".css", ".py", ".json", ".md", ".txt"}
        and any(brand in path.read_text(encoding="utf-8", errors="ignore").lower() for brand in ("canadian", "enphase", "fortress"))
    ]
    assert offenders == []


@pytest.mark.parametrize("path", ["/captacion", "/app", "/ia", "/chat"])
def test_solar_theme_is_the_last_stylesheet_on_every_surface(client, path):
    page = client.get(path).text
    sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)"', page)
    assert sheets and sheets[-1].startswith("/static/css/solar-theme.css"), sheets
    theme = client.get(sheets[-1])
    assert theme.status_code == 200
    # Paleta pedida por el titular; los colores claros no se usan como color de texto.
    for color in ("#ffc100", "#ffdd02", "#68a9f4", "#3785ea", "#2266de", "#cbf3f0", "#ffbf69", "#2ec4b6", "#ff9f1c"):
        assert color in theme.text.lower(), color
    assert not re.search(r"(?<![-\w])color:\s*var\(--sol-(?:gold|sun|sky|mint|peach|orange|teal)\)", theme.text)
