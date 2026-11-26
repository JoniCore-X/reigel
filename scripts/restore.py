"""Restore a verified backup of the database and its Google Authenticator key.

The server must be stopped: this script cannot detect a running server, and
replacing an open SQLite database corrupts it. Like ``backup.py`` it never
builds ``Store``; schema and additive migrations apply when the server starts.

It fails closed in the same way the server does. A copy that holds registered
authenticators is only restored when the key that will be used afterwards
(``REIGEL_TOTP_KEY`` or the ``<copia>.totp.key`` file) really opens every one of
them. Nothing is deleted: the database being replaced, its WAL files and its key
are moved to a dated folder next to it. The key is never printed.

    python scripts/restore.py --from COPIA.db --db DESTINO.db --check
    python scripts/restore.py --from COPIA.db --key COPIA.db.totp.key --db DESTINO.db
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

from cryptography.exceptions import InvalidTag  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

from reigel.core import DomainError  # noqa: E402
from reigel.identity import TOTP_KEY_ENV, decode_totp_key  # noqa: E402


class RestoreError(Exception):
    pass


def read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=15)


def authenticators(connection: sqlite3.Connection) -> list[tuple]:
    """Confirmed authenticators; a database from before Google Authenticator has none."""
    try:
        return connection.execute("SELECT user_id,secret_nonce,secret_cipher FROM team_totp").fetchall()
    except sqlite3.Error:
        return []


def resolve_key(copy: Path, key_file: str | None) -> tuple[bytes | None, str, Path | None]:
    """The key the server will use after the restore: the variable wins over any file."""
    configured = os.environ.get(TOTP_KEY_ENV, "").strip()
    if configured:
        try:
            return decode_totp_key(configured), f"variable {TOTP_KEY_ENV}", None
        except DomainError:
            raise RestoreError(f"{TOTP_KEY_ENV} no es una clave válida (base64 de 32 bytes exactos).") from None
    path = Path(key_file) if key_file else Path(f"{copy}.totp.key")
    if not path.is_file():
        if key_file:
            raise RestoreError(f"No existe el archivo de clave indicado: {path.name}")
        return None, "sin clave", None
    key = path.read_bytes()
    if len(key) != 32:
        raise RestoreError(f"El archivo de clave {path.name} no tiene 32 bytes; no es la clave original.")
    return key, f"archivo {path.name}", path


def verify(copy: Path, key_file: str | None, allow_without_key: bool) -> tuple[int, str, Path | None]:
    """Integrity of the copy and proof that the key opens its authenticators."""
    if not copy.is_file():
        raise RestoreError(f"No existe la copia: {copy}")
    source = read_only(copy)
    try:
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RestoreError("La copia no supera la verificación de integridad de SQLite.")
        rows = authenticators(source)
    except sqlite3.DatabaseError:
        raise RestoreError("La copia no es una base SQLite legible.") from None
    finally:
        source.close()
    key, origin, key_path = resolve_key(copy, key_file)
    if not rows:
        return 0, origin, key_path
    if key is None:
        if not allow_without_key:
            raise RestoreError(
                f"La copia tiene {len(rows)} cuenta(s) con Google Authenticator y no se encontró su clave "
                f"({copy.name}.totp.key, --key ni {TOTP_KEY_ENV}). No se restauró nada. Busca la clave original; "
                "solo si se perdió definitivamente, repite con --sin-clave y emite después un código de "
                "recuperación para cada persona con scripts/team_recovery.py.")
        return len(rows), "sin clave (cada persona necesitará un código de recuperación)", None
    cipher = AESGCM(key)
    try:
        for user_id, nonce, sealed in rows:
            cipher.decrypt(bytes(nonce), bytes(sealed), str(user_id).encode())
    except (InvalidTag, ValueError):
        raise RestoreError(
            "La clave no corresponde a esta copia: no abre los autenticadores registrados. No se restauró nada. "
            "Usa la clave que se guardó junto a esta misma copia.") from None
    return len(rows), origin, key_path


def restore(copy: Path, destination: Path, key_path: Path | None) -> Path | None:
    """Build the new database beside the destination, set the old files aside, then swap."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(destination.name + ".restaurando")
    staging.unlink(missing_ok=True)
    source = read_only(copy)
    try:
        target = sqlite3.connect(str(staging))
        try:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RestoreError("La base restaurada no supera la verificación de integridad.")
        finally:
            target.close()
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    finally:
        source.close()
    staging.chmod(0o600)

    previous = [Path(f"{destination}{suffix}") for suffix in ("", "-wal", "-shm", ".totp.key")]
    kept = None
    if any(path.exists() for path in previous):
        kept = destination.parent / datetime.now(UTC).strftime("antes-de-restaurar-%Y%m%dT%H%M%S%fZ")
        kept.mkdir(mode=0o700)
        for path in previous:
            if path.exists():
                shutil.move(str(path), str(kept / path.name))
    os.replace(staging, destination)
    if key_path is not None:
        key_destination = Path(f"{destination}.totp.key")
        shutil.copyfile(key_path, key_destination)
        key_destination.chmod(0o600)
    return kept


def main(argv=None, ask=input) -> int:
    parser = argparse.ArgumentParser(description="Restaurar una copia verificada de la base de Power Solar")
    parser.add_argument("--from", dest="copy", required=True, help="Copia creada con scripts/backup.py")
    parser.add_argument("--db", required=True, help="Ruta explícita de la base que usará el servidor")
    parser.add_argument("--key", help="Archivo de clave de la copia; por defecto COPIA.totp.key")
    parser.add_argument("--check", action="store_true", help="Solo verifica la copia y su clave; no cambia nada")
    parser.add_argument("--sin-clave", action="store_true",
                        help="Restaura aunque falte la clave: nadie podrá usar su autenticador actual")
    parser.add_argument("--yes", action="store_true", help="Confirma que el servidor está detenido")
    args = parser.parse_args(argv)
    copy, destination = Path(args.copy).resolve(), Path(args.db).resolve()
    try:
        if copy == destination:
            raise RestoreError("La copia y la base de destino son el mismo archivo.")
        enrolled, origin, key_path = verify(copy, args.key, args.sin_clave)
        with copy.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        print(f"Copia íntegra: {copy}\nSHA256: {digest}\n"
              f"Cuentas con Google Authenticator: {enrolled}. Clave: {origin}.")
        if args.check:
            print("Verificación terminada. No se cambió nada.")
            return 0
        print(f"ATENCIÓN: se va a reemplazar {destination}. El servidor debe estar DETENIDO.\n"
              "Lo que haya ahora en esa ruta se moverá a una carpeta «antes-de-restaurar-…»; no se borra.",
              file=sys.stderr)
        if not args.yes:
            if ask is input and (not sys.stdin or not sys.stdin.isatty()):
                print("Sin confirmación interactiva: repite con --yes si el servidor está detenido.", file=sys.stderr)
                return 3
            if ask("Escribe SI para continuar: ").strip().upper() != "SI":
                print("Cancelado. No se cambió nada.", file=sys.stderr)
                return 3
        kept = restore(copy, destination, key_path)
    except RestoreError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Base restaurada: {destination}")
    if key_path is not None:
        print(f"Clave de Google Authenticator restaurada junto a la base: {destination.name}.totp.key")
    if kept:
        print(f"Archivos anteriores conservados en: {kept}")
    print("Arranca el servidor: las migraciones aditivas se aplican al iniciar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
