"""
bank/signals.py — обновлённая версия.
Добавлен вызов apply_cashback после доставки.
Полностью замени свой bank/signals.py на этот файл.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

from orders.models import Order

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Order)
def on_order_status_change(sender, instance, created, **kwargs):
    """
    Когда заказ → 'delivered':
      1. Размораживаем деньги продавца (confirm_delivery)
      2. Начисляем кэшбэк клиенту (apply_cashback — заглушка пока отключена)
    """
    if created:
        return

    update_fields = kwargs.get('update_fields')
    if update_fields and 'status' not in update_fields:
        return

    if instance.status != 'delivered':
        return

    from bank.services import confirm_delivery, apply_cashback
    from bank.models import FrozenBalance

    # 1. Разморозка продавца
    has_frozen = FrozenBalance.objects.filter(
        order=instance,
        is_released=False,
        payout_request__isnull=True,  # только заморозки по заказу, не по выводу
    ).exists()

    if has_frozen:
        try:
            confirm_delivery(order=instance)
        except Exception as e:
            logger.error(f'[bank.signals] Ошибка разморозки заказ #{instance.id}: {e}')

    # 2. Кэшбэк клиенту (заглушка — не сработает пока is_active=False)
    try:
        apply_cashback(order=instance, buyer=instance.client)
    except Exception as e:
        logger.error(f'[bank.signals] Ошибка кэшбэка заказ #{instance.id}: {e}')