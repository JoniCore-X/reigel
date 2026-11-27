"""Allow/deny decisions of scripts/public_gate.py. No network, no app."""
import importlib.util
from pathlib import Path

import pytest

from reigel.seo import PUBLIC_PAGES

SPEC = importlib.util.spec_from_file_location("public_gate", Path(__file__).resolve().parents[1] / "scripts" / "public_gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
CID = "0123456789abcdef0123456789abcdef"


def test_gate_pages_match_the_app_public_pages():
    assert gate.PUBLIC_PAGES == frozenset(PUBLIC_PAGES)


@pytest.mark.parametrize("method,target", [
    ("GET", "/"), ("GET", "/ia"), ("GET", "/ia?q=%C2%BFhola%3F"), ("GET", "/captacion"),
    ("GET", "/soluciones/tesla-panel-mount-flat"), ("GET", "/robots.txt"), ("GET", "/sitemap.xml"),
    ("GET", "/favicon.ico"), ("GET", "/static/css/ia.css?v=23"), ("HEAD", "/static/js/ia.js"),
    ("GET", "/static/assets/power-solar/panel-mount/base-foot.webp"),
    ("GET", "/api/ia/bootstrap"), ("GET", "/api/ia/status"), ("GET", "/api/ia/conversations?q=techo"),
    ("GET", f"/api/ia/suggestions?conversation_id={CID}&seen=a%2Cb"), ("GET", f"/api/ia/conversations/{CID}"),
    ("POST", "/api/ia/conversations"), ("POST", f"/api/ia/conversations/{CID}/messages"),
    ("PATCH", f"/api/ia/conversations/{CID}"), ("DELETE", f"/api/ia/conversations/{CID}"),
    ("POST", f"/api/ia/conversations/{CID}/attachments"), ("DELETE", f"/api/ia/conversations/{CID}/attachments/{CID}"),
])
def test_allows_public_pages_and_ia(method, target):
    assert gate.decide(method, target)


@pytest.mark.parametrize("method,target", [
    ("GET", "/app"), ("GET", "/app/"), ("GET", "/app/acceso"), ("GET", "/APP"), ("GET", "/cuenta"), ("GET", "/chat"),
    ("GET", "/docs"), ("GET", "/openapi.json"), ("GET", "/redoc"), ("GET", "/health"),
    ("GET", "/static/index.html"), ("GET", "/static/team-access.html"), ("GET", "/static/js/app.js"),
    ("GET", "/static/js/operations.js"), ("GET", "/static/css/operations.css"),
    ("GET", "/static/assets/power-solar/SOURCES.md"), ("GET", "/api/public/config"), ("GET", "/api/public/chat"),
    ("POST", "/api/public/chat"), ("POST", "/api/public/chat/book"), ("POST", "/api/public/chat/human"),
    ("POST", "/api/auth/login"), ("POST", "/api/knowledge/refresh"), ("POST", "/webhooks/meta"),
    ("POST", f"/api/ia/conversations/{CID}/regenerate"), ("POST", "/api/ia/conversations?x=1"),
    ("PUT", "/api/team-identity/policy"), ("POST", "/api/team-identity/totp/login"), ("POST", "/api/team-identity/totp/enroll"),
    ("POST", "/api/team-identity/totp/enroll/confirm"), ("GET", "/api/team-identity/me"), ("GET", "/api/team-access"), ("GET", "/api/team-access/copy"),
    ("HEAD", "/api/team-access/copy"), ("GET", "/static/js/team-access.js"),
    ("POST", "/api/team-access/emails"), ("POST", "/api/team-access/emails/remove"), ("PUT", "/api/team-access/name-rule"),
    ("GET", "/api/team"), ("POST", "/api/team"), ("OPTIONS", "/ia"), ("HEAD", "/captacion"), ("get", "/ia"),
    ("GET", "/%61pp"), ("GET", "/static/js%2fapp.js"), ("GET", "/static/../reigel/api.py"),
    ("GET", "/static/js/./ia.js"), ("GET", "//app"), ("GET", "/static//js/ia.js"), ("GET", "/ia\\..\\app"),
    ("GET", "/captacion/"), ("GET", "/captacion;x"), ("GET", "/ia#x"), ("GET", "http://127.0.0.1:8878/app"),
    ("GET", "*"), ("GET", "/ia?q=<script>"), ("GET", "/api/ia/conversations/ABC"),
    ("GET", "/api/ia/conversations/../../leads"), ("GET", "/" + "a" * 5000),
    ("GET", f"/api/ia/conversations/{CID}/attachments"), ("PUT", f"/api/ia/conversations/{CID}/attachments"),
    ("POST", f"/api/ia/conversations/{CID}/attachments?x=1"), ("POST", f"/api/ia/conversations/{CID}/attachments/"),
    ("POST", f"/api/ia/conversations/{CID}/attachments/{CID}"), ("POST", "/api/ia/conversations/ABC/attachments"),
    ("GET", f"/api/ia/conversations/{CID}/attachments/{CID}"), ("DELETE", f"/api/ia/conversations/{CID}/attachments/x"),
    ("PATCH", f"/api/ia/conversations/{CID}/attachments/{CID}"),
])
def test_denies_private_routes_and_path_tricks(method, target):
    assert not gate.decide(method, target)


def test_only_the_ia_visitor_cookie_is_forwarded():
    assert gate.filter_cookies("powersolar_session=t; reigel_ia=v; reigel_webchat=w") == "reigel_ia=v"
    assert gate.filter_cookies("powersolar_session=t") == ""


def test_client_address_trusts_the_tunnel_only_from_loopback():
    assert gate.client_address("127.0.0.1", "1.2.3.4, 203.0.113.9") == "203.0.113.9"
    assert gate.client_address("198.51.100.7", "203.0.113.9") == "198.51.100.7"
    assert gate.client_address("127.0.0.1", "not-an-ip") == "127.0.0.1"


def test_body_cap_is_the_visitor_file_limit_only_for_attachments():
    from reigel.documents import VISITOR
    assert gate.ATTACHMENT_MAX_BODY == VISITOR.max_bytes == 3 * 1024 * 1024
    assert gate.body_limit("POST", f"/api/ia/conversations/{CID}/attachments", gate.MAX_BODY) == VISITOR.max_bytes
    assert gate.body_limit("POST", f"/api/ia/conversations/{CID}/messages", gate.MAX_BODY) == gate.MAX_BODY
    assert gate.body_limit("POST", f"/api/ia/conversations/{CID}/attachments?x=1", gate.MAX_BODY) == gate.MAX_BODY
    assert gate.body_limit("DELETE", f"/api/ia/conversations/{CID}/attachments/{CID}", gate.MAX_BODY) == gate.MAX_BODY

def test_every_asset_the_public_shell_pide_pasa_por_la_puerta():
    """La puerta nombra una a una las hojas, los scripts y lo vendorizado que deja
    pasar. Añadir un recurso a `landing.html` y olvidarlo aquí no rompe nada en local
    —ahí no hay puerta— y en la demostración publicada da 404 en silencio: la página
    carga pero sin escena, sin tipografía y sin estilos. Pasó el 27 de noviembre de
    2026 con `solar-hero`, `display-type`, `scroll-cinema`, `solar-hero-3d`, Three.js
    y la fuente."""
    import re

    shell = (Path(__file__).resolve().parents[1] / "frontend" / "landing.html").read_text(encoding="utf-8")
    pedidos = set(re.findall(r'(?:href|src)="(/static/[^"?]+)', shell))
    assert pedidos, "el shell tiene que pedir algo"
    bloqueados = [ruta for ruta in sorted(pedidos) if not gate.decide("GET", ruta)]
    assert not bloqueados, f"la puerta bloquea recursos que la portada pide: {bloqueados}"
