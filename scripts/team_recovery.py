"""Emit a one-time, audited Team access code from the server host.

This is the only way to obtain the owner's own codes: the first Google
Authenticator registration ("--purpose enroll", an invitation code) or a
replacement after losing the phone ("--purpose recovery"). It needs console
access to the server and to the database; there is no HTTP route for it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reigel.core import DomainError, Store  # noqa: E402
from reigel.identity import GRANT_MINUTES, INVITE_HOURS, Identity  # noqa: E402

LABELS = {"enroll": "invitación (primer registro de Google Authenticator)", "recovery": "recuperación (reemplaza el autenticador)"}


def main(argv=None, ask=input) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Ruta explícita de la base de datos")
    parser.add_argument("--email", required=True)
    parser.add_argument("--motivo", required=True)
    parser.add_argument("--purpose", choices=sorted(LABELS), default="recovery",
                        help="enroll: código de invitación para el primer registro; recovery: reemplazo del autenticador")
    parser.add_argument("--yes", action="store_true", help="Confirma sin pregunta interactiva")
    args = parser.parse_args(argv)
    if not Path(args.db).is_file():
        print("No existe esa base de datos.", file=sys.stderr)
        return 2
    validity = f"{INVITE_HOURS} horas" if args.purpose == "enroll" else f"{GRANT_MINUTES} minutos"
    print(f"ATENCIÓN: vas a emitir un código de {LABELS[args.purpose]} para {args.email}.\n"
          "Con ese código y la contraseña de la cuenta se puede registrar un autenticador nuevo.\n"
          f"Es de un solo uso, vence en {validity}, anula cualquier código anterior de la cuenta y queda en la auditoría.\n"
          "Entrégalo en persona. No lo envíes por correo, chat ni capturas de pantalla.", file=sys.stderr)
    if not args.yes:
        if ask is input and (not sys.stdin or not sys.stdin.isatty()):
            print("Sin confirmación interactiva: vuelve a ejecutar con --yes si estás seguro.", file=sys.stderr)
            return 3
        if ask("Escribe SI para continuar: ").strip().upper() != "SI":
            print("Cancelado. No se emitió ningún código.", file=sys.stderr)
            return 3
    try:
        grant = Identity(Store(args.db)).local_grant(args.email, args.motivo, args.purpose)
    except DomainError as error:
        print(error.detail, file=sys.stderr)
        return 1
    print(f"Código de un solo uso: {grant['code']}\nVence: {grant['expires_at']}\n"
          "Úsalo al entrar en /app (paso «código de invitación») o en /app/acceso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
