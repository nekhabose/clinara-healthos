"""Demo settings — run the full stack locally with no external services.

Uses a file-backed SQLite database (so data persists across the seed step and the running
server) and mounts the demo console. RLS is a Postgres-only guarantee and is a no-op on
SQLite (see core.rls); tenant isolation is still enforced at the application layer, which is
what the console demonstrates. This module is for local demos only — never production.
"""
from __future__ import annotations

from pathlib import Path

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, TEMPLATES

DEBUG = True
ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(Path(BASE_DIR) / "demo.sqlite3"),
    }
}

# Serve the demo console templates.
TEMPLATES[0]["DIRS"] = [str(Path(BASE_DIR) / "clinara" / "templates")]

# The console is same-origin, so DRF SessionAuthentication + CSRF works without CORS.
