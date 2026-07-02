"""Uvicorn entrypoint — `uvicorn app.main:app`."""

from app.api.routes import app

__all__ = ["app"]
