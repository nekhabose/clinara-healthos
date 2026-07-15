from django.apps import AppConfig


class KillSwitchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.killswitch"
    label = "killswitch"
    verbose_name = "Kill Switch"
