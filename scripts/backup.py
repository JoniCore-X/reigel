"""Consistent SQLite backup taken before anything touches the database.

Never copy a live WAL database as a plain file, and never build ``Store`` here:
its constructor applies the schema and migrations, so a backup meant to precede
a migration would capture the database after it. The source is opened
read-only and copied with SQLite's online backup API.

The Google Authenticator key (``<base>.totp.key``) is copied next to the copy as
``<copia>.totp.key``, so both files can be restored together. Without that key the
registered authenticators cannot be read. When the key comes from the
``REIGEL_TOTP_KEY`` variable it is in no file and is not copied.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
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
    key_source = Path(f"{source}.totp.key")
    key_destination = Path(f"{destination}.totp.key")
    if destination == source or destination.exists() or key_destination.exists():
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
        try:
            enrolled = src.execute("SELECT count(*) FROM team_totp").fetchone()[0]
        except sqlite3.Error:
            enrolled = 0  # a database from before Google Authenticator existed
        if key_source.is_file():
            shutil.copyfile(key_source, key_destination)
            key_destination.chmod(0o600)
    except BaseException:
        destination.unlink(missing_ok=True)
        key_destination.unlink(missing_ok=True)
        raise
    finally:
        src.close()

    destination.chmod(0o600)
    with destination.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    print(f"Copia verificada: {destination}\nSHA256: {digest}")
    if key_destination.is_file():
        print(f"Clave de Google Authenticator copiada: {key_destination}\n"
              "ATENCIÓN: guarda esta clave por separado y en un lugar seguro. Quien tenga la copia y la clave puede leer "
              "los secretos de Google Authenticator. Para restaurar, conserva los dos archivos con el mismo nombre base "
              "(«BASE» y «BASE.totp.key») o define REIGEL_TOTP_KEY.")
    elif os.environ.get("REIGEL_TOTP_KEY", "").strip():
        print("RECORDATORIO: la clave de Google Authenticator viene de REIGEL_TOTP_KEY y no está en esta copia. "
              "Consérvala aparte; sin ella, nadie podrá entrar con Google Authenticator usando esta copia.")
    elif enrolled:
        print(f"ATENCIÓN: hay {enrolled} cuenta(s) con Google Authenticator, pero no se encontró la clave "
              f"({key_source.name} ni REIGEL_TOTP_KEY). Esta copia no permitirá leer esos autenticadores.")


if __name__ == "__main__":
    main()
