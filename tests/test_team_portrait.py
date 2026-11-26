"""El retrato del consultor en `/equipo`.

Va encima del monograma, no en su lugar: si el archivo falta, el círculo sigue
mostrando «JM». Y se sirve desde el propio sitio, nunca desde un tercero: la política
de contenido de la aplicación solo admite imágenes del mismo origen.
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reigel.api import create_app

ROOT = Path(__file__).resolve().parent.parent
PORTRAIT = ROOT / "frontend" / "assets" / "power-solar" / "joniel-martinez.jpg"
RUTA = "/static/assets/power-solar/joniel-martinez.jpg"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    return TestClient(create_app(tmp_path / "retrato.sqlite3"))


def test_the_portrait_is_served_from_the_site_itself(client):
    response = client.get(RUTA)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


def test_the_monogram_stays_as_the_fallback(client):
    """Si la imagen no carga, el círculo no se queda vacío."""
    page = client.get("/equipo").text
    monogram = re.search(r'<div class="team-monogram"[^>]*>(.*?)</div>', page, re.S)
    assert monogram, "no se encontró el círculo"
    assert "JM" in monogram.group(1)
    assert RUTA in monogram.group(1)


def test_the_portrait_is_decorative_because_the_name_is_next_to_it(client):
    """El titular ya dice el nombre completo; repetirlo lo haría sonar dos veces."""
    page = client.get("/equipo").text
    tag = re.search(r'<img class="team-portrait"[^>]*>', page)
    assert tag, "no se encontró la imagen"
    assert 'alt=""' in tag.group(0)
    assert "Joniel L. Martínez Rosario" in page


def test_the_image_is_small_enough_to_not_cost_a_visit(client):
    assert PORTRAIT.exists()
    assert PORTRAIT.stat().st_size < 60 * 1024, PORTRAIT.stat().st_size


def test_no_third_party_image_or_frame_was_introduced(client):
    """La política de contenido no admite imágenes ni marcos de fuera, y la página
    tampoco los pide: el retrato se sirve desde el sitio."""
    page = client.get("/equipo").text
    assert "facebook.com" not in page and "<iframe" not in page
    policy = client.get("/equipo").headers["content-security-policy"]
    assert "img-src 'self' data:" in policy
    assert "frame-src 'self'" in policy
