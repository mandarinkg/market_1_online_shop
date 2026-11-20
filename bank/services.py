"""
bank/services.py

Весь бизнес-логика банковских операций.

Правила:
  1. Все операции — внутри transaction.atomic()
  2. select_for_update() на Wallet перед любым изменением баланса
  3. LedgerEntry создаётся для каждого движения денег
  4. Никогда не менять LedgerEntry после создания
"""

from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import (
    Wallet,
    FrozenBalance,
    Transaction,
    LedgerEntry,
    PayoutRequest,
    PayoutStatus,
    TransactionType,
    EntryType,
    Currency,
    CashbackConfig,
)

from .models import TopUpRequest, TopUpStatus


# ==============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==============================================================================

def get_or_create_wallet(user, currency=Currency.KGS) -> Wallet:
    """Получить или создать кошелёк пользователя."""
    wallet, _ = Wallet.objects.get_or_create(
        user=user,
        currency=currency,
        defaults={'balance': Decimal('0.00')}
    )
    return wallet


def _create_ledger_entry(transaction_obj, wallet, entry_type, amount) -> LedgerEntry:
    """
    Создать запись в леджере и обновить баланс кошелька.
    Вызывать ТОЛЬКО внутри select_for_update() блока.
    """
    balance_before = wallet.balance

    if entry_type == EntryType.DEBIT:
        wallet.balance -= amount
    else:
        wallet.balance += amount

    if wallet.balance < 0:
        raise ValidationError(
            f'Недостаточно средств. Баланс: {balance_before}, списание: {amount}'
        )

    wallet.save(update_fields=['balance', 'updated_at'])

    return LedgerEntry.objects.create(
        transaction=transaction_obj,
        wallet=wallet,
        entry_type=entry_type,
        amount=amount,
        balance_before=balance_before,
        balance_after=wallet.balance,
    )


# ==============================================================================
# 1. ПОКУПКА ТОВАРА
# Покупатель платит → деньги замораживаются у продавца
# ==============================================================================

@transaction.atomic
def process_purchase(order, buyer, seller, amount: Decimal) -> Transaction:
    """
    Логика покупки:
      DEBIT  buyer_wallet       — списать у покупателя
      CREDIT seller_frozen      — заморозить у продавца

    select_for_update() блокирует строки кошельков до конца транзакции,
    исключая Race Condition когда два запроса одновременно меняют баланс.
    """
    if amount <= 0:
        raise ValidationError('Сумма покупки должна быть больше нуля.')

    # Блокируем оба кошелька одновременно (порядок по id — защита от дедлока)
    wallets = Wallet.objects.select_for_update().filter(
        user__in=[buyer, seller],
        currency=Currency.KGS,
    ).order_by('id')

    wallet_map = {w.user_id: w for w in wallets}

    buyer_wallet  = wallet_map.get(buyer.id)
    seller_wallet = wallet_map.get(seller.id)

    if not buyer_wallet:
        raise ValidationError('Кошелёк покупателя не найден.')
    if not seller_wallet:
        raise ValidationError('Кошелёк продавца не найден.')

    if buyer_wallet.balance < amount:
        raise ValidationError(
            f'Недостаточно средств. Баланс: {buyer_wallet.balance}, нужно: {amount}'
        )

    # Создаём транзакцию-группировщик
    txn = Transaction.objects.create(
        transaction_type=TransactionType.PURCHASE,
        order=order,
        initiated_by=buyer,
        description=f'Оплата заказа #{order.id}',
    )

    # DEBIT покупателя
    _create_ledger_entry(txn, buyer_wallet, EntryType.DEBIT, amount)

    # CREDIT продавца (в active wallet — для простоты учёта)
    # Деньги попадают на баланс, но тут же замораживаются через FrozenBalance
    _create_ledger_entry(txn, seller_wallet, EntryType.CREDIT, amount)

    # Замораживаем у продавца
    FrozenBalance.objects.create(
        wallet=seller_wallet,
        amount=amount,
        order=order,
    )

    # Сразу "убираем" из активного баланса продавца обратно
    # (баланс = доступные деньги, frozen не должен быть доступен)
    seller_wallet_locked = Wallet.objects.select_for_update().get(pk=seller_wallet.pk)
    balance_before = seller_wallet_locked.balance
    seller_wallet_locked.balance -= amount
    seller_wallet_locked.save(update_fields=['balance', 'updated_at'])

    # Доп. ledger запись — отражаем заморозку
    LedgerEntry.objects.create(
        transaction=txn,
        wallet=seller_wallet_locked,
        entry_type=EntryType.DEBIT,
        amount=amount,
        balance_before=balance_before,
        balance_after=seller_wallet_locked.balance,
    )

    return txn


