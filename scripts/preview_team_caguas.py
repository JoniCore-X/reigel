r"""Run an isolated, synthetic preview; never load .env or the commercial database.

Usage: .\.venv\Scripts\python.exe scripts\preview_team_caguas.py --port 8877
The generated SQLite directory is outside the repository and is retained on exit.
All accounts below belong solely to the new local preview.

Google Authenticator is mandatory for every team account. Only here, in the
synthetic preview, two demo accounts are pre-enrolled with a random secret that
is generated for this run and printed with the demo passwords; a third account
is left without it to show the first registration, which needs the password and
a one-time invitation code (synthetic, printed only by this preview) before the
QR appears. To compute the current
code without a phone:  python scripts\preview_team_caguas.py --codigo SECRETO
"""
from __future__ import annotations

import argparse
import base64
import os
import time
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Synthetic example.com accounts; each contains "powersolar" so the naming rule stays on.
PREVIEW_EMAIL = "admin.powersolar@example.com"
PREVIEW_PASSWORD = "Preview-Caguas-2026!"
ADVISOR_EMAIL = "asesor.powersolar@example.com"
ADVISOR_PASSWORD = "Preview-Asesor-2026!"
NEW_EMAIL = "nuevo.powersolar@example.com"
NEW_PASSWORD = "Preview-Nuevo-2026!"
# Filled by build_preview() with a fresh random secret per run (base32, as Google Authenticator shows it).
PREVIEW_TOTP_SECRET = ""
ADVISOR_TOTP_SECRET = ""
# Filled by build_preview(): invitation code of the synthetic account without Google Authenticator.
NEW_INVITATION_CODE = ""


