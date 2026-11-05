"""Public metadata is derived from the configured origin, never an invented domain."""

from html import escape
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.responses import HTMLResponse, PlainTextResponse, Response

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def public_origin(store):
    value = store.settings().get("site_url", "").rstrip("/")
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or host in {"localhost", "testserver"}:
        return ""
    try:
        if not ip_address(host).is_global:
            return ""
    except ValueError:
        if "." not in host or host.endswith((".local", ".localhost", ".internal")):
            return ""
    return value if not parsed.query and not parsed.fragment and parsed.path in {"", "/"} else ""


def landing_response(store):
    content = (FRONTEND / "landing.html").read_text(encoding="utf-8")
    origin = public_origin(store)
    headers = {}
    if origin:
        metadata = (f'<link rel="canonical" href="{escape(origin, quote=True)}/">\n'
                    f'<meta property="og:url" content="{escape(origin, quote=True)}/">')
        content = content.replace("</head>", metadata + "\n</head>")
        headers["Link"] = f'<{origin}/>; rel="canonical"'
    else:
        headers["X-Robots-Tag"] = "noindex, nofollow"
    return HTMLResponse(content, headers=headers)


def register_routes(app):
    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        origin = public_origin(app.state.store)
        text = "User-agent: *\nDisallow: /\n"
        if origin:
            text = ("User-agent: *\nAllow: /\nDisallow: /app\nDisallow: /api/\n"
                    f"Disallow: /webhooks/\nSitemap: {origin}/sitemap.xml\n")
        return PlainTextResponse(text)

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap():
        origin = public_origin(app.state.store)
        body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        if origin:
            body += f"<url><loc>{escape(origin)}/</loc></url>"
        body += "</urlset>"
        return Response(body, media_type="application/xml")