# ==============================================================================
# 2. ПОДТВЕРЖДЕНИЕ ДОСТАВКИ
# Товар доставлен → размораживаем деньги продавца
# ==============================================================================

@transaction.atomic
def confirm_delivery(order, confirmed_by=None) -> Transaction:
    """
    Логика разморозки после доставки:
      Снимаем FrozenBalance → CREDIT seller_wallet (деньги становятся доступны)

    Вызывается когда заказ переходит в статус 'delivered'.
    """
    frozen = FrozenBalance.objects.select_for_update().filter(
        order=order,
        is_released=False,
    ).first()

    if not frozen:
        raise ValidationError(f'Замороженные средства для заказа #{order.id} не найдены.')

    seller_wallet = Wallet.objects.select_for_update().get(pk=frozen.wallet.pk)

    txn = Transaction.objects.create(
        transaction_type=TransactionType.DELIVERY_CONFIRM,
        order=order,
        initiated_by=confirmed_by,
        description=f'Подтверждение доставки заказа #{order.id}',
    )

    # Размораживаем — деньги возвращаются в активный баланс продавца
    _create_ledger_entry(txn, seller_wallet, EntryType.CREDIT, frozen.amount)

    # Помечаем frozen как освобождённый
    frozen.is_released = True
    frozen.released_at = timezone.now()
    frozen.save(update_fields=['is_released', 'released_at'])

    return txn


# ==============================================================================
# 3. ВОЗВРАТ СРЕДСТВ (REFUND)
# Заказ отменён → деньги возвращаются покупателю
# ==============================================================================

@transaction.atomic
def process_refund(order, buyer, refund_amount: Decimal, initiated_by=None) -> Transaction:
    """
    Логика возврата:
      Размораживаем у продавца → CREDIT buyer_wallet
    """
    frozen = FrozenBalance.objects.select_for_update().filter(
        order=order,
        is_released=False,
    ).first()

    if not frozen:
        raise ValidationError('Нет замороженных средств для возврата.')

    if refund_amount > frozen.amount:
        raise ValidationError(
            f'Сумма возврата {refund_amount} превышает замороженную {frozen.amount}.'
        )

    wallets = Wallet.objects.select_for_update().filter(
        user__in=[buyer, frozen.wallet.user],
        currency=Currency.KGS,
    ).order_by('id')

    wallet_map = {w.user_id: w for w in wallets}
    buyer_wallet = wallet_map.get(buyer.id)

    if not buyer_wallet:
        raise ValidationError('Кошелёк покупателя не найден.')

    txn = Transaction.objects.create(
        transaction_type=TransactionType.REFUND,
        order=order,
        initiated_by=initiated_by,
        description=f'Возврат по заказу #{order.id}',
    )

    # Возвращаем покупателю
    _create_ledger_entry(txn, buyer_wallet, EntryType.CREDIT, refund_amount)

    # Помечаем frozen как освобождённый
    frozen.is_released = True
    frozen.released_at = timezone.now()
    frozen.save(update_fields=['is_released', 'released_at'])

    return txn


