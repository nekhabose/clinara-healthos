"""Test settings.

Defaults to in-memory SQLite so the suite runs anywhere (CI, laptops) with no external
services. PostgreSQL-specific guarantees — Row-Level Security, the non-superuser role — are
exercised by opting in with ``CLINARA_TEST_DB=postgres`` (used by the dockerized
``make test`` and the tenant-isolation CI job). RLS migration operations are no-ops on
SQLite (see core.rls), so migrations apply identically on both backends.
"""
import os

from .base import *  # noqa: F401,F403

DEBUG = True

if os.environ.get("CLINARA_TEST_DB") == "postgres":
    pass  # inherit the PostgreSQL DATABASES from base (RLS enforced)
else:
    DATABASES = {  # noqa: F405
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    }

# Fast, insecure hasher — tests only.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
