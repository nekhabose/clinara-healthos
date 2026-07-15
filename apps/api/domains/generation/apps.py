from django.apps import AppConfig


class GenerationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.generation"
    label = "generation"
    verbose_name = "Generation"