# ==============================================================================
# 4. ЗАЯВКА НА ВЫВОД СРЕДСТВ
# Продавец запрашивает вывод → деньги блокируются
# ==============================================================================

@transaction.atomic
def create_payout_request(user, amount: Decimal, requisites) -> PayoutRequest:
    """
    Логика создания заявки на вывод:
      DEBIT seller_wallet  — списать из активного баланса
      Создать FrozenBalance с привязкой к PayoutRequest
      Создать PayoutRequest со статусом pending

    Администратор потом обработает вручную через approve_payout / reject_payout.
    """
    if amount <= 0:
        raise ValidationError('Сумма вывода должна быть больше нуля.')

    if not requisites.is_verified:
        raise ValidationError('Реквизиты не верифицированы администратором.')

    wallet = Wallet.objects.select_for_update().get(
        user=user,
        currency=Currency.KGS,
    )

    if wallet.balance < amount:
        raise ValidationError(
            f'Недостаточно средств. Доступно: {wallet.balance}, запрошено: {amount}'
        )

    # Сначала создаём PayoutRequest (без frozen_balance — добавим ниже)
    payout = PayoutRequest.objects.create(
        user=user,
        wallet=wallet,
        requisites=requisites,
        amount=amount,
        status=PayoutStatus.PENDING,
    )

    txn = Transaction.objects.create(
        transaction_type=TransactionType.PAYOUT,
        initiated_by=user,
        description=f'Заявка на вывод #{payout.id} | {amount} KGS',
    )

    # Списываем из активного баланса
    _create_ledger_entry(txn, wallet, EntryType.DEBIT, amount)

    # Замораживаем до обработки
    FrozenBalance.objects.create(
        wallet=wallet,
        amount=amount,
        payout_request=payout,
    )

    return payout


# ==============================================================================
# 5. ОДОБРЕНИЕ ЗАЯВКИ НА ВЫВОД (АДМИНИСТРАТОР)
# ==============================================================================

@transaction.atomic
def approve_payout(payout_id, admin_user, comment: str = '') -> PayoutRequest:
    """
    Администратор одобряет заявку:
      - Меняем статус → completed
      - Размораживаем FrozenBalance (деньги ушли — не возвращаем на баланс)
      - Фиксируем кто и когда обработал

    На данном этапе — ручная операция (без банковского API).
    В будущем здесь будет вызов banking API.
    """
    payout = PayoutRequest.objects.select_for_update().get(
        id=payout_id,
        status=PayoutStatus.PENDING,
    )

    frozen = FrozenBalance.objects.select_for_update().get(
        payout_request=payout,
        is_released=False,
    )

    # Деньги фактически выплачены — просто освобождаем заморозку
    # (они уже были списаны из wallet при создании заявки)
    frozen.is_released = True
    frozen.released_at = timezone.now()
    frozen.save(update_fields=['is_released', 'released_at'])

    payout.status = PayoutStatus.COMPLETED
    payout.processed_by = admin_user
    payout.admin_comment = comment
    payout.processed_at = timezone.now()
    payout.save(update_fields=['status', 'processed_by', 'admin_comment', 'processed_at'])

    return payout


# ==============================================================================
# 6. ОТКЛОНЕНИЕ ЗАЯВКИ НА ВЫВОД (АДМИНИСТРАТОР)
# ==============================================================================

