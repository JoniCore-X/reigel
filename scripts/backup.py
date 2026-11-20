"""Consistent SQLite backup taken before anything touches the database.

Never copy a live WAL database as a plain file, and never build ``Store`` here:
its constructor applies the schema and migrations, so a backup meant to precede
a migration would capture the database after it. The source is opened
read-only and copied with SQLite's online backup API.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reigel.api import load_environment
from reigel.core import default_db_path


def main():
    parser = argparse.ArgumentParser(description="Copia consistente de la base de Power Solar")
    parser.add_argument("--db", help="Base de origen; por defecto REIGEL_DB_PATH o la carpeta privada de PowerSolar")
    parser.add_argument("--output", help="Ruta de un archivo nuevo, fuera de carpetas públicas")
    args = parser.parse_args()
    if not args.db:
        load_environment()  # only to resolve REIGEL_DB_PATH; nothing else is read
    source = Path(default_db_path(args.db)).resolve()
    if not source.is_file():
        parser.error(f"No existe la base de origen: {source}. No se creó ninguna base ni copia.")
    default_name = datetime.now(UTC).strftime("powersolar-%Y%m%dT%H%M%S%fZ") + ".db"
    destination = (Path(args.output) if args.output else source.parent / "backups" / default_name).resolve()
    if destination == source or destination.exists():
        parser.error("La copia debe usar un archivo nuevo, distinto de la base activa.")
    destination.parent.mkdir(parents=True, exist_ok=True)

    src = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=15)
    try:
        dst = sqlite3.connect(str(destination))
        try:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Falló la verificación de integridad de la copia.")
        finally:
            dst.close()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        src.close()

    destination.chmod(0o600)
    with destination.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    print(f"Copia verificada: {destination}\nSHA256: {digest}")


if __name__ == "__main__":
    main()
