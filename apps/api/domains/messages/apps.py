from django.apps import AppConfig


class MessagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.messages"
    label = "patient_messages"  # avoid clashing with django.contrib.messages
    verbose_name = "Patient Messages"