@transaction.atomic
def reject_payout(payout_id, admin_user, comment: str = '') -> PayoutRequest:
    """
    Администратор отклоняет заявку:
      - Возвращаем деньги на баланс → CREDIT wallet
      - Размораживаем FrozenBalance
      - Меняем статус → rejected
    """
    payout = PayoutRequest.objects.select_for_update().get(
        id=payout_id,
        status=PayoutStatus.PENDING,
    )

    frozen = FrozenBalance.objects.select_for_update().get(
        payout_request=payout,
        is_released=False,
    )

    wallet = Wallet.objects.select_for_update().get(pk=payout.wallet.pk)

    txn = Transaction.objects.create(
        transaction_type=TransactionType.PAYOUT_CANCEL,
        initiated_by=admin_user,
        description=f'Отклонение заявки #{payout.id} — возврат {payout.amount} KGS',
    )

    # Возвращаем деньги на баланс
    _create_ledger_entry(txn, wallet, EntryType.CREDIT, payout.amount)

    # Размораживаем
    frozen.is_released = True
    frozen.released_at = timezone.now()
    frozen.save(update_fields=['is_released', 'released_at'])

    payout.status = PayoutStatus.REJECTED
    payout.processed_by = admin_user
    payout.admin_comment = comment
    payout.processed_at = timezone.now()
    payout.save(update_fields=['status', 'processed_by', 'admin_comment', 'processed_at'])

    return payout


# ==============================================================================
# 7. ПОПОЛНЕНИЕ БАЛАНСА (TOP UP)
# Используется для тестирования и ручного зачисления администратором
# ==============================================================================

@transaction.atomic
def top_up_wallet(user, amount: Decimal, initiated_by=None) -> Transaction:
    """
    Пополнение баланса пользователя.
    На продакшене здесь будет интеграция с платёжным шлюзом.
    """
    if amount <= 0:
        raise ValidationError('Сумма пополнения должна быть больше нуля.')

    wallet = Wallet.objects.select_for_update().get(
        user=user,
        currency=Currency.KGS,
    )

    txn = Transaction.objects.create(
        transaction_type=TransactionType.TOP_UP,
        initiated_by=initiated_by or user,
        description=f'Пополнение баланса на {amount} KGS',
    )

    _create_ledger_entry(txn, wallet, EntryType.CREDIT, amount)

    return txn



"""
bank/services.py — добавлены функции для клиента:
  - apply_cashback()       — начислить кэшбэк (заглушка, не начисляет пока config.is_active=False)
  - client_payout_request() — клиент выводит деньги (возврат/кэшбэк)

Добавь эти функции в конец своего существующего bank/services.py
"""




# ==============================================================================
# КЭШБЭК — ЗАГЛУШКА
# Пока CashbackConfig.is_active = False — ничего не начисляется.
# Когда включишь в Admin — автоматически заработает.
# ==============================================================================

@transaction.atomic
def apply_cashback(order, buyer) -> Transaction | None:
    """
    Начислить кэшбэк клиенту после доставки заказа.

    Вызывается из signals.py вместе с confirm_delivery.
    Если кэшбэк отключён (is_active=False) — просто возвращает None.

    Сумма кэшбэка = сумма заказа * процент / 100
    """
    config = CashbackConfig.get()

    # ЗАГЛУШКА — кэшбэк отключён
    if not config.is_active or config.percent <= 0:
        return None

    # Считаем сумму заказа
    order_total = sum(
        item.sale_price * item.quantity
        for item in order.items.all()
    )

    if order_total <= 0:
        return None

    cashback_amount = (order_total * config.percent / 100).quantize(Decimal('0.01'))

    if cashback_amount <= 0:
        return None

    wallet = Wallet.objects.select_for_update().get(
        user=buyer,
        currency=Currency.KGS,
    )

    txn = Transaction.objects.create(
        transaction_type=TransactionType.CASHBACK,
        order=order,
        initiated_by=buyer,
        description=f'Кэшбэк {config.percent}% за заказ #{order.id} — {cashback_amount} KGS',
    )

    balance_before = wallet.balance
    wallet.balance += cashback_amount
    wallet.save(update_fields=['balance', 'updated_at'])

    LedgerEntry.objects.create(
        transaction=txn,
        wallet=wallet,
        entry_type=EntryType.CREDIT,
        amount=cashback_amount,
        balance_before=balance_before,
        balance_after=wallet.balance,
    )

    return txn


# ==============================================================================
# КЛИЕНТСКИЙ ВЫВОД СРЕДСТВ
# Клиент выводит кэшбэк/возвраты на карту
# ==============================================================================

