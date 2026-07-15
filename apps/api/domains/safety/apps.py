from django.apps import AppConfig


class SafetyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.safety"
    label = "safety"
    verbose_name = "Safety"
