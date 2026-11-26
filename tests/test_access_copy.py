"""Texts that describe how team access is managed are served only to a signed-in
session, by role; the public static files and pages carry none of them.
Synthetic example.com accounts and a temporary database only."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reigel import access_copy
from reigel.api import create_app
from team_auth import login

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "Prueba-Textos-Acceso-2026!"
OWNER = "duena.powersolar@example.com"
ADMIN = "lider.powersolar@example.com"
ADVISOR = "ana.powersolar@example.com"
COPY = "/api/team-access/copy"
# Phrases of the access policy that must never be readable without a session.
MARKERS = (
    "Correos autorizados", "correo autorizado", "Autorizar", "REGLA «POWER SOLAR»", "regla «Power Solar»", "nombre.powersolar@",
    "REIGEL_TEAM_ALLOWED_EMAILS", "SOLO PROPIETARIO", "Solo estos correos", "emite códigos", "solo el propietario",
    "se obtienen en el servidor", "en persona", "anula el anterior", "deja de servir", "sus sesiones", "tus otras sesiones",
    "no se puede desactivar", "No los ven los administradores", "no ve la suscripción", "primer registro", "reemplaza su autenticador",
)


def static_files():
    frontend = ROOT / "frontend"
    return sorted([*frontend.rglob("*.html"), *(frontend / "js").glob("*.js"), *(frontend / "css").glob("*.css")])


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("REIGEL_ENV", "local")
    monkeypatch.delenv("SITE_URL", raising=False)
    app = create_app(tmp_path / "access-copy.db")
    store = app.state.store
    owner = store.create_user({"name": "Dueña", "email": OWNER, "password": PASSWORD, "role": "admin"}, bootstrap=True)
    store.allow_team_email(ADMIN, owner)
    store.allow_team_email(ADVISOR, owner)
    store.create_user({"name": "Líder", "email": ADMIN, "password": PASSWORD, "role": "admin"}, owner)
    store.create_user({"name": "Ana", "email": ADVISOR, "password": PASSWORD}, owner)
    return app


def signed_in(app, email):
    browser = TestClient(app, base_url="http://localhost")
    assert login(browser, email, PASSWORD).status_code == 200
    return browser


def test_copy_needs_a_full_team_session(world):
    anonymous = TestClient(world, base_url="http://localhost")
    response = anonymous.get(COPY)
    assert response.status_code == 401 and "copy" not in response.json()
    assert not any(marker in response.text for marker in MARKERS)
    # A correct password alone (no authenticator code yet) is not a session either.
    assert anonymous.post("/api/auth/login", json={"email": OWNER, "password": PASSWORD}).json()["mfa_required"] is True
    assert anonymous.get(COPY).status_code == 401
    for method in ("post", "put", "delete"):
        assert getattr(anonymous, method)(COPY).status_code in {401, 403, 405}


def test_each_role_receives_only_its_own_texts(world):
    owner = signed_in(world, OWNER).get(COPY)
    assert owner.status_code == 200 and owner.headers["cache-control"] == "no-store"
    assert owner.json()["copy"] == {"member": access_copy.MEMBER, "admin": access_copy.OWNER_ADMIN, "owner": access_copy.OWNER}

    admin = signed_in(world, ADMIN).get(COPY)
    assert admin.json()["copy"] == {"member": access_copy.MEMBER, "admin": access_copy.ADMIN}
    owner_only = set(access_copy.strings(access_copy.OWNER)) | {access_copy.OWNER_ADMIN["grant_scope"]}
    assert not any(text in admin.text for text in owner_only)
    assert "propietario" not in admin.text.lower() and "powersolar" not in admin.text.lower()

    advisor = signed_in(world, ADVISOR).get(COPY)
    assert advisor.status_code == 200 and advisor.json()["copy"] == {"member": access_copy.MEMBER}
    restricted = owner_only | set(access_copy.strings(access_copy.ADMIN))
    assert not any(text in advisor.json()["copy"]["member"].values() for text in restricted)
    assert not any(text in advisor.text for text in restricted)


def test_copy_for_ignores_unknown_or_missing_roles():
    assert access_copy.copy_for(None) == {"member": access_copy.MEMBER}
    assert access_copy.copy_for({"role": "advisor", "is_owner": True}) == {"member": access_copy.MEMBER}


def test_static_files_do_not_describe_the_access_policy():
    files = static_files()
    assert len(files) > 30
    served = [text for block in (access_copy.MEMBER, access_copy.OWNER_ADMIN, access_copy.ADMIN, access_copy.OWNER)
              for text in access_copy.strings(block) if len(text) >= 16]
    assert len(served) > 40
    for path in files:
        source = path.read_text(encoding="utf-8")
        found = [text for text in (*MARKERS, *served) if text in source]
        assert not found, f"{path.relative_to(ROOT)}: {found}"


def test_public_pages_and_scripts_are_served_without_those_texts(world):
    anonymous = TestClient(world, base_url="http://localhost")
    entrance, access = anonymous.get("/app"), anonymous.get("/app/acceso")
    assert 'src="/static/js/app.js?v=12"' in entrance.text and "/static/css/operations.css?v=7" in entrance.text
    assert 'src="/static/js/team-access.js?v=8"' in access.text and "/static/css/team-auth.css?v=2" in access.text
    assert "Si no tienes un código, pídelo a tu administrador." in access.text
    assert "Si no tienes un código, pídelo a tu administrador." in entrance.text
    # The flow and its fields stay as they were.
    for field in ('id="grant-email" name="email" type="email" autocomplete="username"', 'id="grant-password" name="password" type="password"',
                  'id="grant-setup-code" name="grant_code" type="text" autocomplete="off"', 'id="grant-purpose" name="purpose"',
                  'id="totp-note"', 'id="grant-scope"', 'id="policy-section"'):
        assert field in access.text, field
    pages = [entrance, access, *(anonymous.get(path) for path in (
        "/static/js/app.js", "/static/js/team-access.js", "/static/js/operations.js", "/static/js/learning.js",
        "/static/index.html", "/static/team-access.html", "/static/css/operations.css", "/static/css/team-auth.css"))]
    for page in pages:
        assert page.status_code == 200, page.url
        assert not [marker for marker in MARKERS if marker in page.text], page.url


def test_the_scripts_take_the_texts_from_the_authenticated_endpoint():
    app_js = (ROOT / "frontend/js/app.js").read_text(encoding="utf-8")
    access_js = (ROOT / "frontend/js/team-access.js").read_text(encoding="utf-8")
    assert "api('/api/team-access/copy')" in app_js and "api('/api/team-access/copy')" in access_js
    # Rendered as text: escaped in /app templates, textContent in /app/acceso.
    assert "${esc(text('panel_help'))}" in app_js and "${esc(step)}" in app_js
    assert "$(id).textContent = text;" in access_js and "innerHTML" not in access_js
    # Ids and hooks the panel behaviour depends on are unchanged.
    for hook in ('id="team-access-panel"', 'id="allow-form"', 'id="name-rule-toggle"', 'id="name-rule-error"', "data-remove-email",
                 'id="remove-email-form"', 'id="grant-code-form"', 'class="grant-steps"', 'id="offboard-form"'):
        assert hook in app_js, hook