@transaction.atomic
def client_payout_request(user, amount: Decimal, requisites) -> PayoutRequest:
    """
    Клиент создаёт заявку на вывод своего кэшбэка или возвратов.
    Логика идентична продавцу — тот же PayoutRequest.
    """
    if amount <= 0:
        raise ValidationError('Сумма вывода должна быть больше нуля.')

    if not requisites.is_verified:
        raise ValidationError('Реквизиты не верифицированы администратором.')

    wallet = Wallet.objects.select_for_update().get(
        user=user,
        currency=Currency.KGS,
    )

    if wallet.balance < amount:
        raise ValidationError(
            f'Недостаточно средств. Доступно: {wallet.balance}, запрошено: {amount}'
        )

    payout = PayoutRequest.objects.create(
        user=user,
        wallet=wallet,
        requisites=requisites,
        amount=amount,
        status=PayoutStatus.PENDING,
    )

    txn = Transaction.objects.create(
        transaction_type=TransactionType.PAYOUT,
        initiated_by=user,
        description=f'Вывод клиента #{payout.id} | {amount} KGS',
    )

    # Списываем из активного баланса
    balance_before = wallet.balance
    wallet.balance -= amount
    wallet.save(update_fields=['balance', 'updated_at'])

    LedgerEntry.objects.create(
        transaction=txn,
        wallet=wallet,
        entry_type=EntryType.DEBIT,
        amount=amount,
        balance_before=balance_before,
        balance_after=wallet.balance,
    )

    # Замораживаем до обработки
    FrozenBalance.objects.create(
        wallet=wallet,
        amount=amount,
        payout_request=payout,
    )

    return payout




# В будущем сюда же добавятся функции для интеграции с платёжными шлюзами, 
# автоматической обработки выплат и т.д.
@transaction.atomic
def create_topup_request(user, amount: Decimal, comment: str = '') -> TopUpRequest:
    """
    Клиент создаёт заявку на пополнение.
    Деньги НЕ зачисляются сразу — только после одобрения админом.
    """
    if amount <= 0:
        raise ValidationError('Сумма пополнения должна быть больше нуля.')

    wallet = get_or_create_wallet(user)

    topup = TopUpRequest.objects.create(
        user=user,
        wallet=wallet,
        amount=amount,
        comment=comment,
        status=TopUpStatus.PENDING,
    )
    return topup


@transaction.atomic
def approve_topup(topup_id, admin_user, comment: str = '') -> TopUpRequest:
    """
    Админ одобряет заявку → деньги зачисляются на кошелёк.
    """
    from django.utils import timezone

    topup = TopUpRequest.objects.select_for_update().get(
        id=topup_id,
        status=TopUpStatus.PENDING,
    )

    wallet = Wallet.objects.select_for_update().get(pk=topup.wallet.pk)

    # Зачисляем через top_up_wallet (создаёт Transaction + LedgerEntry)
    top_up_wallet(
        user=topup.user,
        amount=topup.amount,
        initiated_by=admin_user,
    )

    topup.status       = TopUpStatus.APPROVED
    topup.processed_by = admin_user
    topup.admin_comment = comment
    topup.processed_at = timezone.now()
    topup.save(update_fields=['status', 'processed_by', 'admin_comment', 'processed_at'])

    return topup


@transaction.atomic
def reject_topup(topup_id, admin_user, comment: str = '') -> TopUpRequest:
    """
    Админ отклоняет заявку → ничего не происходит с балансом.
    """
    from django.utils import timezone

    topup = TopUpRequest.objects.select_for_update().get(
        id=topup_id,
        status=TopUpStatus.PENDING,
    )

    topup.status        = TopUpStatus.REJECTED
    topup.processed_by  = admin_user
    topup.admin_comment = comment
    topup.processed_at  = timezone.now()
    topup.save(update_fields=['status', 'processed_by', 'admin_comment', 'processed_at'])

    return topup