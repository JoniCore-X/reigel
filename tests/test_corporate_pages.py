"""Public corporate routes keep content, metadata and integration boundaries separate."""

from html.parser import HTMLParser
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from reigel.api import create_app


PAGES = {
    "/captacion": "inicio",
    "/empresa": "empresa",
    "/equipo": "equipo",
    "/soluciones": "soluciones",
    "/proceso": "proceso",
    "/contacto": "contacto",
    "/preguntas": "preguntas",
}
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScbCm-67NFR1qFYLfD9oR-nMkCGsGionTB5iG9uR0JKWdZHMQ/viewform?embedded=true"


class PageDocument(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.tags = []
        self.headings = []
        self._heading = None
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "h1":
            self._heading = []

    def handle_data(self, data):
        if self._heading is not None:
            self._heading.append(data)

    def handle_endtag(self, tag):
        if tag == "h1" and self._heading is not None:
            self.headings.append(" ".join("".join(self._heading).split()))
            self._heading = None


@pytest.fixture
def corporate_app(tmp_path, monkeypatch):
    monkeypatch.setattr("reigel.api.load_environment", lambda: None)
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    return create_app(tmp_path / "corporate.sqlite3")


def test_corporate_routes_have_specific_server_rendered_content_and_shared_navigation(corporate_app):
    headings = set()
    with TestClient(corporate_app) as client:
        for path, page_key in PAGES.items():
            response = client.get(path)
            assert response.status_code == 200, path
            assert "{{page_title}}" not in response.text
            assert "{{page_description}}" not in response.text
            document = PageDocument(response.text)
            assert len(document.headings) == 1, path
            assert document.headings[0], path
            headings.add(document.headings[0])
            hrefs = {attrs.get("href") for tag, attrs in document.tags if tag == "a"}
            assert set(PAGES) <= hrefs, path
            assert "/app" in hrefs, path
            assert "/contacto#privacidad" in hrefs, path
            active = [attrs for tag, attrs in document.tags if tag == "a" and attrs.get("aria-current") == "page"]
            assert active, path
            assert all(link.get("data-site-page") == page_key for link in active), path
            assert all(link.get("href") == path for link in active), path
            ids = [attrs["id"] for _, attrs in document.tags if "id" in attrs]
            assert len(ids) == len(set(ids)), path
            assert {"main", "public-menu-toggle", "public-nav", "reigel-chat", "chat-form", "chat-book-form"} <= set(ids), path
            frames = [attrs for tag, attrs in document.tags if tag == "iframe"]
            if path == "/contacto":
                assert len(frames) == 1
                assert frames[0]["src"] == FORM_URL
                assert frames[0].get("scrolling") != "no"
                assert frames[0].get("title")
                assert {"evaluacion", "privacidad"} <= set(ids)
                assert FORM_URL.removesuffix("?embedded=true") in hrefs
            else:
                assert not frames, path
        assert len(headings) == len(PAGES)


def test_corporate_metadata_and_sitemap_use_each_public_route(corporate_app):
    origin = "https://powersolar.example"
    # Test-only store settings: no operator configuration or customer data is loaded.
    with corporate_app.state.store.connect() as db:
        db.execute("UPDATE settings SET value=? WHERE key='site_url'", (origin,))
    with TestClient(corporate_app) as client:
        for path in PAGES:
            response = client.get(path + "?utm_source=corporate-test")
            document = PageDocument(response.text)
            canonical = [attrs["href"] for tag, attrs in document.tags if tag == "link" and attrs.get("rel") == "canonical"]
            assert canonical == [origin + path]
            og_urls = [attrs.get("content") for tag, attrs in document.tags if tag == "meta" and attrs.get("property") == "og:url"]
            assert og_urls == [origin + path]
            assert response.headers["link"] == f'<{origin}{path}>; rel="canonical"'
            assert "x-robots-tag" not in response.headers
        sitemap = ElementTree.fromstring(client.get("/sitemap.xml").text)
        locations = [element.text for element in sitemap.findall("{*}url/{*}loc")]
        subpages = ["/soluciones/tesla-panel-mount-flat", "/soluciones/certificaciones"]
        assert set(locations) == {origin + path for path in [*PAGES, *subpages]}
        assert len(locations) == len(PAGES) + len(subpages)
        robots = client.get("/robots.txt").text
        assert all(f"Allow: {path}\n" in robots for path in PAGES)
        assert "Disallow: /$\n" in robots
        assert "Disallow: /app\n" in robots
        assert "Disallow: /api/\n" in robots
        assert "Disallow: /webhooks/\n" in robots
        assert client.get("/").headers["x-robots-tag"] == "noindex, nofollow"
        assert "link" not in client.get("/app").headers


def test_html_pages_are_revalidated_so_updates_are_never_hidden_by_cache(corporate_app):
    with TestClient(corporate_app) as client:
        for path in [*PAGES, "/chat"]:
            assert client.get(path).headers["cache-control"] == "no-cache", path
        for path in ("/", "/ia", "/app"):
            assert client.get(path).headers["cache-control"] == "no-store", path


def test_local_corporate_pages_are_not_advertised_to_search_engines(corporate_app):
    with TestClient(corporate_app) as client:
        for path in PAGES:
            response = client.get(path)
            assert response.headers["x-robots-tag"] == "noindex, nofollow"
            assert "link" not in response.headers
            assert not any(tag == "link" and attrs.get("rel") == "canonical" for tag, attrs in PageDocument(response.text).tags)
        sitemap = ElementTree.fromstring(client.get("/sitemap.xml").text)
        assert not sitemap.findall("{*}url")
        assert client.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"


def test_corporate_routes_cannot_select_other_pages_or_files_through_parameters(corporate_app):
    with TestClient(corporate_app) as client:
        company = client.get("/empresa")
        for query in ("?page_path=/contacto", "?page=../../index.html", "?page_path=/app&fragment=contacto"):
            response = client.get("/empresa" + query)
            assert response.status_code == 200
            assert response.text == company.text
        for path in ("/corporate/index.html", "/empresa/contacto", "/pagina-no-existente"):
            assert client.get(path).status_code == 404
        assert client.get("/api/auth/me").status_code == 401


def test_team_page_publishes_only_the_verified_contact_card(corporate_app):
    with TestClient(corporate_app) as client:
        page = client.get("/equipo")
        assert page.status_code == 200
        assert "Joniel L. Martínez Rosario" in page.text
        assert "Consultor Profesional" in page.text
        assert "Con capacitación en sistemas solares" in page.text
        assert 'href="tel:+19392104722"' in page.text
        assert "+1 (939) 210-4722" in page.text
        assert 'href="mailto:joniel.powersolar@gmail.com"' in page.text
        assert 'href="https://www.powersolarpr.com"' in page.text
        assert 'target="_blank" rel="noopener noreferrer"' in page.text
        for category in ("Solar para tu hogar", "Baterías para apartamentos", "Soluciones comerciales"):
            assert category in page.text
        for image in ("residencia-paneles-puerto-rico.jpg", "respaldo-apartamento.jpg",
                      "paneles-solares-edificio-comercial-puerto-rico.jpg"):
            assert f'/static/assets/power-solar/{image}' in page.text
            assert client.get(f"/static/assets/power-solar/{image}").status_code == 200
        assert page.text.count("data-chat-prefill=") == 3
        assert "Categorías y nombres publicados por Power Solar" in page.text
        for unverified in ("2018", "1,400", "80,000", "150,000", "24/7", "gratis"):
            assert unverified not in page.text


def test_subscription_plans_are_not_part_of_the_public_site(corporate_app):
    """Los planes de R.E.I.G.E.L. son para el propietario (/app); los clientes no los ven."""
    with TestClient(corporate_app) as client:
        assert client.get("/precios", headers={"accept": "text/html"}).status_code == 404
        for path in PAGES:
            text = client.get(path).text
            assert 'href="/precios"' not in text and "pricing.css" not in text, path


def test_page_loader_promotes_the_solar_sun_with_local_assets(corporate_app):
    with TestClient(corporate_app) as client:
        for path in ("/captacion", "/chat", "/app"):
            page = client.get(path)
            assert page.status_code == 200, path
            document = PageDocument(page.text)
            loader = next(attrs for tag, attrs in document.tags
                          if tag == "div" and attrs.get("id") == "ps-loader")
            assert loader.get("popover") == "manual", path
            assert "hidden" in loader, path
            assert loader.get("role") == "status", path
            assert loader.get("aria-live") == "polite", path
            assert page.text.count('class="rl-glyph ') == 12, path
            assert "/static/css/reigel-loader.css?v=5" in page.text, path
            assert page.text.index("/static/js/reigel-loader.js?v=6") < page.text.index("/static/js/site-loader.js?v=8"), path
            assert "Cargando Power Solar" in page.text, path
            assert 'class="ps-error"' in page.text, path
            assert 'role="alert"' in page.text, path
            assert "Reintentar" in page.text and "Continuar al sitio" in page.text, path
            assert 'class="ps-retry"' in page.text, path
            assert 'class="ps-continue"' in page.text, path
            assert "/static/css/site-loader.css?v=10" in page.text, path
            assert "/static/js/site-loader.js?v=8" in page.text, path
            scripts = [attrs for tag, attrs in document.tags if tag == "script"]
            assert all(attrs.get("src") for attrs in scripts), path

        css = client.get("/static/css/site-loader.css?v=10")
        assert css.status_code == 200
        for token in ("--rl-scrim", "backdrop-filter", "ps-error", "ps-failed",
                      ":popover-open", "prefers-reduced-motion", "forced-colors"):
            assert token in css.text, token
        mark = client.get("/static/css/reigel-loader.css?v=5")
        assert mark.status_code == 200
        for token in ("rl-glyph", "rl-line", "prefers-reduced-motion", "forced-colors"):
            assert token in mark.text, token
        engine = client.get("/static/js/reigel-loader.js?v=6")
        assert engine.status_code == 200
        for token in ("drive", "glyph.animate", "prefers-reduced-motion", "effectiveType", "document.hidden"):
            assert token in engine.text, token

        script = client.get("/static/js/site-loader.js?v=8")
        assert script.status_code == 200
        for token in ("showPopover", "hidePopover", "ps-loader-seen", "MIN_FIRST", "Escape",
                      "SLOW_MS", "FAILURES_ALLOWED", "navigator.onLine", "location.reload",
                      "ps-error-text", "pageProgress"):
            assert token in script.text, token



def test_unknown_public_paths_render_the_branded_not_found_page(corporate_app):
    browser = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    with TestClient(corporate_app) as client:
        page = client.get("/ruta-que-no-existe", headers=browser)
        assert page.status_code == 404
        assert page.headers["content-type"].startswith("text/html")
        assert page.headers["x-robots-tag"] == "noindex, nofollow"
        assert page.headers["cache-control"] == "no-store"
        assert "ruta-que-no-existe" not in page.text
        document = PageDocument(page.text)
        assert len(document.headings) == 1
        assert "no está aquí" in document.headings[0]
        assert "Página no encontrada | Power Solar · Team Caguas" in page.text
        assert not [attrs for tag, attrs in document.tags if attrs.get("aria-current") == "page"]
        assert not [attrs for tag, attrs in document.tags if attrs.get("rel") == "canonical"]
        hrefs = {attrs.get("href") for tag, attrs in document.tags if tag == "a"}
        assert {"/captacion", "/equipo", "/soluciones", "/proceso", "/preguntas", "/contacto"} <= hrefs
        assert "/precios" not in hrefs
        assert {"main", "reigel-chat", "ps-loader"} <= {attrs["id"] for _, attrs in document.tags if "id" in attrs}

        with corporate_app.state.store.connect() as db:
            db.execute("UPDATE settings SET value=? WHERE key='site_url'", ("https://powersolar.example",))
        published = client.get("/ruta-que-no-existe", headers=browser)
        assert published.status_code == 404
        assert published.headers["x-robots-tag"] == "noindex, nofollow"
        assert "rel=\"canonical\"" not in published.text


def test_unknown_programmatic_paths_keep_the_json_error_contract(corporate_app):
    with TestClient(corporate_app) as client:
        api = client.get("/api/ruta-que-no-existe", headers={"accept": "text/html"})
        assert api.status_code == 404
        assert api.headers["content-type"].startswith("application/json")
        assert api.json() == {"detail": "Not Found"}
        webhook = client.get("/webhooks/ruta-que-no-existe", headers={"accept": "text/html"})
        assert webhook.headers["content-type"].startswith("application/json")
        other = client.get("/ruta-que-no-existe")
        assert other.headers["content-type"].startswith("application/json")
        assert other.json() == {"detail": "Not Found"}
        missing_asset = client.get("/static/assets/no-existe.png")
        assert missing_asset.status_code == 404
        assert missing_asset.headers["content-type"].startswith("application/json")


def test_branded_icon_is_served_locally_and_linked_from_every_shell(corporate_app):
    icons = {
        "/static/assets/power-solar/favicon.svg",
        "/static/assets/power-solar/favicon-32.png",
        "/static/assets/power-solar/favicon-180.png",
    }
    with TestClient(corporate_app) as client:
        for path in ("/captacion", "/", "/app"):
            page = client.get(path)
            document = PageDocument(page.text)
            links = [(attrs.get("rel"), attrs.get("href")) for tag, attrs in document.tags
                     if tag == "link" and attrs.get("rel") in {"icon", "apple-touch-icon"}]
            assert {href for _, href in links} == icons, path
            assert {rel for rel, _ in links} == {"icon", "apple-touch-icon"}, path
        for icon in icons:
            response = client.get(icon)
            assert response.status_code == 200, icon
            assert response.content
        shortcut = client.get("/favicon.ico")
        assert shortcut.status_code == 200
        assert shortcut.headers["content-type"] == "image/png"
        assert "max-age=86400" in shortcut.headers["cache-control"]