def current_code(secret: str) -> str:
    """Current 6-digit code for a synthetic preview secret."""
    from reigel import totp
    raw = base64.b32decode(secret.replace(" ", "").upper() + "=" * (-len(secret.replace(" ", "")) % 8))
    return totp.code_at(raw, int(time.time() // totp.PERIOD))


def _pre_enroll(app, user) -> str:
    """SYNTHETIC PREVIEW ONLY: register Google Authenticator for a demo account so the
    printed secret works at once. Real accounts always enroll through the QR flow."""
    from reigel import totp
    from reigel.core import stamp
    assert getattr(app.state, "synthetic_preview", False), "Solo la demostración sintética preinscribe Google Authenticator."
    secret = totp.new_secret()
    nonce, cipher = app.state.identity._seal(secret, user["id"])
    with app.state.store.connect() as db:
        db.execute("INSERT INTO team_totp(user_id,secret_nonce,secret_cipher,last_step,confirmed_at) VALUES(?,?,?,?,?)",
                   (user["id"], nonce, cipher, -1, stamp()))
        app.state.store.audit(db, None, "preview.totp_pre_enrolled", user["id"])
    return totp.display_secret(secret)


def build_preview():
    from reigel import api
    from reigel.channels import CONFIG

    # Scope every override to this construction; no persistent configuration writes.
    environment = {"REIGEL_ENV": "local", "SITE_URL": "", "REIGEL_ALLOWED_HOSTS": ""}
    for channel, (_, keys, _) in CONFIG.items():
        if channel != "ai":
            environment.update({key: "" for key in keys})
    directory = Path(tempfile.mkdtemp(prefix="reigel-team-caguas-preview-"))
    with patch.dict(os.environ, environment), patch.object(api, "load_environment", lambda: None):
        app = api.create_app(directory / "preview.sqlite3")
    app.state.synthetic_preview = True
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def preview_boundaries(request, call_next):
        if request.url.path.startswith("/webhooks/") or request.url.path == "/api/knowledge/refresh":
            return JSONResponse({"detail": "Esta demostración sintética no recibe webhooks ni actualiza fuentes externas."}, status_code=503)
        return await call_next(request)

    global PREVIEW_TOTP_SECRET, ADVISOR_TOTP_SECRET, NEW_INVITATION_CODE
    store = app.state.store
    admin = store.create_user({"name": "Administración · DEMO", "email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD, "role": "admin"}, bootstrap=True)
    for email in (ADVISOR_EMAIL, NEW_EMAIL):
        store.allow_team_email(email, admin)
    advisor = store.create_user({"name": "Asesor · DEMO", "email": ADVISOR_EMAIL, "password": ADVISOR_PASSWORD}, admin)
    newcomer = store.create_user({"name": "Asesor nuevo · DEMO", "email": NEW_EMAIL, "password": NEW_PASSWORD}, admin)
    PREVIEW_TOTP_SECRET = _pre_enroll(app, admin)
    ADVISOR_TOTP_SECRET = _pre_enroll(app, advisor)
    # Same audited path an administrator uses in /app; synthetic and valid only in this temporary base.
    NEW_INVITATION_CODE = app.state.identity.issue_grant(newcomer["id"], "enroll", "Demostración sintética", admin)["code"]
    store.update_user(advisor["id"], {"public_booking": True, "work_days": list(range(7))}, admin)
    lead = store.create_lead({"name": "Prospecto ficticio · DEMO", "email": "persona@example.test", "phone": "+17875550100", "municipality": "Caguas", "monthly_bill": 180, "consent": True, "advisor_id": advisor["id"]}, admin)
    day = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    slot = store.slots(advisor["id"], day)["slots"][0]
    store.book({"lead_id": lead["id"], "advisor_id": advisor["id"], "start_at": slot["start_at"]}, source="equipo", actor=admin)
    # A visible, honest label appears in every workspace view. Seed records are synthetic.
    store.update_settings({"market": "Puerto Rico · DEMO SINTÉTICA"}, admin)
    return app, directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--codigo", metavar="SECRETO", help="Muestra el código actual de una clave sintética de esta demostración y termina.")
    parser.add_argument(
        "--host-publico",
        default="",
        metavar="NOMBRE",
        help="Nombre de host externo que esta demostración acepta, para publicarla tras un túnel "
             "(por ejemplo algo.trycloudflare.com). Solo afecta a este proceso y no escribe nada.",
    )
    parser.add_argument(
        "--ia-local",
        action="store_true",
        help="Activa la IA con Ollama local (127.0.0.1:11434) solo en este proceso; no descarga modelos ni lee .env.",
    )
    parser.add_argument(
        "--ia-modelo",
        default="",
        help="Modelo local ya instalado para esta vista previa (por ejemplo llama3.2:3b). No lo descarga.",
    )
    args = parser.parse_args()
    if args.codigo:
        print(current_code(args.codigo), flush=True)
        return
    if not 1024 <= args.port <= 65535:
        parser.error("El puerto debe estar entre 1024 y 65535.")
    import uvicorn

    app, directory = build_preview()
    if args.host_publico:
        # Se lee en cada petición en api.py, así que no sirve fijarlo solo durante la
        # construcción: `patch.dict` ya habría salido. Ámbito: este proceso.
        os.environ["REIGEL_ALLOWED_HOSTS"] = args.host_publico.strip().lower()
    if args.ia_local:
        # Read at request time by ai_chat.enabled(); scoped to this process only.
        os.environ["REIGEL_CHAT_AI"] = "ollama"
        if args.ia_modelo:
            os.environ["REIGEL_CHAT_MODEL"] = args.ia_modelo
    print(f"DEMO SINTÉTICA: http://127.0.0.1:{args.port}/app", flush=True)
    print(f"Base aislada: {directory}", flush=True)
    print(f"Acceso de prueba (propietario): {PREVIEW_EMAIL} / {PREVIEW_PASSWORD}", flush=True)
    print(f"  Google Authenticator sintético: {PREVIEW_TOTP_SECRET}", flush=True)
    print(f"Acceso de prueba (asesor): {ADVISOR_EMAIL} / {ADVISOR_PASSWORD}", flush=True)
    print(f"  Google Authenticator sintético: {ADVISOR_TOTP_SECRET}", flush=True)
    print(f"Primer acceso con registro QR obligatorio: {NEW_EMAIL} / {NEW_PASSWORD}", flush=True)
    print(f"  Código de invitación sintético (un solo uso): {NEW_INVITATION_CODE}", flush=True)
    print(r"Código actual sin teléfono: .venv\Scripts\python.exe scripts\preview_team_caguas.py --codigo CLAVE", flush=True)
    print("Estas claves solo existen en esta base sintética temporal.", flush=True)
    print("No se cargó .env, no se abrió la base comercial y no se programan refrescos externos.", flush=True)
    if args.ia_local:
        print(f"IA local activada en este proceso (Ollama en 127.0.0.1:11434, modelo {os.environ.get('REIGEL_CHAT_MODEL') or 'qwen2.5:3b'}).", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
