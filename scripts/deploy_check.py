"""Comprobación del servidor ya desplegado, desde dentro del contenedor.

    docker compose exec app python scripts/deploy_check.py

Lee la configuración del proceso y la base en modo lectura. No migra, no crea
archivos, no imprime claves ni correos y solo se conecta a esta misma máquina
(127.0.0.1): la aplicación y, si la IA está activada, Ollama.

``scripts/doctor.py`` es el diagnóstico del código en la computadora de
desarrollo (necesita Git, Node.js y las pruebas, que no viajan en la imagen).
"""
from __future__ import annotations

import ipaddress
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reigel.core import DomainError, default_db_path, site_origin  # noqa: E402
from reigel.identity import totp_key_status  # noqa: E402

LOOPBACK = "http://127.0.0.1"


def forwarded_trust(value: str) -> tuple[str, str]:
    """Only a specific proxy address may declare the client address."""
    entries = [item.strip() for item in value.split(",") if item.strip()]
    for entry in entries:
        if entry == "*":
            return "ERROR", "FORWARDED_ALLOW_IPS es «*»: cualquier cliente puede falsificar su dirección"
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            return "ERROR", "FORWARDED_ALLOW_IPS contiene un valor que no es una dirección"
        if network.num_addresses > 256 or not (network.is_private or network.is_loopback):
            return "ERROR", "FORWARDED_ALLOW_IPS confía en una red amplia o pública; indica solo la dirección del proxy"
    if not entries:
        return "AVISO", "FORWARDED_ALLOW_IPS vacío: la aplicación verá la dirección del proxy, no la del cliente"
    return "OK", f"cabeceras de reenvío aceptadas solo de {len(entries)} dirección(es) privada(s)"


def visitor_networks(seen: list[str]) -> tuple[str, str]:
    """Recent audited accesses must come from real networks, not from the proxy's own."""
    networks = []
    for value in seen:
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    if not networks:
        return "AVISO", "todavía no hay accesos registrados; entra en /app desde tu navegador y repite"
    if production_proxy_only(networks):
        return "ERROR", ("los últimos accesos llegan con direcciones internas: la aplicación no ve la dirección real "
                         "(revisa DNS sin intermediarios, IPv6 y que no sea Docker Desktop)")
    return "OK", "los accesos recientes llegan con la red real del visitante (truncada)"


def production_proxy_only(networks) -> bool:
    return all(network.is_private or network.is_loopback for network in networks)


def local_json(url: str):
    if not url.startswith(LOOPBACK + ":"):
        raise ValueError("solo direcciones locales")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=4) as response:  # noqa: S310 - loopback only
        return json.loads(response.read(1_000_000).decode("utf-8"))


def checks(environ=os.environ, fetch=local_json, uid=None) -> list[tuple[str, str, str]]:
    results = []

    def add(name, status, detail):
        results.append((name, status, detail))

    production = environ.get("REIGEL_ENV", "local").lower() == "production"
    add("Modo", "OK" if production else "ERROR",
        "producción" if production else "REIGEL_ENV no es «production»: las cookies no exigen HTTPS")
    try:
        origin = site_origin(environ.get("SITE_URL", "").rstrip("/"))
        add("Dirección pública", "OK" if origin else "ERROR", origin or "SITE_URL vacío")
    except DomainError:
        add("Dirección pública", "ERROR", "SITE_URL no es un origen HTTPS válido")
    add("Proxy de confianza", *forwarded_trust(environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")))

    uid = uid if uid is not None else (os.getuid() if hasattr(os, "getuid") else None)
    if uid is None:
        add("Usuario", "AVISO", "no se puede comprobar en este sistema")
    else:
        add("Usuario", "ERROR" if uid == 0 else "OK", "el proceso corre como root" if uid == 0 else f"sin privilegios (uid {uid})")

    database = Path(default_db_path(environ.get("REIGEL_DB_PATH") or None))
    if not database.is_file():
        add("Base de datos", "ERROR", f"no existe {database}; se crea al arrancar la aplicación")
    else:
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=15)
        try:
            quick = connection.execute("PRAGMA quick_check").fetchone()[0]
            admins = connection.execute("SELECT count(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]

            def has_secrets():
                try:
                    return bool(connection.execute("SELECT EXISTS(SELECT 1 FROM team_totp)").fetchone()[0])
                except sqlite3.Error:
                    return False

            key_status, key_detail = totp_key_status(str(database), has_secrets)
            try:
                seen = [row[0] for row in connection.execute(
                    "SELECT client_net FROM identity_audit WHERE client_net IS NOT NULL ORDER BY created_at DESC LIMIT 20")]
            except sqlite3.Error:
                seen = []
        except sqlite3.Error:
            quick, admins, key_status, key_detail, seen = "error", 0, "invalid", "no se pudo leer la base", []
        finally:
            connection.close()
        add("Base de datos", "OK" if quick == "ok" else "ERROR",
            f"{database} íntegra" if quick == "ok" else "la base no supera la comprobación de SQLite")
        add("Administrador", "OK" if admins else "ERROR",
            f"{admins} administrador(es) activo(s)" if admins else "ninguno: ejecutar scripts/bootstrap.py")
        add("Clave de Google Authenticator", "ERROR" if key_status in {"missing", "invalid"} else "OK", key_detail)
        add("Dirección de los visitantes", *visitor_networks(seen))
        leftover = database.parent / "local-access.txt"
        if leftover.exists():
            add("Acceso inicial", "AVISO", f"{leftover} sigue en el servidor: bórralo cuando hayas cambiado la contraseña")

    try:
        health = fetch(f"{LOOPBACK}:8765/health")
        add("Aplicación", "OK" if health.get("status") == "ok" else "ERROR", "/health responde")
    except (OSError, ValueError, urllib.error.URLError):
        add("Aplicación", "ERROR", "/health no responde en 127.0.0.1:8765")

    if environ.get("REIGEL_CHAT_AI", "").strip().lower() not in {"1", "on", "yes", "local", "ollama"}:
        add("IA local", "AVISO", "desactivada (REIGEL_CHAT_AI vacío); el resto del sitio funciona sin ella")
    else:
        model = (environ.get("REIGEL_CHAT_MODEL") or environ.get("REIGEL_LOCAL_MODEL") or "qwen2.5:3b").strip()
        try:
            names = {item.get("name") for item in fetch(f"{LOOPBACK}:11434/api/tags").get("models", [])}
            add("IA local", "OK" if model in names else "ERROR",
                f"Ollama responde y tiene {model}" if model in names else f"Ollama responde, pero falta el modelo {model}")
        except (OSError, ValueError, urllib.error.URLError):
            add("IA local", "ERROR", "activada, pero Ollama no responde en 127.0.0.1:11434 (¿perfil «ia» encendido?)")
    return results


def main() -> int:
    results = checks()
    print("R.E.I.G.E.L. | Comprobación del servidor (solo lectura, solo esta máquina)")
    for name, status, detail in results:
        print(f"[{status}] {name}: {detail}")
    success = all(status != "ERROR" for _, status, _ in results)
    print("RESULTADO:", "APROBADO" if success else "REQUIERE CORRECCIÓN")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
