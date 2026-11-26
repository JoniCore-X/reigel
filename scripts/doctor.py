"""Diagnóstico local de R.E.I.G.E.L.; no toca la base comercial ni envía datos.

Uso desde PowerShell (con .venv activado):
    python scripts/doctor.py
    python scripts/doctor.py --sin-pruebas
    python scripts/doctor.py --json
    python scripts/doctor.py --sin-pruebas --base RUTA_DE_LA_BASE

Con --base (y las mismas variables de entorno que usará el servidor) comprueba,
antes de arrancar, que la clave de Google Authenticator esté disponible. Solo
abre la base en modo lectura para contar cuentas registradas; no migra nada y
nunca imprime la clave.

Las pruebas de pytest usan las bases temporales definidas por el proyecto.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "main.py",
    "requirements.txt",
    "reigel/api.py",
    "reigel/core.py",
    "reigel/conversation.py",
    "reigel/webchat.py",
    "frontend/index.html",
    "frontend/landing.html",
    "frontend/js/app.js",
    "frontend/js/public.js",
    "frontend/js/chat.js",
    "tests/test_core.py",
)

MODULES = (
    "fastapi",
    "httpx",
    "uvicorn",
    "pytest",
)

SENSITIVE_PATHS = (
    ".env",
    ".local-access.txt",
    "local-access.txt",
    ".venv",
    "venv",
    "data",
    "database",
    "backups",
    "*.db",
    "*.db-wal",
    "*.db-shm",
    "*.sqlite*",
    "*.pem",
    "*.key",
)


@dataclass(frozen=True)
class Result:
    check: str
    status: str
    detail: str


def run_command(
    command: list[str],
    *,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str] | None:
    """Ejecuta argumentos explícitos sin utilizar shell."""
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_structure(root: Path = ROOT) -> Result:
    missing = [
        item
        for item in REQUIRED_FILES
        if not (root / item).is_file()
    ]

    if missing:
        return Result(
            "Estructura",
            "ERROR",
            "Faltan archivos: " + ", ".join(missing),
        )

    return Result(
        "Estructura",
        "OK",
        f"{len(REQUIRED_FILES)} archivos esenciales presentes",
    )


def check_python() -> Result:
    version = ".".join(str(part) for part in sys.version_info[:3])

    if sys.version_info < (3, 11):
        return Result(
            "Python",
            "ERROR",
            f"{version}; se necesita Python 3.11 o superior",
        )

    return Result("Python", "OK", version)


def check_dependencies() -> Result:
    missing = [
        name
        for name in MODULES
        if importlib.util.find_spec(name) is None
    ]

    if missing:
        return Result(
            "Dependencias",
            "ERROR",
            "No instaladas: " + ", ".join(missing),
        )

    return Result(
        "Dependencias",
        "OK",
        "FastAPI, HTTPX, Uvicorn y Pytest disponibles",
    )


def check_timezone() -> Result:
    try:
        ZoneInfo("America/Puerto_Rico")
    except ZoneInfoNotFoundError:
        return Result(
            "Zona horaria",
            "ERROR",
            "No disponible America/Puerto_Rico; instala tzdata",
        )

    return Result(
        "Zona horaria",
        "OK",
        "America/Puerto_Rico disponible",
    )


def check_totp_key(db_path: str | None) -> Result:
    """Fail closed before start: existing authenticators need their original key."""
    name = "Clave de Google Authenticator"
    if not db_path:
        return Result(name, "AVISO", "Omitida: usa --base RUTA para comprobarla antes de arrancar el servidor")
    path = Path(db_path)
    if not path.is_file():
        return Result(name, "ERROR", "No existe la base indicada; no se creó nada")
    sys.path.insert(0, str(ROOT))
    from reigel.identity import totp_key_status

    def has_secrets() -> bool:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=15)
        try:
            return bool(connection.execute("SELECT EXISTS(SELECT 1 FROM team_totp)").fetchone()[0])
        except sqlite3.Error:
            return False
        finally:
            connection.close()

    status, detail = totp_key_status(str(path), has_secrets)
    level = "ERROR" if status in {"missing", "invalid"} else "OK"
    return Result(name, level, detail)


def check_git_privacy() -> Result:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        return Result(
            "Privacidad Git",
            "AVISO",
            "No hay repositorio Git local; verificación omitida",
        )

    outcome = run_command(
        [
            "git",
            "ls-files",
            "--cached",
            "--",
            *SENSITIVE_PATHS,
        ],
        timeout=20,
    )

    if outcome is None or outcome.returncode:
        return Result(
            "Privacidad Git",
            "ERROR",
            "No se pudo verificar el índice de Git",
        )

    tracked = [
        name
        for name in outcome.stdout.splitlines()
        if name.strip()
    ]

    if tracked:
        return Result(
            "Privacidad Git",
            "ERROR",
            f"{len(tracked)} archivo(s) privado(s) rastreado(s): "
            "revisar antes de publicar",
        )

    return Result(
        "Privacidad Git",
        "OK",
        "Sin archivos privados conocidos preparados en Git",
    )


def check_javascript() -> Result:
    node = shutil.which("node")

    if not node:
        return Result(
            "JavaScript",
            "AVISO",
            "Node.js no está disponible; no se verificó la sintaxis",
        )

    files = sorted((ROOT / "frontend" / "js").glob("*.js"))

    if not files:
        return Result(
            "JavaScript",
            "ERROR",
            "No se encontraron archivos JavaScript",
        )

    failures = []

    for filename in files:
        outcome = run_command(
            [node, "--check", str(filename)],
            timeout=20,
        )

        if outcome is None or outcome.returncode:
            failures.append(filename.name)

    if failures:
        return Result(
            "JavaScript",
            "ERROR",
            "Error de sintaxis en: " + ", ".join(failures),
        )

    return Result(
        "JavaScript",
        "OK",
        f"{len(files)} archivos JS sin errores de sintaxis",
    )


def check_pytest() -> Result:
    outcome = run_command(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        timeout=300,
    )

    if outcome is None:
        return Result(
            "Pytest",
            "ERROR",
            "No se pudo ejecutar o superó el tiempo máximo",
        )

    lines = [
        line.strip()
        for line in outcome.stdout.splitlines()
        if line.strip()
    ]

    summary = next(
        (
            line
            for line in reversed(lines)
            if " passed" in line
            or " failed" in line
            or " error" in line
        ),
        None,
    )

    if not summary:
        fallback = (
            outcome.stderr
            or outcome.stdout
            or "Pytest no proporcionó un resumen"
        )
        summary = fallback.strip().splitlines()[-1]

    return Result(
        "Pytest",
        "OK" if outcome.returncode == 0 else "ERROR",
        summary,
    )


def diagnose(*, run_tests: bool = True, db_path: str | None = None) -> list[Result]:
    results = [
        check_structure(),
        check_python(),
        check_dependencies(),
        check_timezone(),
        check_git_privacy(),
        check_javascript(),
        check_totp_key(db_path),
    ]

    if run_tests:
        results.append(check_pytest())
    else:
        results.append(
            Result(
                "Pytest",
                "AVISO",
                "Omitido por --sin-pruebas",
            )
        )

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verificación local y segura de R.E.I.G.E.L."
    )

    parser.add_argument(
        "--sin-pruebas",
        action="store_true",
        help="Omite Pytest para una revisión rápida",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Resultado estructurado para automatización",
    )

    parser.add_argument(
        "--base",
        help="Base que usará el servidor; comprueba su clave de Google Authenticator (solo lectura)",
    )

    args = parser.parse_args(argv)
    extra = {"db_path": args.base} if args.base else {}
    results = diagnose(run_tests=not args.sin_pruebas, **extra)
    success = all(result.status != "ERROR" for result in results)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": success,
                    "checks": [asdict(result) for result in results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("R.E.I.G.E.L. | Diagnóstico local (sin conexiones comerciales)")

        for result in results:
            print(f"[{result.status}] {result.check}: {result.detail}")

        print("RESULTADO:", "APROBADO" if success else "REQUIERE CORRECCIÓN")

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
