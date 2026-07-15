from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.audit"
    label = "audit"
    verbose_name = "Audit"
