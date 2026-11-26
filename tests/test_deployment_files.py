"""Deployment contract (docs/DESPLIEGUE.md), checked without Docker or network.

Static checks of Dockerfile, compose.yaml, Caddyfile, .dockerignore and
.env.example, plus the restore and server-check scripts against synthetic,
temporary databases. Nothing here proves a real deployment.
"""
import asyncio
import importlib.util
import ipaddress
import re
import sqlite3
from pathlib import Path

import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from reigel.core import Store
from reigel.identity import Identity

ROOT = Path(__file__).resolve().parent.parent


def read(name):
    return (ROOT / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def uncommented(text):
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def section(text, name, indent):
    """Body of a YAML mapping key at a given indentation, without a YAML parser."""
    pad = " " * indent
    match = re.search(rf"^{pad}{re.escape(name)}:[^\n]*\n((?:{pad} [^\n]*\n|\s*\n)*)", text, re.M)
    assert match, name
    return match.group(1)


def load_script(name):
    spec = importlib.util.spec_from_file_location(f"reigel_{name}_script", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPOSE = uncommented(read("compose.yaml")) + "\n"
SERVICES = section(COMPOSE, "services", 0)
APP = section(SERVICES, "app", 2)
CADDY = section(SERVICES, "caddy", 2)
OLLAMA = section(SERVICES, "ollama", 2)
DOCKERFILE = uncommented(read("Dockerfile"))
CADDYFILE = uncommented(read("deploy/Caddyfile"))


# ── compose.yaml ────────────────────────────────────────────────────────────

def test_only_caddy_publishes_ports_and_the_app_is_reached_through_the_internal_network():
    assert "ports:" not in APP and "ports:" not in OLLAMA
    assert "network_mode" not in APP  # never the host network
    assert re.findall(r'^\s+- "([^"]+)"$', section(CADDY, "ports", 4), re.M) == ["80:80", "443:443", "443:443/udp"]
    assert "8765" not in CADDY and "11434" not in CADDY.replace("OLLAMA", "")
    networks = section(COMPOSE, "networks", 0)
    assert "internal: true" in section(networks, "interna", 2)
    assert "interna:" in section(APP, "networks", 4) and "interna:" in section(CADDY, "networks", 4)
    assert "publica" not in section(APP, "networks", 4)  # the public network is Caddy's alone


def test_forwarded_headers_are_trusted_only_from_the_proxy_address():
    for text in (COMPOSE, DOCKERFILE):
        assert "--forwarded-allow-ips" not in text
        assert not re.search(r"""FORWARDED_ALLOW_IPS\s*[:=]\s*["']?\*""", text)
    assert "--proxy-headers" in DOCKERFILE
    assert re.search(r"FORWARDED_ALLOW_IPS=127\.0\.0\.1\s*$", DOCKERFILE, re.M)  # safe default without compose
    trusted = re.search(r"FORWARDED_ALLOW_IPS: (\S+)", APP).group(1)
    caddy_address = re.search(r"ipv4_address: (\S+)", section(CADDY, "networks", 4)).group(1)
    app_address = re.search(r"ipv4_address: (\S+)", section(APP, "networks", 4)).group(1)
    subnet = ipaddress.ip_network(re.search(r"subnet: (\S+)", COMPOSE).group(1))
    assert trusted == caddy_address != app_address  # one address, not a network and not "*"
    assert ipaddress.ip_address(caddy_address) in subnet and ipaddress.ip_address(app_address) in subnet
    assert subnet.is_private


def test_the_configured_trust_resolves_real_clients_and_ignores_spoofed_headers():
    trusted = re.search(r"FORWARDED_ALLOW_IPS: (\S+)", APP).group(1)
    seen = {}

    async def endpoint(scope, receive, send):
        seen.update(client=scope["client"][0], scheme=scope["scheme"])

    def call(peer, forwarded):
        scope = {"type": "http", "scheme": "http", "client": (peer, 40000), "server": ("app", 8765),
                 "headers": [(b"x-forwarded-for", forwarded.encode()), (b"x-forwarded-proto", b"https")]}
        asyncio.run(ProxyHeadersMiddleware(endpoint, trusted_hosts=trusted)(scope, None, None))
        return dict(seen)

    # Through Caddy: the visitor's address and HTTPS reach rate limits, audit and cookies.
    assert call(trusted, "203.0.113.9") == {"client": "203.0.113.9", "scheme": "https"}
    # A value the visitor prepended never wins over the address Caddy observed.
    assert call(trusted, "10.0.0.1, 203.0.113.9")["client"] == "203.0.113.9"
    # Anything else on the network (or loopback) cannot declare another address.
    assert call("172.30.87.99", "203.0.113.9") == {"client": "172.30.87.99", "scheme": "http"}
    assert call("127.0.0.1", "203.0.113.9")["client"] == "127.0.0.1"


def test_app_container_is_hardened_single_process_and_health_checked():
    assert 'user: "10001:10001"' in APP
    assert "read_only: true" in APP
    assert re.search(r"- /tmp:\S*noexec", section(APP, "tmpfs", 4))
    assert "no-new-privileges:true" in APP
    assert re.search(r"cap_drop:\n\s+- ALL", APP) and "cap_add" not in APP and "privileged" not in COMPOSE
    assert "restart: unless-stopped" in APP
    assert "/health" in section(APP, "healthcheck", 4)
    for limit in ("mem_limit:", "cpus:", "pids_limit:"):
        assert limit in APP and limit in CADDY and limit in OLLAMA
    assert "REIGEL_ENV: production" in APP
    assert "condition: service_healthy" in CADDY
    assert "docker.sock" not in COMPOSE
    assert "replicas" not in COMPOSE  # rate limits and coordination live in one process
    assert re.search(r'"--workers", "1"', DOCKERFILE)


def test_data_volume_holds_the_database_and_the_totp_key(tmp_path):
    assert "- solar_data:/app/data" in APP
    assert "REIGEL_DB_PATH: /app/data/reigel.db" in APP
    assert re.search(r"^  solar_data:", section(COMPOSE, "volumes", 0), re.M)
    assert "REIGEL_DB_PATH=/app/data/reigel.db" in DOCKERFILE
    # The key file is created next to the database, so it lands in the same volume.
    database = tmp_path / "data" / "reigel.db"
    assert Identity(Store(database)).key_path() == Path(f"{database}.totp.key")
    # Secrets come from the server's .env, never from values written in the file.
    assert re.search(r"env_file:\n\s+- \.env\n", APP)
    assert not re.search(r"(TOKEN|SECRET|PASSWORD|TOTP_KEY)\w*: *\S", COMPOSE)


def test_ollama_is_an_optional_sidecar_never_exposed():
    assert 'profiles: ["ia"]' in OLLAMA  # off unless the owner turns it on
    assert 'network_mode: "service:app"' in OLLAMA  # the backend only talks to 127.0.0.1:11434
    assert "OLLAMA_HOST: 127.0.0.1:11434" in OLLAMA  # loopback only: Caddy cannot reach it
    assert "0.0.0.0" not in OLLAMA and "networks:" not in OLLAMA
    assert "ollama" not in section(CADDY, "depends_on", 4)
    assert "ollama" not in APP  # the site starts and works without AI


# ── Dockerfile and .dockerignore ────────────────────────────────────────────

def test_image_runs_as_an_unprivileged_user_and_cannot_rewrite_its_code():
    instructions = [line.split()[0] for line in DOCKERFILE.splitlines() if line and not line.startswith(" ")]
    users = [line.split()[1] for line in DOCKERFILE.splitlines() if line.startswith("USER ")]
    assert users and users[-1] not in {"root", "0"}
    assert instructions.index("USER") < instructions.index("CMD")
    assert "--uid 10001" in DOCKERFILE
    assert "--chown" not in DOCKERFILE  # code stays owned by root, read-only for the app user
    assert "chown solar:solar /app/data" in DOCKERFILE  # only the data directory is writable
    assert "HEALTHCHECK" in DOCKERFILE and "/health" in DOCKERFILE
    copied = re.findall(r"^COPY (\S+)", DOCKERFILE, re.M)
    assert copied == ["requirements.txt", "reigel", "frontend", "scripts", "main.py"]  # never "COPY ."


def test_dockerignore_and_gitignore_keep_secrets_and_data_out():
    ignored = read(".dockerignore").split()
    for pattern in (".env", ".env.*", "data", "backups", "*.key", "**/*.key", "*.pem", "*.db*", "**/*.db*",
                    "*.sqlite*", ".git", "local-access.txt", "secrets", "credentials"):
        assert pattern in ignored, pattern
    assert "!.env.example" in ignored
    assert ignored.index(".env.*") < ignored.index("!.env.example")
    git = read(".gitignore").split()
    for pattern in (".env", ".env.*", "data/", "backups/", "*.key", "*.pem", "*.db", "*.db-wal", ".local-access.txt"):
        assert pattern in git, pattern


# ── Caddyfile ───────────────────────────────────────────────────────────────

def test_caddyfile_uses_placeholders_and_leaves_security_headers_to_the_app():
    assert re.search(r"^\{\$DOMAIN\} \{$", CADDYFILE, re.M)
    assert "email {$CADDY_EMAIL}" in CADDYFILE
    assert "reverse_proxy app:8765" in CADDYFILE
    assert not re.search(r"[\w-]+\.(com|net|org|pr|io|dev)\b", CADDYFILE)  # no real domain or email
    assert "@" not in CADDYFILE
    # One source of truth: the application sets these on every response.
    for header in ("Content-Security-Policy", "Strict-Transport-Security", "X-Frame-Options",
                   "Referrer-Policy", "Permissions-Policy"):
        assert header not in CADDYFILE, header
        assert header in read("reigel/api.py")
    assert "trusted_proxies" not in CADDYFILE  # Caddy replaces X-Forwarded-For with the peer it sees
    assert "header_up" not in CADDYFILE
    assert "tls internal" not in CADDYFILE and "auto_https off" not in CADDYFILE
    assert CADDYFILE.count("{") == CADDYFILE.count("}")


# ── .env.example ────────────────────────────────────────────────────────────

def test_env_example_lists_production_variables_without_values():
    values = {}
    for line in read(".env.example").splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    for key in ("REIGEL_ENV", "SITE_URL", "DOMAIN", "CADDY_EMAIL", "REIGEL_ALLOWED_HOSTS", "REIGEL_TOTP_KEY",
                "REIGEL_TEAM_ALLOWED_EMAILS", "REIGEL_CHAT_AI", "REIGEL_LOCAL_MODEL", "COMPOSE_PROFILES"):
        assert key in values, key
    assert "REIGEL_DB_PATH" in read(".env.example")
    assert values.pop("REIGEL_ENV") == "local"  # copying the example never switches production on by itself
    harmless = {"REIGEL_LOCAL_MODEL", "REIGEL_LOCAL_TIMEOUT_SECONDS", "REIGEL_LOCAL_NUM_CTX",
                "REIGEL_LOCAL_NUM_PREDICT", "REIGEL_LOCAL_TEMPERATURE"}
    for key, value in values.items():
        if key in harmless:
            assert len(value) <= 12 and "@" not in value and "//" not in value, key
        else:
            assert value == "", key  # domains, emails, keys, tokens and secrets stay empty
    # Addresses in comments are reserved documentation names only.
    for host in re.findall(r"@([\w.-]+\.\w+)|(?<![\w/.-])((?:[\w-]+\.)+(?:com|net|org|pr|io))\b", read(".env.example")):
        name = host[0] or host[1]
        assert name.endswith(("example.com", "ejemplo.com")), name


# ── Server scripts ──────────────────────────────────────────────────────────

def test_backup_routine_separates_key_from_database_and_prunes_only_after_success():
    script = read("deploy/backup.sh")
    assert "set -euo pipefail" in script and "umask 077" in script
    assert "python scripts/backup.py --output" in script  # SQLite online backup, not a file copy of a live WAL
    assert '"$base_dir" = "$key_dir"' in script  # refuses to store both together
    assert script.index("sha256sum") < script.index("-delete")  # retention runs after verification
    assert "curl" not in script and "scp" not in script and "rclone" not in script  # uploads nothing
    restore = uncommented(read("deploy/restore.sh"))
    assert restore.index("docker compose stop") < restore.index("python scripts/restore.py")
    assert "set -euo pipefail" in restore and "--no-deps" in restore


@pytest.fixture
def enrolled(tmp_path, monkeypatch):
    """A synthetic database with one registered authenticator and its key file."""
    monkeypatch.delenv("REIGEL_TOTP_KEY", raising=False)
    path = tmp_path / "origen" / "reigel.db"
    store = Store(path)
    user = store.create_user({"email": "titular.powersolar@example.com", "name": "Titular", "role": "admin",
                              "password": "Sintetica-Demo-2026!"}, bootstrap=True)
    identity = Identity(store)
    nonce, sealed = identity._seal(b"secreto-sintetico-20", user["id"])
    with store.connect() as db:
        db.execute("INSERT INTO team_totp(user_id,secret_nonce,secret_cipher,last_step,confirmed_at) VALUES(?,?,?,?,?)",
                   (user["id"], nonce, sealed, -1, "2026-11-25T00:00:00+00:00"))
    copy = tmp_path / "copias" / "powersolar-copia.db"
    copy.parent.mkdir()
    source = sqlite3.connect(path)
    target = sqlite3.connect(copy)
    source.backup(target)
    source.close()
    target.close()
    key = tmp_path / "claves" / "powersolar-copia.db.totp.key"
    key.parent.mkdir()
    key.write_bytes(Path(f"{path}.totp.key").read_bytes())
    return {"copy": copy, "key": key, "user": user["id"], "secret": b"secreto-sintetico-20", "origin": path}


def test_restore_puts_database_and_key_back_and_the_authenticator_still_opens(enrolled, tmp_path, capsys):
    restore = load_script("restore")
    destination = tmp_path / "servidor" / "reigel.db"
    code = restore.main(["--from", str(enrolled["copy"]), "--key", str(enrolled["key"]), "--db", str(destination), "--yes"])
    output = capsys.readouterr()
    assert code == 0
    assert enrolled["key"].read_bytes().hex() not in output.out + output.err  # the key is never printed
    assert Path(f"{destination}.totp.key").read_bytes() == enrolled["key"].read_bytes()
    identity = Identity(Store(destination))  # opens normally; additive migrations apply here
    assert identity.key_status()[0] == "file"
    with identity.store.connect() as db:
        row = db.execute("SELECT secret_nonce,secret_cipher FROM team_totp WHERE user_id=?", (enrolled["user"],)).fetchone()
    assert identity._open(row["secret_nonce"], row["secret_cipher"], enrolled["user"]) == enrolled["secret"]


def test_restore_keeps_the_replaced_database_instead_of_deleting_it(enrolled, tmp_path):
    restore = load_script("restore")
    destination = tmp_path / "servidor" / "reigel.db"
    old = Store(destination)
    with old.connect() as db:
        db.execute("UPDATE settings SET value='Base anterior' WHERE key='name'")
    assert restore.main(["--from", str(enrolled["copy"]), "--key", str(enrolled["key"]), "--db", str(destination), "--yes"]) == 0
    kept = [path for path in destination.parent.iterdir() if path.name.startswith("antes-de-restaurar-")]
    assert len(kept) == 1
    previous = sqlite3.connect(kept[0] / "reigel.db")
    try:
        assert previous.execute("SELECT value FROM settings WHERE key='name'").fetchone()[0] == "Base anterior"
    finally:
        previous.close()
    assert not list(destination.parent.glob("*.restaurando"))


def test_restore_fails_closed_without_the_right_key_and_changes_nothing(enrolled, tmp_path, capsys):
    restore = load_script("restore")
    destination = tmp_path / "servidor" / "reigel.db"
    # No key at all: refused, nothing created.
    assert restore.main(["--from", str(enrolled["copy"]), "--db", str(destination), "--yes"]) == 1
    assert "no se encontró su clave" in capsys.readouterr().err
    # A different 32-byte key (what a regenerated key would be): refused.
    wrong = tmp_path / "otra.totp.key"
    wrong.write_bytes(bytes(32))
    assert restore.main(["--from", str(enrolled["copy"]), "--key", str(wrong), "--db", str(destination), "--yes"]) == 1
    assert "no corresponde" in capsys.readouterr().err
    # A truncated key file: refused.
    wrong.write_bytes(b"corta")
    assert restore.main(["--from", str(enrolled["copy"]), "--key", str(wrong), "--db", str(destination), "--yes"]) == 1
    # A file that is not a database: refused.
    broken = tmp_path / "rota.db"
    broken.write_bytes(b"esto no es SQLite" * 100)
    assert restore.main(["--from", str(broken), "--db", str(destination), "--yes"]) == 1
    # The copy onto itself: refused.
    assert restore.main(["--from", str(enrolled["copy"]), "--db", str(enrolled["copy"]), "--yes"]) == 1
    assert not destination.exists() and not destination.parent.exists()


def test_restore_check_only_verifies_and_unattended_runs_need_explicit_confirmation(enrolled, tmp_path, capsys):
    restore = load_script("restore")
    destination = tmp_path / "servidor" / "reigel.db"
    arguments = ["--from", str(enrolled["copy"]), "--key", str(enrolled["key"]), "--db", str(destination)]
    assert restore.main([*arguments, "--check"]) == 0
    assert "No se cambió nada" in capsys.readouterr().out
    assert restore.main(arguments, ask=lambda prompt: "no") == 3
    assert not destination.exists()
    assert restore.main(arguments, ask=lambda prompt: "si") == 0
    assert destination.is_file()


def test_restore_without_key_is_an_explicit_choice_that_leaves_authenticators_blocked(enrolled, tmp_path, monkeypatch):
    restore = load_script("restore")
    destination = tmp_path / "servidor" / "reigel.db"
    assert restore.main(["--from", str(enrolled["copy"]), "--db", str(destination), "--sin-clave", "--yes"]) == 0
    assert not Path(f"{destination}.totp.key").exists()
    assert Identity(Store(destination)).key_status()[0] == "missing"  # the server will not invent a key


def test_restore_accepts_the_key_from_the_environment_variable(enrolled, tmp_path, monkeypatch):
    import base64
    restore = load_script("restore")
    destination = tmp_path / "servidor" / "reigel.db"
    monkeypatch.setenv("REIGEL_TOTP_KEY", base64.urlsafe_b64encode(enrolled["key"].read_bytes()).decode())
    assert restore.main(["--from", str(enrolled["copy"]), "--db", str(destination), "--yes"]) == 0
    assert not Path(f"{destination}.totp.key").exists()  # the variable is the key; no file is written
    monkeypatch.setenv("REIGEL_TOTP_KEY", base64.urlsafe_b64encode(bytes(32)).decode())
    assert restore.main(["--from", str(enrolled["copy"]), "--db", str(tmp_path / "otro" / "reigel.db"), "--yes"]) == 1


def test_server_check_reports_configuration_without_printing_secrets(enrolled, monkeypatch):
    check = load_script("deploy_check")
    assert check.forwarded_trust("*")[0] == "ERROR"
    assert check.forwarded_trust("172.30.87.2, *")[0] == "ERROR"
    assert check.forwarded_trust("0.0.0.0/0")[0] == "ERROR"
    assert check.forwarded_trust("172.16.0.0/12")[0] == "ERROR"
    assert check.forwarded_trust("8.8.8.8")[0] == "ERROR"
    assert check.forwarded_trust("172.30.87.2")[0] == "OK"

    def fetch(url):
        assert url.startswith("http://127.0.0.1:")  # never leaves the machine
        if url.endswith("/health"):
            return {"status": "ok", "database": True}
        raise OSError("sin Ollama")

    environment = {"REIGEL_ENV": "production", "SITE_URL": "https://reigel.ejemplo.com", "FORWARDED_ALLOW_IPS": "172.30.87.2",
                   "REIGEL_DB_PATH": str(enrolled["origin"]), "REIGEL_TEAM_ALLOWED_EMAILS": "ana.powersolar@example.com"}
    results = {name: (status, detail) for name, status, detail in check.checks(environment, fetch, uid=10001)}
    assert all(status != "ERROR" for status, _ in results.values()), results
    assert results["Clave de Google Authenticator"][0] == "OK"
    assert results["IA local"][0] == "AVISO"  # off by default; not an error
    assert "example.com" not in str(results)

    environment.update(REIGEL_CHAT_AI="ollama", FORWARDED_ALLOW_IPS="*", REIGEL_ENV="local", SITE_URL="http://reigel.ejemplo.com")
    Path(f"{enrolled['origin']}.totp.key").unlink()
    results = {name: status for name, status, _ in check.checks(environment, fetch, uid=0)}
    for name in ("Modo", "Dirección pública", "Proxy de confianza", "Usuario", "Clave de Google Authenticator", "IA local"):
        assert results[name] == "ERROR", name
    with pytest.raises(ValueError):
        check.local_json("https://ejemplo.com/api/tags")
    # Behind a misconfigured proxy every access would carry the internal network.
    assert check.visitor_networks([])[0] == "AVISO"
    assert check.visitor_networks(["172.30.87.0/24", "172.30.87.0/24"])[0] == "ERROR"
    assert check.visitor_networks(["172.30.87.0/24", "8.8.8.0/24"])[0] == "OK"


# ── Documentation ───────────────────────────────────────────────────────────

def test_runbook_covers_the_steps_only_the_owner_can_take_and_uses_placeholders():
    guide = read("docs/DESPLIEGUE.md")
    for required in ("scripts/bootstrap.py", "scripts/team_recovery.py", "--purpose enroll", "deploy/backup.sh",
                     "deploy/restore.sh", "scripts/deploy_check.py", "/health", "REIGEL_TEAM_ALLOWED_EMAILS",
                     "COMPOSE_PROFILES=ia", "ollama pull", "SOURCES.md", "420 W", "repositorio es público",
                     "sin revisión humana", "Antes de publicar"):
        assert required in guide, required
    for host in re.findall(r"https?://([\w.-]+)", guide):
        assert host.endswith(("ejemplo.com", "127.0.0.1", "docs.docker.com", "github.com", "DOMAIN")), host
    for address in re.findall(r"[\w.+-]+@([\w-]+\.[\w.-]+)", guide):
        assert address.rstrip(".").endswith(("ejemplo.com", "example.com")), address
