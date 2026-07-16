"""Kill-switch persistence (GA hardening — spec §11.4).

A kill switch is a platform-level emergency control, so it is intentionally NOT tenant-scoped
in the RLS sense — a GLOBAL switch must be visible to every request, and a platform operator
engaging a TENANT switch acts across the tenant boundary. Rows carry an explicit ``target``
instead. The active set is loaded and passed to ``killswitch.core.resolve``.
"""
from __future__ import annotations

import uuid

from clinara_shared_types import KillSwitchScope
from django.db import models

SCOPE_CHOICES = [(s.value, s.name.title()) for s in KillSwitchScope]


class KillSwitchRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=32, choices=SCOPE_CHOICES, db_index=True)
    # Identifier within the scope; "*" (or GLOBAL) covers the whole scope.
    target = models.CharField(max_length=200, default="*")
    active = models.BooleanField(default=True, db_index=True)
    reason = models.TextField(blank=True, default="")
    engaged_by = models.CharField(max_length=200, blank=True, default="")
    engaged_at = models.DateTimeField(auto_now_add=True)
    released_by = models.CharField(max_length=200, blank=True, default="")
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["active", "scope"])]
        constraints = [
            # At most one active switch per (scope, target) — re-engaging is idempotent.
            models.UniqueConstraint(
                fields=["scope", "target"],
                condition=models.Q(active=True),
                name="uniq_active_killswitch_per_scope_target",
            )
        ]
        ordering = ["-engaged_at"]

    def __str__(self) -> str:
        state = "active" if self.active else "released"
        return f"{self.scope}:{self.target}[{state}]"
