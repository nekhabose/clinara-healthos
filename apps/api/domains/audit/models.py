"""Immutable, hash-chained audit trail (spec §10.4).

Every state-changing action writes one AuditEvent with the mandatory field set. Records
are tamper-evident: each row stores the hash of the previous row plus its own content
hash, forming a per-tenant chain. Records are append-only — never updated or deleted.
"""
from __future__ import annotations

import uuid

from django.db import models


class AuditAction(models.TextChoices):
    # Auditable action types (spec §10.4).
    AUTHENTICATION = "authentication", "Authentication"
    PHI_ACCESS = "phi_access", "PHI access"
    RULE_CREATE = "rule_create", "Rule creation"
    RULE_MODIFY = "rule_modify", "Rule modification"
    RULE_APPROVE = "rule_approve", "Rule approval"
    RULE_DEPLOY = "rule_deploy", "Rule deployment"
    CONFIG_CHANGE = "config_change", "Configuration change"
    MAPPING_CHANGE = "mapping_change", "Mapping change"
    WORKFLOW_DECISION = "workflow_decision", "Workflow decision"
    LLM_USAGE = "llm_usage", "LLM usage"
    MESSAGE_DELIVERY = "message_delivery", "Message delivery"
    CLINICIAN_ACTION = "clinician_action", "Clinician action"
    ADMIN_EXPORT = "admin_export", "Administrative export"
    SUPPORT_ACCESS = "support_access", "Support access"
    DATA_PURGE = "data_purge", "Data purge"


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Mandatory fields (spec §10.4).
    actor = models.CharField(max_length=255)           # user id or system principal
    action = models.CharField(max_length=40, choices=AuditAction.choices, db_index=True)
    resource = models.CharField(max_length=255)        # type:id of the affected resource
    tenant_id = models.UUIDField(null=True, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    session = models.CharField(max_length=128, null=True, blank=True)
    before_state = models.JSONField(null=True, blank=True)
    after_state = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    correlation_id = models.CharField(max_length=64, db_index=True)

    # Tamper-evidence chain.
    prev_hash = models.CharField(max_length=64, null=True, blank=True)
    record_hash = models.CharField(max_length=64, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "timestamp"])]
        ordering = ["timestamp"]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor} on {self.resource}"
