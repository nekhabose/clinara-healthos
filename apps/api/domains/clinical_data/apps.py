from django.apps import AppConfig


class ClinicalDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.clinical_data"
    label = "clinical_data"
    verbose_name = "Clinical Data"
