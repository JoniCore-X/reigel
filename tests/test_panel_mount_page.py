"""Tesla Panel Mount Flat: idea simple fuera, detalle verificado dentro de los desplegables."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reigel.api import create_app

ROUTE = "/soluciones/tesla-panel-mount-flat"
ROOT = Path(__file__).resolve().parent.parent
FRAGMENT = ROOT / "frontend" / "pages" / "panel-mount-flat.html"
IMAGES = ROOT / "frontend" / "assets" / "power-solar" / "panel-mount"
PART_NUMBERS = (
    "1577562-00-X", "2291585-00-X", "2291586-00-X", "1577203-00-X", "1576449-00-X", "1577385-00-X",
    "1576606-00-X", "1576469-00-X", "2233066-00-X", "2133094-00-X", "2129978-10-X", "2129978-11-X",
    "2129978-12-X", "2129977-00-X", "1576999-00-X", "1578969-00-X", "1578119-00-X", "1578249-00-X",
    "1578389-00-X", "1879359-15-X", "1571739-00-X",
)


def visible_text(html):
    return re.sub(r"<[^>]+>", " ", html)


def outside_disclosures(html):
    return re.sub(r'<details class="pm-more".*?</details>\s*(?=<details class="pm-more"|</div>\s*</section>)', "", html, flags=re.S)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    return TestClient(create_app(tmp_path / "panel-mount.sqlite3"))


def test_route_renders_in_the_shell_and_marks_solutions_as_active(client):
    response = client.get(ROUTE)
    assert response.status_code == 200
    page = response.text
    assert page.count("<h1") == 1
    active = re.findall(r'<a [^>]*data-site-page="([^"]+)" aria-current="page"', page)
    assert active and set(active) == {"soluciones"}
    assert 'href="/contacto#evaluacion"' in page
    assert 'href="/ia?q=' in page
    assert ROUTE in client.get("/soluciones").text


def test_main_message_is_simple_and_free_of_technical_terms():
    fragment = FRAGMENT.read_text(encoding="utf-8")
    for phrase in ("La base que sostiene tus placas.", "Es para techos de madera casi planos.",
                   "Se fija a la madera de tu techo.", "Mantiene tus placas firmes en su lugar.",
                   "Une las placas y ordena los cables.", "¿Quieres saber si tu techo aplica?"):
        assert phrase in fragment
    outside = visible_text(outside_disclosures(fragment))
    assert "Ver las 18 piezas" not in outside
    assert not re.search(r"\bpsf\b|\bPa\b|\bUL\b|ASCE|TAS|módulo|arreglo|voladizo|tramo|puesta a tierra|\d{7}-", outside)
    assert not re.search(r"seguro|resistente|a prueba de|huracán|huracanes", outside, re.I)


def test_technical_figures_keep_their_conditions_inside_the_disclosure():
    fragment = FRAGMENT.read_text(encoding="utf-8")
    assert fragment.count('<details class="pm-more"') == 2
    assert '<details class="pm-more" open' not in fragment
    condition = "no incluye los límites de presión del módulo ni del material del techo"
    for value in ("85 psf", "75 psf"):
        row = re.search(rf'<div class="pm-spec"><dt>[^<]*</dt><dd><strong>[^<]*{value}.*?</div>', fragment, re.S).group(0)
        assert condition in row and "orientación horizontal" in row and "UL 2703" in row
    fire = re.search(r'<div class="pm-spec"><dt>[^<]*</dt><dd><strong>Clase A.*?</div>', fragment, re.S).group(0)
    assert "Tipo 1 o Tipo 2" in fire


def test_explorer_groups_all_components_with_native_details():
    fragment = FRAGMENT.read_text(encoding="utf-8")
    items = re.findall(r'<li class="pm-part".*?</li>', fragment, re.S)
    assert len(items) == 18
    assert all("<details" in item and "<summary>" in item for item in items)
    for number in PART_NUMBERS:
        assert fragment.count(number) == 1, number
    groups = re.findall(r'<section class="pm-group" data-group="(\w+)".*?</section>', fragment, re.S)
    assert groups == ["agarra", "sostiene", "conecta"]
    sizes = [len(re.findall(r'<li class="pm-part"', block))
             for block in re.findall(r'<section class="pm-group".*?</section>', fragment, re.S)]
    assert sizes == [5, 6, 7]


def test_images_are_local_sized_credited_and_logo_part_is_omitted(client):
    fragment = FRAGMENT.read_text(encoding="utf-8")
    assert "Imágenes: Tesla Panel Mount Flat Datasheet, © 2025 Tesla Inc." in fragment
    images = re.findall(r"<img [^>]+>", fragment)
    assert len(images) == 1 + 17 + 1 + 17  # portada, escena, final y explorador
    for tag in images:
        assert 'src="/static/assets/power-solar/panel-mount/' in tag and 'width="' in tag and 'height="' in tag
        assert re.search(r'alt="[^"]{8,}"', tag)
    assert sum('loading="lazy"' in tag for tag in images) == len(images) - 1
    for name in set(re.findall(r"panel-mount/([\w-]+\.webp)", fragment)):
        assert (IMAGES / name).is_file(), name
        assert client.get(f"/static/assets/power-solar/panel-mount/{name}").status_code == 200
    assert not (IMAGES / "mci.webp").exists()
    assert "Esquema ilustrativo" in fragment
    sources = (ROOT / "frontend" / "assets" / "power-solar" / "SOURCES.md").read_text(encoding="utf-8")
    assert "permiso de uso comercial sigue pendiente" in sources


def test_scroll_scene_lists_all_parts_in_order_with_honest_notice_and_skip_link():
    fragment = FRAGMENT.read_text(encoding="utf-8")
    scene = re.search(r'<section class="pm-scene".*?(?=<section class="pm-more-wrap")', fragment, re.S).group(0)
    assert re.findall(r'data-key="([\w-]+)"', scene) == [
        "base-foot", "sealing-ring", "lag-screw", "i-joist-adapter", "wood-screw",
        "mechanical-tubing", "cross-brace", "post-mount", "spanner-bar", "spanner-splice", "leveling-foot",
        "interlock", "hybrid-interlock", "ground-lockit", "dc-clip", "home-run-clip", "mci", "combiner",
    ]
    assert [f"{n:02d} / 18" for n in range(1, 19)] == re.findall(r'pm-seq-num">([^<]+)<', scene)
    explorer_order = re.findall(r'<li class="pm-part" data-part-key="([\w-]+)" data-number="(\d\d)"', fragment)
    assert [key for key, _ in explorer_order] == re.findall(r'data-key="([\w-]+)"', scene)
    assert [int(number) for _, number in explorer_order] == list(range(1, 19))
    for key in re.findall(r'data-key="([\w-]+)"', scene):
        item = re.search(rf'data-key="{key}">.*?</li>', scene, re.S).group(0)
        assert "Esquema ilustrativo" in item if key == "mci" else f"panel-mount/{key}.webp" in item
    assert scene.count("Solo si tu techo tiene viguetas I") == 2
    assert "Secuencia ilustrativa. No está a escala ni es una guía de instalación." in scene
    assert 'href="#pm-despues"' in scene and "Saltar la animación" in scene
    assert 'id="pm-despues"' in fragment and "Así queda el sistema." in scene


def test_hero_and_scene_text_follow_the_pdf():
    fragment = FRAGMENT.read_text(encoding="utf-8")
    hero = re.search(r'<section class="pm-hero".*?</section>', fragment, re.S).group(0)
    assert re.search(r"Agarra\.</span>\s*<span>Sostiene\.</span>\s*<span>Conecta\.", hero)
    outside = visible_text(outside_disclosures(fragment))
    assert not re.search(r"hasta \d+ cables", outside)
    assert "Roof Deck Adapter" in fragment
    assert "Fija el adaptador" not in fragment
    scene = re.search(r'<section class="pm-scene".*?(?=<section class="pm-more-wrap")', fragment, re.S).group(0)
    assert scene.count('class="pm-tier"') == 3 and "pm-tray" not in scene


def test_scene_only_reads_scroll_position():
    script = (ROOT / "frontend" / "js" / "panel-mount.js").read_text(encoding="utf-8")
    for forbidden in ("wheel", "touchstart", "touchmove", "preventDefault", "scrollTo("):
        assert forbidden not in script, forbidden
    assert "prefers-reduced-motion" in script


def test_fragment_respects_csp_and_avoids_forbidden_claims():
    fragment = FRAGMENT.read_text(encoding="utf-8")
    assert not re.findall(r"\son[a-z]+=", fragment)
    assert not re.search(r"<script(?![^>]*\bsrc=)", fragment)
    text = visible_text(fragment).lower()
    for claim in ("huracán", "huracanes", "a prueba de", "vida útil", "durabilidad", "mph", "km/h", "410"):
        assert claim not in text, claim


def test_assets_load_only_on_this_route(client):
    page = client.get(ROUTE).text
    assert "panel-mount.css" in page and "panel-mount.js" in page
    for path in ("/captacion", "/empresa", "/equipo", "/soluciones", "/proceso", "/contacto", "/preguntas", "/ia", "/chat", "/app"):
        other = client.get(path).text
        assert "panel-mount.css" not in other and "panel-mount.js" not in other, path
