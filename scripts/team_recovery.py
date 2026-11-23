"""Emit a one-time, audited Team recovery code from the server host."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reigel.core import DomainError, Store  # noqa: E402
from reigel.identity import Identity  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Ruta explícita de la base de datos")
    parser.add_argument("--email", required=True)
    parser.add_argument("--motivo", required=True)
    args = parser.parse_args()
    if not Path(args.db).is_file():
        print("No existe esa base de datos.", file=sys.stderr)
        return 2
    try:
        grant = Identity(Store(args.db)).local_recovery(args.email, args.motivo)
    except DomainError as error:
        print(error.detail, file=sys.stderr)
        return 1
    print(f"Código de un solo uso: {grant['code']}\nVence: {grant['expires_at']}\nÚsalo en /app/acceso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
