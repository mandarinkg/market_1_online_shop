"""
bank/apps.py
"""

from django.apps import AppConfig


class BankConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bank'
    verbose_name = 'Биллинговая система'

    def ready(self):
        import bank.signals  # noqa — подключаем сигналы