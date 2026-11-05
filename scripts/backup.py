"""Consistent SQLite backup; never copy a live WAL database as a plain file."""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reigel.api import load_environment
from reigel.core import Store


def main():
    parser = argparse.ArgumentParser(description="Copia consistente de la base de Power Solar")
    parser.add_argument("--output", help="Ruta de un archivo nuevo, fuera de carpetas públicas")
    args = parser.parse_args()
    load_environment()
    store = Store()
    destination = Path(args.output) if args.output else Path(store.path).parent / "backups" / (datetime.now(UTC).strftime("powersolar-%Y%m%dT%H%M%S%fZ") + ".db")
    source = Path(store.path).resolve()
    destination = destination.resolve()
    if destination == source or destination.exists():
        parser.error("La copia debe usar un archivo nuevo, distinto de la base activa.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with store.connect() as src, sqlite3.connect(str(destination)) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Falló la verificación de integridad de la copia.")
    destination.chmod(0o600)
    digest = hashlib.file_digest(destination.open("rb"), "sha256").hexdigest()
    print(f"Copia verificada: {destination}\nSHA256: {digest}")


if __name__ == "__main__":
    main()
