"""Public metadata is derived from the configured origin, never an invented domain."""

from html import escape
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
FAVICON = FRONTEND / "assets" / "power-solar" / "favicon-32.png"
NOT_FOUND = ("Página no encontrada | Power Solar · Team Caguas",
             "La dirección que buscas no está disponible. Vuelve al inicio o continúa por las secciones del sitio.")

# Routes and fragments are a closed set. Request parameters never select files.
PUBLIC_PAGES = {
    "/captacion": ("inicio", "Power Solar | Team Caguas", "Conoce a Power Solar · Team Caguas, explora opciones de energía para tu hogar en Puerto Rico y cómo solicitar orientación."),
    "/empresa": ("empresa", "Empresa | Power Solar · Team Caguas", "Conoce el enfoque de orientación y atención de Power Solar · Team Caguas para hogares de Puerto Rico."),
    "/equipo": ("equipo", "Equipo | Power Solar · Team Caguas", "Conoce a Team Caguas, su forma de orientar y cómo coordinar una evaluación para tu hogar o negocio en Puerto Rico."),
    "/soluciones": ("soluciones", "Soluciones | Power Solar · Team Caguas", "Información para evaluar energía solar, respaldo y consumo de tu hogar con Power Solar · Team Caguas."),
    "/proceso": ("proceso", "Evaluación | Power Solar · Team Caguas", "Conoce el proceso de orientación, evaluación y revisión de una propuesta de energía para tu hogar."),
    "/contacto": ("contacto", "Contacto | Power Solar · Team Caguas", "Comparte tu interés mediante el formulario de Power Solar o conversa con R.E.I.G.E.L. para coordinar una evaluación."),
    "/soluciones/tesla-panel-mount-flat": ("panel-mount-flat", "Tesla Panel Mount Flat | Power Solar · Team Caguas", "Cómo funciona esta estructura para techos de madera de baja pendiente, sus piezas, normas y condiciones. Requiere evaluación estructural."),
    "/preguntas": ("preguntas", "Preguntas frecuentes | Power Solar · Team Caguas", "Respuestas sobre evaluación, consumo, respaldo, contacto y condiciones de una propuesta de energía solar."),
}
NAV_PARENT = {"panel-mount-flat": "soluciones"}  # Subpáginas que marcan su sección en el menú.
CONTENT_START = "<!--corporate:content:start-->"
CONTENT_END = "<!--corporate:content:end-->"


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


def render_shell(store, page_key, title, description, *, status=200, canonical_path=None):
    content = (FRONTEND / "landing.html").read_text(encoding="utf-8")
    if content.count(CONTENT_START) != 1 or content.count(CONTENT_END) != 1:
        raise RuntimeError("El shell corporativo necesita un único bloque de contenido.")
    before, _, remainder = content.partition(CONTENT_START)
    home_content, _, after = remainder.partition(CONTENT_END)
    page_content = home_content if page_key == "inicio" else (FRONTEND / "pages" / f"{page_key}.html").read_text(encoding="utf-8")
    content = before + CONTENT_START + page_content + CONTENT_END + after
    content = content.replace("{{page_title}}", escape(title, quote=True))
    content = content.replace("{{page_description}}", escape(description, quote=True))
    content = content.replace(' aria-current="page"', "")
    nav_key = NAV_PARENT.get(page_key, page_key)
    content = content.replace(f'data-site-page="{nav_key}"', f'data-site-page="{nav_key}" aria-current="page"')
    origin = public_origin(store)
    headers = {}
    if origin and canonical_path:
        canonical = origin + canonical_path
        metadata = (f'<link rel="canonical" href="{escape(canonical, quote=True)}">\n'
                    f'<meta property="og:url" content="{escape(canonical, quote=True)}">')
        content = content.replace("</head>", metadata + "\n</head>")
        headers["Link"] = f'<{canonical}>; rel="canonical"'
    else:
        headers["X-Robots-Tag"] = "noindex, nofollow"
    # Las páginas se validan siempre, para que una actualización no siga enlazando recursos viejos.
    headers["Cache-Control"] = "no-store" if canonical_path is None else "no-cache"
    return HTMLResponse(content, status_code=status, headers=headers)


def landing_response(store, page_path="/captacion"):
    page_key, title, description = PUBLIC_PAGES[page_path]
    return render_shell(store, page_key, title, description, canonical_path=page_path)


def not_found_response(store):
    title, description = NOT_FOUND
    # The requested path is never reflected back into the response.
    return render_shell(store, "404", title, description, status=404)


def _wants_html(request):
    path = request.url.path
    if path.startswith(("/api/", "/webhooks/")):
        return False
    return "text/html" in request.headers.get("accept", "").lower()


def register_routes(app):
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        if exc.status_code == 404 and _wants_html(request):
            return not_found_response(app.state.store)
        headers = dict(exc.headers or {})
        if exc.status_code >= 500:
            headers.setdefault("Cache-Control", "no-store")
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)

    # Closures expose no page/file selector as a FastAPI query parameter.
    def page_endpoint(page_path):
        async def public_page():
            return landing_response(app.state.store, page_path)
        return public_page

    for page_path, (page_key, _, _) in PUBLIC_PAGES.items():
        app.add_api_route(page_path, page_endpoint(page_path), methods=["GET"],
                          include_in_schema=False, name=f"corporate_{page_key}")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(FAVICON, media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        origin = public_origin(app.state.store)
        text = "User-agent: *\nDisallow: /\n"
        if origin:
            allows = "".join(f"Allow: {path}\n" for path in PUBLIC_PAGES)
            text = (f"User-agent: *\n{allows}Disallow: /$\nDisallow: /app\nDisallow: /api/\n"
                    f"Disallow: /webhooks/\nSitemap: {origin}/sitemap.xml\n")
        return PlainTextResponse(text)

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap():
        origin = public_origin(app.state.store)
        body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        if origin:
            body += "".join(f"<url><loc>{escape(origin + path)}</loc></url>" for path in PUBLIC_PAGES)
        body += "</urlset>"
        return Response(body, media_type="application/xml")
