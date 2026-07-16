"""Vercel serverless entrypoint for the Clinara Django app.

Vercel's Python runtime imports this module and serves the WSGI callable exported as ``app``.
The Django project lives under ``apps/api``; the shared clinical packages under ``packages`` are
installed from ``requirements.txt``. Every request is routed here by ``vercel.json``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_DIR = _REPO_ROOT / "apps" / "api"

# Make the Django project importable (settings, clinara.*, domains.*, core.*).
sys.path.insert(0, str(_API_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "clinara.settings.vercel")

from clinara.wsgi import application  # noqa: E402

# Vercel's @vercel/python runtime serves a WSGI/ASGI callable named ``app``.
app = application
