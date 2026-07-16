from django.apps import AppConfig


class EmbeddedConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.embedded"
    label = "embedded"
    verbose_name = "EHR-Embedded Surface"
