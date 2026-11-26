"""Certificaciones de los equipos: lo que se publica sale de un documento con enlace,
y cada norma dice también lo que no significa."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reigel.api import create_app

ROUTE = "/soluciones/certificaciones"
ROOT = Path(__file__).resolve().parent.parent
FRAGMENT = ROOT / "frontend" / "pages" / "certificaciones.html"
# Lo que Team Caguas instala. Powerwall 2, Powerwall+ y Backup Gateway 2 están en los
# mismos documentos del fabricante y no se publican: no se instalan.
INSTALLED = ("Tesla Solar Panel", "Tesla Solar Inverter", "MCI-1", "MCI-2",
             "Powerwall 3", "Powerwall 3 Expansion", "Gateway 3", "Backup Switch")
NOT_INSTALLED = ("Powerwall 2", "Powerwall+", "Backup Gateway 2", "Tesla Remote Meter")
DOCUMENTS = (
    "E548861-20250725", "105368239CRT-003", "US23P05I.003", "105387461LAX-001",
    "104873297LAX-001", "104514208CRT-001", "105428445CRT-001", "105217933CRT-001",
    "104338849CRT-001", "104873297LAX-002", "US23U76C.006", "US23U76C.007",
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    return TestClient(create_app(tmp_path / "certificaciones.sqlite3"))


def page_text(html):
    return re.sub(r"<[^>]+>", " ", html)


def test_the_route_renders_in_the_shell_and_marks_solutions_as_active(client):
    response = client.get(ROUTE)
    assert response.status_code == 200
    page = response.text
    assert "Las certificaciones de los equipos." in page
    assert set(re.findall(r'<a [^>]*data-site-page="([^"]+)" aria-current="page"', page)) == {"soluciones"}


def test_every_document_is_listed_with_a_link_to_the_original(client):
    page = client.get(ROUTE).text
    for reference in DOCUMENTS:
        assert reference in page, reference
        assert f"ProductCertificationInformation/{reference}.pdf" in page, reference


def test_nothing_is_published_without_a_public_source():
    """Tesla publica el documento UL 3741 con una dirección de `energylibrary-stg`, un
    host de pruebas que no resuelve. El mismo documento sí está en el host público, y es
    esa la dirección que se publica: un enlace muerto no respalda nada."""
    fragment = FRAGMENT.read_text(encoding="utf-8")
    assert "energylibrary-stg" not in fragment
    links = re.findall(r'href="(https?://[^"]+)"', fragment)
    assert links, "la página se queda sin documentos"
    assert all(link.startswith("https://energylibrary.tesla.com/") for link in links), links


def test_only_the_equipment_team_caguas_installs_is_presented_as_its_own(client):
    page = page_text(client.get(ROUTE).text)
    for product in INSTALLED:
        assert product in page, product
    for product in NOT_INSTALLED:
        # Pueden mencionarse como «otros equipos», pero nunca con nombre propio:
        # publicar la certificación de algo que no se instala induce a error.
        assert product not in page, product


def test_each_standard_says_what_it_does_not_mean(client):
    page = client.get(ROUTE).text
    rows = re.findall(r"<tr>(.*?)</tr>", page, flags=re.S)
    norm_rows = [row for row in rows if 'data-label="Qué cubre"' in row]
    assert len(norm_rows) >= 10
    for row in norm_rows:
        assert 'data-label="Qué no significa"' in row, row[:120]


@pytest.mark.parametrize("promise", ["cuota", "financia", "%", "$"])
def test_the_page_carries_no_figure_and_no_commercial_term(client, promise):
    """Una certificación no es una promesa comercial, y la página no la convierte en una."""
    page = page_text(client.get(ROUTE).text).lower()
    section = page[page.index("las certificaciones de los equipos"):]
    assert promise not in section, promise
    assert not re.search(r"\d+\s*(?:%|por ciento)", section)


def test_savings_and_guarantees_are_only_denied_or_sent_to_the_proposal(client):
    """«Ahorro» y «garantía» sí aparecen, y nunca como promesa: o se niegan, o remiten
    a donde esa promesa sí vive, que es la propuesta por escrito."""
    page = page_text(client.get(ROUTE).text)
    sentences = [part.strip() for part in re.split(r"(?<=[.;])\s+", page) if part.strip()]
    claims = [part for part in sentences if re.search(r"ahorr|garant", part, re.I)]
    assert claims, "la página debería desmentir expresamente el ahorro y la garantía"
    for claim in claims:
        assert re.search(r"\b(?:no|ni|nunca)\b|propuesta|escrito", claim, re.I), claim


def test_the_page_says_a_certificate_does_not_cover_the_installation(client):
    page = page_text(client.get(ROUTE).text)
    assert "No certifica la instalación en tu propiedad." in page
    assert "El permiso y la inspección los hace la autoridad local." in page
    assert "No es una garantía." in page


def test_the_process_page_links_to_the_certifications(client):
    page = client.get("/proceso").text
    assert f'href="{ROUTE}"' in page
