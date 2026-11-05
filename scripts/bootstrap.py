"""Create the first administrator, without a shared/default password."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reigel.api import load_environment
from reigel.core import DomainError, Store


def main():
    parser = argparse.ArgumentParser(description="Crear el primer administrador de Power Solar")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Power Solar")
    args = parser.parse_args()
    load_environment()
    password = secrets.token_urlsafe(24)
    store = Store()
    try:
        user = store.create_user({"email": args.email, "name": args.name, "password": password, "role": "admin"}, bootstrap=True)
    except DomainError as exc:
        print(exc.detail, file=sys.stderr)
        return 1
    output = Path(store.path).resolve().parent / "local-access.txt"
    output.write_text("Power Solar · acceso local\n\nURL: http://127.0.0.1:8765/app\nCorreo: " + user["email"] + "\nContraseña: " + password + "\n\nCambia la contraseña al entrar y elimina este archivo. No lo compartas ni lo subas al repositorio.\n", encoding="utf-8")
    try:
        os.chmod(output, 0o600)
    except OSError:
        pass
    print(f"Administrador creado. Credenciales locales: {output}. Cámbialas al iniciar sesión.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
