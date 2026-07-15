"""Local development settings."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Convenience for local: allow the app to connect as the bootstrap superuser if the
# dedicated non-superuser role hasn't been provisioned yet. RLS is still exercised in CI.
if env.bool("DJANGO_LOCAL_SUPERUSER_DB", default=False):
    DATABASES["default"]["USER"] = "postgres"  # noqa: F405
    DATABASES["default"]["PASSWORD"] = "postgres"  # noqa: F405
