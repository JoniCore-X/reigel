r"""Allowlist reverse proxy for a temporary public link to the synthetic preview.

Only the public pages, the /ia conversation and their static files pass; every
other method or path receives a plain 404 without reaching the app. Standard
library only. It does not start any tunnel, read .env or touch any database.

Usage (preview already running on 127.0.0.1:8878):
    .\.venv\Scripts\python.exe scripts\public_gate.py --public-host <subdominio>.ngrok-free.app

The app keeps its own host and origin checks: the preview process must list the
public host in REIGEL_ALLOWED_HOSTS. This gate never rewrites Host or Origin.
"""
from __future__ import annotations

import argparse
import http.client
import ipaddress
import logging
import re
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 64 * 1024
# A document attached in /ia: the visitor limit of reigel/documents.py (3 MB).
ATTACHMENT_MAX_BODY = 3 * 1024 * 1024
MAX_TARGET = 4096
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 300  # A streamed /ia reply may take a while between sentences.
CHUNK = 8192

# Mirrors reigel/seo.py PUBLIC_PAGES plus the AI conversation. Exact, case-sensitive.
PUBLIC_PAGES = frozenset({
    "/captacion",
    "/soluciones/tesla-panel-mount-flat", "/soluciones/certificaciones",
})
# Desde el 27 de noviembre de 2026 estas seis direcciones solo redirigen a su ancla
# dentro de `/captacion`. Pasan igual: un enlace viejo tiene que seguir llegando.
MERGED_PAGES = frozenset({
    "/empresa", "/equipo", "/soluciones", "/proceso", "/contacto", "/preguntas",
})
READ_EXACT = PUBLIC_PAGES | MERGED_PAGES | {
    "/", "/ia", "/robots.txt", "/sitemap.xml", "/favicon.ico",
    "/api/ia/bootstrap", "/api/ia/status", "/api/ia/conversations", "/api/ia/suggestions",
}
# Only the stylesheets and scripts that the public pages and /ia reference.
STATIC_CSS = frozenset({
    "certificaciones", "coordination-chat", "corporate", "dark-mode", "depth-3d", "energy-scene", "energy-view",
    "google-form", "ia", "panel-mount", "power-solar-identity", "public-header", "public-intents",
    "public-shell", "reigel-loader", "site-loader", "solar-theme", "styles", "system-showcase",
    "tesla-experience", "theme-switch", "uiverse-components",
    "display-type", "scroll-cinema", "solar-hero",
})
STATIC_JS = frozenset({
    "chat", "corporate", "depth-3d", "energy-scene", "header-menu", "ia", "launcher-yield",
    "panel-mount", "public-intents", "reigel-loader", "site-loader", "system-showcase",
    "tesla-experience", "theme", "solar-hero-3d",
})
CONVERSATION = r"[0-9a-f]{32}"
RE_ASSET = re.compile(r"/static/assets/power-solar/(?:(?:panel-mount|sistema)/)?[a-z0-9][a-z0-9-]*\.(?:webp|png|jpg|svg)")
RE_CSS = re.compile(r"/static/css/([a-z0-9-]+)\.css")
RE_JS = re.compile(r"/static/js/([a-z0-9-]+)\.js")
RE_CONVERSATION = re.compile(rf"/api/ia/conversations/{CONVERSATION}")
RE_MESSAGES = re.compile(rf"/api/ia/conversations/{CONVERSATION}/messages")
RE_ATTACH = re.compile(rf"/api/ia/conversations/{CONVERSATION}/attachments")
RE_ATTACHMENT = re.compile(rf"/api/ia/conversations/{CONVERSATION}/attachments/{CONVERSATION}")
# Lo vendorizado se sirve por ruta exacta, no por carpeta: la escena del hero y la
# tipografía de los titulares son los dos únicos archivos de `vendor/` que la página
# pública pide, y nombrarlos uno a uno deja la puerta tan cerrada como estaba.
VENDOR = frozenset({
    "/static/assets/vendor/three/three.module.min.js",
    "/static/assets/vendor/fonts/space-grotesk-latin-wght-normal.woff2",
})
# Publicar algo con licencia MIT u OFL obliga a que su licencia sea alcanzable.
LICENSES = frozenset({
    "/static/assets/licenses/uiverse-components.txt",
    "/static/assets/licenses/three-LICENSE.txt",
    "/static/assets/licenses/space-grotesk-OFL.txt",
})
SAFE_PATH = re.compile(r"/[A-Za-z0-9._/-]*")
SAFE_QUERY = re.compile(r"[A-Za-z0-9._~%+=&,-]*")

HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection",
    "te", "trailer", "transfer-encoding", "upgrade",
})
# Never forwarded from the visitor: forwarding headers are set by this gate.
DROP_REQUEST = HOP_BY_HOP | {
    "content-length", "forwarded", "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host",
    "x-forwarded-port", "x-real-ip", "cookie", "expect",
}
# /ia only needs its own visitor cookie; team or chat sessions never pass.
FORWARD_COOKIES = frozenset({"reigel_ia"})


def split_target(target: str):
    """Return (path, query) for an origin-form target, or None if it is malformed."""
    if not target.startswith("/") or len(target) > MAX_TARGET or "#" in target:
        return None
    path, _, query = target.partition("?")
    return path, query


def decide(method: str, target: str) -> bool:
    """Default deny. True only for an exact method + canonical path on the allowlist."""
    parts = split_target(target)
    if parts is None:
        return False
    path, query = parts
    # Canonical paths only: no encoding, backslashes, dot segments, empty
    # segments, trailing slashes, path parameters or control characters.
    if not SAFE_PATH.fullmatch(path) or "//" in path or (path != "/" and path.endswith("/")):
        return False
    if any(segment in {".", ".."} for segment in path.split("/")):
        return False
    if not SAFE_QUERY.fullmatch(query):
        return False
    if method in {"GET", "HEAD"}:
        # HEAD only where the app answers it (StaticFiles); FastAPI routes reply 405.
        if method == "GET" and (path in READ_EXACT or RE_CONVERSATION.fullmatch(path)):
            return True
        if path in LICENSES or path in VENDOR or RE_ASSET.fullmatch(path):
            return True
        css = RE_CSS.fullmatch(path)
        if css:
            return css.group(1) in STATIC_CSS
        js = RE_JS.fullmatch(path)
        return bool(js) and js.group(1) in STATIC_JS
    if query:
        return False
    if method == "POST":
        return path == "/api/ia/conversations" or bool(RE_MESSAGES.fullmatch(path) or RE_ATTACH.fullmatch(path))
    if method == "DELETE" and RE_ATTACHMENT.fullmatch(path):
        # Remove a document attached but not sent yet.
        return True
    if method in {"PATCH", "DELETE"}:
        # Rename or delete one of the visitor's own /ia conversations.
        return bool(RE_CONVERSATION.fullmatch(path))
    return False


def body_limit(method: str, target: str, default: int) -> int:
    """Body cap for an allowed request: documents in /ia get the visitor file limit."""
    parts = split_target(target)
    if parts and method == "POST" and not parts[1] and RE_ATTACH.fullmatch(parts[0]):
        return ATTACHMENT_MAX_BODY
    return default


def filter_cookies(header: str) -> str:
    kept = []
    for item in header.split(";"):
        name, sep, value = item.strip().partition("=")
        if sep and name in FORWARD_COOKIES:
            kept.append(f"{name}={value}")
    return "; ".join(kept)


def client_address(peer: str, forwarded_for: str | None) -> str:
    """The tunnel agent connects from loopback and appends the visitor's address last."""
    try:
        loopback = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        loopback = False
    if loopback and forwarded_for:
        candidate = forwarded_for.split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass
    return peer


