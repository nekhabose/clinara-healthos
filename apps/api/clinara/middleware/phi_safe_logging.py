"""PHI-safe, structured logging (spec §10.3, plan cross-cutting foundations).

- ``CorrelationIdMiddleware`` stamps a correlation id on every request.
- ``CorrelationIdFilter`` / ``CorrelationIdMiddleware`` propagate it into log records.
- ``PhiScrubFilter`` redacts values that look like PHI before anything is emitted.
- ``JsonFormatter`` renders one structured JSON object per line.

The scrubber is a defense-in-depth backstop: code must never log PHI in the first place.
CI includes a lint that flags obvious PHI in log calls.
"""
from __future__ import annotations

import contextvars
import datetime as _dt
import json
import logging
import re
import uuid

from django.utils.deprecation import MiddlewareMixin

correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)

# Keys whose values must never be logged, and patterns that look like PHI.
_REDACT_KEYS = re.compile(
    r"(?i)(ssn|mrn|dob|birth|phone|email|address|first_?name|last_?name|patient_name)"
)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_REDACTED = "[REDACTED]"


def scrub(value: object) -> object:
    """Recursively redact obvious PHI from a value."""
    if isinstance(value, dict):
        return {k: (_REDACTED if _REDACT_KEYS.search(k) else scrub(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return _EMAIL.sub(_REDACTED, _SSN.sub(_REDACTED, value))
    return value


class PhiScrubFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.msg)
        if isinstance(record.args, dict):
            record.args = scrub(record.args)
        return True


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        return json.dumps(payload, default=str)


class CorrelationIdMiddleware(MiddlewareMixin):
    HEADER = "HTTP_X_CORRELATION_ID"

    def process_request(self, request) -> None:
        cid = request.META.get(self.HEADER) or str(uuid.uuid4())
        correlation_id.set(cid)
        request.correlation_id = cid

    def process_response(self, request, response):
        cid = getattr(request, "correlation_id", None)
        if cid:
            response["X-Correlation-Id"] = cid
        return response
