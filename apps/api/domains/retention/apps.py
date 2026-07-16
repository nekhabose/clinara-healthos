from django.apps import AppConfig


class RetentionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.retention"
    label = "retention"
    verbose_name = "Data Lifecycle & Compliance Hardening"
