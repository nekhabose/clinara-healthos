"""HTTP transport seam for outbound EMR calls (plan Phase 7 — Real EMR Connectivity).

Every network call the SMART auth client and the FHIR write-back client make goes through
the ``HttpTransport`` protocol. This is the same injection discipline the rest of the SDK
uses (an injected clock for rate limiting, an injected ``EhrClient`` for delivery): the
*logic* is pure and unit-testable against a fake transport, and a real deployment swaps in
``UrllibTransport`` (stdlib only — no third-party HTTP dependency) or any conforming client.

Keeping the transport abstract is what lets Phase 7 be validated end-to-end against
vendor-emulating fakes today and pointed at a live Epic/Athena endpoint by configuration
alone, with zero change to the auth or write-back logic.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol


class TransportError(RuntimeError):
    """A network-level failure (connection refused, timeout, DNS). Distinct from an HTTP
    error response, which is a normal ``HttpResponse`` the caller inspects by status."""


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else None

    def header(self, name: str) -> str | None:
        """Case-insensitive header lookup (HTTP header names are case-insensitive)."""
        lname = name.lower()
        for k, v in self.headers.items():
            if k.lower() == lname:
                return v
        return None


class HttpTransport(Protocol):
    def request(self, req: HttpRequest) -> HttpResponse:
        """Perform one HTTP request. Raise ``TransportError`` on a network failure; return an
        ``HttpResponse`` (any status) otherwise — HTTP errors are data, not exceptions."""
        ...


class UrllibTransport:
    """Production transport backed by the standard library only (no ``requests``/``httpx``).

    HTTP error statuses (4xx/5xx) are returned as ``HttpResponse`` so the write-back client
    can classify them (retryable vs terminal). Only genuine network failures raise
    ``TransportError``.
    """

    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        self._timeout = timeout_seconds

    def request(self, req: HttpRequest) -> HttpResponse:
        request = urllib.request.Request(
            req.url, data=req.body, headers=req.headers, method=req.method
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                return HttpResponse(
                    status=resp.status,
                    headers={k: v for k, v in resp.headers.items()},
                    body=resp.read(),
                )
        except urllib.error.HTTPError as exc:  # an HTTP error response — return it as data
            return HttpResponse(
                status=exc.code,
                headers={k: v for k, v in (exc.headers or {}).items()},
                body=exc.read() if hasattr(exc, "read") else b"",
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:  # network-level failure
            raise TransportError(str(exc)) from exc


__all__ = [
    "HttpRequest",
    "HttpResponse",
    "HttpTransport",
    "UrllibTransport",
    "TransportError",
]
