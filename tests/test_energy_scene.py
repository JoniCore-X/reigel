"""Interactive energy scene in /soluciones: original, honest and isolated."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reigel.api import create_app

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "frontend" / "js" / "energy-scene.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "energy-scene.css").read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    return TestClient(create_app(tmp_path / "energy.db"))


def section(client):
    page = client.get("/soluciones").text
    return re.search(r'<section class="es-section".*?</section>', page, re.S).group(0)


def visible(markup):
    return re.sub(r"<[^>]+>", " ", re.sub(r"<defs>.*?</defs>", "", markup, flags=re.S))


def test_scene_is_labeled_as_a_simulation_without_figures_or_brands(client):
    markup = section(client)
    text = visible(markup)
    assert "Simulación educativa" in text and "No son datos de tu casa" in text
    assert not re.search(r"\d|%|\bkw|ahorr|tesla|powerwall|garant", text, re.I), text
    assert "<img" not in markup  # original drawing, not the reference screenshot


def test_every_scenario_is_honest_about_outages():
    for key in ("day:yes", "day:no", "night:yes", "night:no", "outage:yes", "outage:no"):
        assert f"'{key}'" in JS
    without = JS.split("'outage:no'")[1].split("},\n  };")[0]
    assert "se apagan por seguridad" in without and "home: 'off'" in without
    assert "solar: 'off', home: 'off', battery: 'off', grid: 'off'" in without
    assert "solo los equipos conectados al respaldo" in JS.split("'outage:yes'")[1]
    labels = " ".join(re.findall(r"'([^']*)'", JS.split("const SCENES")[1].split("const motion")[0]))
    assert not re.search(r"\d|\bkw|ahorr|garant", labels, re.I)


def test_no_new_dependency_or_network_access():
    assert not re.search(r"fetch\(|XMLHttpRequest|WebSocket|localStorage|https?://(?!www\.w3\.org)", JS)
    assert "url(http" not in CSS and "@import" not in CSS
    assert "prefers-reduced-motion" in JS and "prefers-reduced-motion" in CSS
    assert "IntersectionObserver" in JS and "document.hidden" in JS


def test_controls_are_real_and_only_appear_with_javascript(client):
    markup = section(client)
    assert "data-energy-controls hidden" in markup
    assert markup.count('<button type="button" data-energy-mode=') == 3
    assert 'type="checkbox" data-energy-battery checked' in markup
    assert 'role="status"' in markup and 'role="img"' in markup


def test_scene_only_lives_in_solutions_and_existing_routes_still_work(client):
    assert client.get("/static/js/energy-scene.js?v=8").status_code == 200
    assert client.get("/static/css/energy-scene.css?v=8").status_code == 200
    # Las secciones fundidas solo redirigen; la escena se comprueba donde vive.
    for path in ("/empresa", "/equipo", "/proceso", "/contacto", "/preguntas"):
        assert client.get(path, follow_redirects=False).status_code == 302, path
    assert client.get("/captacion").status_code == 200
    for path in ("/ia", "/chat", "/app"):
        response = client.get(path)
        assert response.status_code == 200 and "energy-scene" not in response.text, path