def make_handler(config):
    log = logging.getLogger("public_gate")

    class Gate(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "gate"
        sys_version = ""
        timeout = 60  # Socket timeout per connection; a slow or stalled client cannot pin a thread.

        def log_message(self, *args):  # The default logger would print the full target.
            pass

        def log_line(self, status):
            path = (self.path or "").partition("?")[0][:200]
            log.info("%s %s %s", self.command, path.encode("unicode_escape").decode("ascii"), status)

        def plain(self, status, text):
            body = (text + "\n").encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            self.close_connection = True
            self.log_line(status)

        def host_allowed(self):
            if not config.public_host:
                return True
            host = (self.headers.get("Host") or "").strip().lower()
            return host == config.public_host

        def handle_any(self):
            if len(self.headers.get_all("Host") or []) != 1 or not self.host_allowed():
                return self.plain(404, "Not Found")
            if not decide(self.command, self.path):
                return self.plain(404, "Not Found")
            body = b""
            if self.headers.get("Transfer-Encoding"):
                return self.plain(411, "Length Required")
            length_header = self.headers.get("Content-Length")
            if length_header is not None:
                try:
                    length = int(length_header)
                except ValueError:
                    return self.plain(400, "Bad Request")
                if length < 0:
                    return self.plain(400, "Bad Request")
                if length > body_limit(self.command, self.path, config.max_body):
                    return self.plain(413, "Payload Too Large")
                body = self.rfile.read(length)
            self.forward(body)

        def forward(self, body):
            headers = {}
            for name, value in self.headers.items():
                if name.lower() not in DROP_REQUEST:
                    headers[name] = value
            cookies = filter_cookies("; ".join(self.headers.get_all("Cookie") or []))
            if cookies:
                headers["Cookie"] = cookies
            proto = (self.headers.get("X-Forwarded-Proto") or "").strip().lower()
            headers["X-Forwarded-Proto"] = proto if proto in {"http", "https"} else config.forwarded_proto
            headers["X-Forwarded-For"] = client_address(self.client_address[0], self.headers.get("X-Forwarded-For"))
            if body or self.command in {"POST", "PATCH", "PUT", "DELETE"}:
                headers["Content-Length"] = str(len(body))
            headers["Connection"] = "close"
            upstream = http.client.HTTPConnection(config.upstream_host, config.upstream_port, timeout=CONNECT_TIMEOUT)
            try:
                upstream.request(self.command, self.path, body=body or None, headers=headers)
                upstream.sock.settimeout(READ_TIMEOUT)
                response = upstream.getresponse()
            except (OSError, http.client.HTTPException):
                upstream.close()
                return self.plain(502, "Bad Gateway")
            try:
                self.relay(response)
            except (OSError, http.client.HTTPException):
                self.close_connection = True  # Client left or upstream broke mid-stream.
            finally:
                upstream.close()

        def relay(self, response):
            self.send_response(response.status, response.reason)
            connection_tokens = {t.strip().lower() for t in (response.getheader("Connection") or "").split(",")}
            length = None
            for name, value in response.getheaders():
                lower = name.lower()
                if lower in HOP_BY_HOP or lower in connection_tokens or lower in {"server", "date"}:
                    continue
                if lower == "content-length":
                    length = value
                self.send_header(name, value)
            no_body = self.command == "HEAD" or response.status in {204, 304} or 100 <= response.status < 200
            chunked = length is None and not no_body
            if chunked:
                self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
            self.log_line(response.status)
            self.close_connection = True
            if no_body:
                return
            while True:
                data = response.read1(CHUNK)  # Returns as soon as bytes arrive: SSE is not held back.
                if not data:
                    break
                if chunked:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
                else:
                    self.wfile.write(data)
                self.wfile.flush()
            if chunked:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()

        do_GET = do_HEAD = do_POST = do_PATCH = do_DELETE = do_PUT = do_OPTIONS = do_TRACE = do_CONNECT = handle_any

    return Gate


class GateServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Proxy de lista blanca para la demostración pública temporal.")
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8879)
    parser.add_argument("--upstream", default="127.0.0.1:8878")
    parser.add_argument("--public-host", default="", help="Host público exacto (p. ej. abc.ngrok-free.app); otros Host reciben 404.")
    parser.add_argument("--forwarded-proto", default="https", choices=["http", "https"],
                        help="X-Forwarded-Proto cuando el túnel no lo envía.")
    parser.add_argument("--max-body", type=int, default=MAX_BODY)
    args = parser.parse_args(argv)
    host, _, port = args.upstream.rpartition(":")
    args.upstream_host, args.upstream_port = host or "127.0.0.1", int(port)
    args.public_host = args.public_host.strip().lower()
    return args


def main(argv=None):
    config = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    server = GateServer((config.listen, config.port), make_handler(config))
    print(f"Gate en http://{config.listen}:{config.port} -> http://{config.upstream_host}:{config.upstream_port}"
          f" (host público: {config.public_host or 'cualquiera'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
