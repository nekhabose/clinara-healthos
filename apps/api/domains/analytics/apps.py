from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.analytics"
    label = "analytics"
    verbose_name = "Analytics"
