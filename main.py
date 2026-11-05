"""Application entry point: python -m uvicorn main:app --port 8765."""

from reigel.api import create_app

app = create_app()
