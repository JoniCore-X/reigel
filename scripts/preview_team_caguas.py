r"""Run an isolated, synthetic preview; never load .env or the commercial database.

Usage: .\.venv\Scripts\python.exe scripts\preview_team_caguas.py --port 8877
The generated SQLite directory is outside the repository and is retained on exit.
All accounts below belong solely to the new local preview.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PREVIEW_EMAIL = "admin@team-caguas.test"
PREVIEW_PASSWORD = "Preview-Caguas-2026!"
ADVISOR_EMAIL = "asesor@team-caguas.test"
ADVISOR_PASSWORD = "Preview-Asesor-2026!"


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

    store = app.state.store
    admin = store.create_user({"name": "Administración · DEMO", "email": PREVIEW_EMAIL, "password": PREVIEW_PASSWORD, "role": "admin"}, bootstrap=True)
    advisor = store.create_user({"name": "Asesor · DEMO", "email": ADVISOR_EMAIL, "password": ADVISOR_PASSWORD}, admin)
    store.create_user({"name": "Otro asesor · DEMO", "email": "otro@team-caguas.test", "password": "Preview-Otro-2026!"}, admin)
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
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("El puerto debe estar entre 1024 y 65535.")
    import uvicorn

    app, directory = build_preview()
    print(f"DEMO SINTÉTICA: http://127.0.0.1:{args.port}/app", flush=True)
    print(f"Base aislada: {directory}", flush=True)
    print(f"Acceso de prueba: {PREVIEW_EMAIL} / {PREVIEW_PASSWORD}", flush=True)
    print("No se cargó .env, no se abrió la base comercial y no se programan refrescos externos.", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
