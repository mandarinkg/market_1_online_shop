"""
bank/models.py — добавлен тип CASHBACK в TransactionType.
Остальное без изменений.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


import re
from django.core.validators import RegexValidator



class Currency(models.TextChoices):
    KGS = 'KGS', 'Кыргызский сом'
    USD = 'USD', 'Доллар США'


class TransactionType(models.TextChoices):
    PURCHASE         = 'purchase',         'Покупка товара'
    DELIVERY_CONFIRM = 'delivery_confirm',  'Подтверждение доставки'
    REFUND           = 'refund',           'Возврат средств'
    PAYOUT           = 'payout',           'Вывод средств'
    PAYOUT_CANCEL    = 'payout_cancel',    'Отмена вывода'
    TOP_UP           = 'top_up',           'Пополнение баланса'
    CASHBACK         = 'cashback',         'Кэшбэк'         # ← новый


class EntryType(models.TextChoices):
    DEBIT  = 'debit',  'Дебет (убыло)'
    CREDIT = 'credit', 'Кредит (прибыло)'


class PayoutStatus(models.TextChoices):
    PENDING   = 'pending',   'Ожидает обработки'
    APPROVED  = 'approved',  'Одобрено'
    REJECTED  = 'rejected',  'Отклонено'
    COMPLETED = 'completed', 'Выплачено'


# ==============================================================================
# WALLET
# ==============================================================================

class Wallet(models.Model):
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='wallets')
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.KGS)
    balance  = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'currency')
        verbose_name = 'Кошелёк'
        verbose_name_plural = 'Кошельки'
        indexes = [models.Index(fields=['user', 'currency'])]

    def __str__(self):
        return f'{self.user.username} | {self.currency} | {self.balance}'

    def clean(self):
        if self.balance < 0:
            raise ValidationError('Баланс не может быть отрицательным.')


# ==============================================================================
# FROZEN BALANCE
# ==============================================================================

class FrozenBalance(models.Model):
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet  = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='frozen_entries')
    amount  = models.DecimalField(max_digits=14, decimal_places=2)
    order   = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='frozen_balances')
    payout_request = models.OneToOneField('PayoutRequest', on_delete=models.SET_NULL, null=True, blank=True, related_name='frozen_balance')
    is_released = models.BooleanField(default=False, db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Замороженный баланс'
        verbose_name_plural = 'Замороженные балансы'
        indexes = [models.Index(fields=['wallet', 'is_released'])]

    def __str__(self):
        return f'{self.wallet.user.username} | {self.amount} | {"разморожено" if self.is_released else "заморожено"}'


# ==============================================================================
# TRANSACTION
# ==============================================================================

class Transaction(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction_type = models.CharField(max_length=30, choices=TransactionType.choices, db_index=True)
    order            = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    initiated_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='initiated_transactions')
    description      = models.TextField(blank=True)
    created_at       = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Транзакция'
        verbose_name_plural = 'Транзакции'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_transaction_type_display()} | {self.id}'


# ==============================================================================
# LEDGER ENTRY — неизменяемый лог
# ==============================================================================

class LedgerEntry(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction    = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name='entries')
    wallet         = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='ledger_entries')
    entry_type     = models.CharField(max_length=6, choices=EntryType.choices)
    amount         = models.DecimalField(max_digits=14, decimal_places=2)
    balance_before = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after  = models.DecimalField(max_digits=14, decimal_places=2)
    created_at     = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Запись леджера'
        verbose_name_plural = 'Записи леджера'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', 'created_at']),
            models.Index(fields=['transaction']),
        ]

    def __str__(self):
        return f'{self.entry_type} | {self.amount} | {self.wallet.user.username}'

    def save(self, *args, **kwargs):
    # Проверяем есть ли запись УЖЕ в БД, а не просто наличие pk
        if self.pk and LedgerEntry.objects.filter(pk=self.pk).exists():
            raise ValidationError('Запись леджера нельзя редактировать.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Запись леджера нельзя удалять.')


# ==============================================================================
# BANK REQUISITES
# ==============================================================================

class BankRequisites(models.Model):

    class RequisiteType(models.TextChoices):
        INDIVIDUAL = 'individual', 'Физическое лицо'
        LEGAL      = 'legal',      'Юридическое лицо / ИП'

    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bank_requisites')
    requisite_type = models.CharField(max_length=10, choices=RequisiteType.choices, default=RequisiteType.INDIVIDUAL)
    bank_name      = models.CharField(max_length=255)
    bik            = models.CharField(max_length=6, db_index=True)
    account_number = models.CharField(max_length=16)
    inn            = models.CharField(max_length=14, blank=True)
    company_name   = models.CharField(max_length=255, blank=True)
    full_name      = models.CharField(max_length=255)
    is_default     = models.BooleanField(default=False, db_index=True)
    is_verified    = models.BooleanField(default=False)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Банковские реквизиты'
        verbose_name_plural = 'Банковские реквизиты'
        indexes = [models.Index(fields=['user', 'is_default'])]

    def __str__(self):
        return f'{self.user.username} | {self.bank_name} | {self.account_number}'

    def clean(self):
        if not self.bik.isdigit() or len(self.bik) != 6:
            raise ValidationError({'bik': 'БИК должен содержать ровно 6 цифр.'})
        if not self.account_number.isdigit() or len(self.account_number) != 16:
            raise ValidationError({'account_number': 'Расчётный счёт должен содержать ровно 16 цифр.'})
        if self.inn:
            if not self.inn.isdigit() or len(self.inn) != 14:
                raise ValidationError({'inn': 'ИНН должен содержать ровно 14 цифр.'})
        if self.requisite_type == self.RequisiteType.LEGAL and not self.inn:
            raise ValidationError({'inn': 'ИНН обязателен для юридического лица.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.is_default:
            BankRequisites.objects.filter(user=self.user, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


# ==============================================================================
# PAYOUT REQUEST
# ==============================================================================
"""
Замени существующий класс PayoutRequest в bank/models.py на этот.
Добавлены: destination_type, seller_card (необязательный requisites).
"""

class PayoutRequest(models.Model):

    class DestinationType(models.TextChoices):
        REQUISITES = 'requisites', 'На расчётный счёт'
        CARD       = 'card',       'На карту'

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user         = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='payout_requests'
    )
    wallet       = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name='payout_requests'
    )

    # Способ вывода — на счёт или на карту
    destination_type = models.CharField(
        max_length=15,
        choices=DestinationType.choices,
        default=DestinationType.REQUISITES,
        verbose_name='Способ вывода',
        db_index=True,
    )

    # На расчётный счёт (необязательно если вывод на карту)
    requisites   = models.ForeignKey(
        BankRequisites,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='payout_requests',
        verbose_name='Реквизиты'
    )

    # На карту (необязательно если вывод на счёт)
    seller_card  = models.ForeignKey(
        'SellerCard',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='payout_requests',
        verbose_name='Карта для вывода'
    )

    amount       = models.DecimalField(max_digits=14, decimal_places=2, verbose_name='Сумма')
    status       = models.CharField(
        max_length=10,
        choices=PayoutStatus.choices,
        default=PayoutStatus.PENDING,
        db_index=True
    )
    processed_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='processed_payouts'
    )
    admin_comment = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Заявка на вывод'
        verbose_name_plural = 'Заявки на вывод'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        dest = self.get_destination_type_display()
        return f'{self.user.username} | {self.amount} KGS | {dest} | {self.get_status_display()}'

    def clean(self):
        if self.amount <= 0:
            raise ValidationError({'amount': 'Сумма вывода должна быть больше нуля.'})
        if self.destination_type == self.DestinationType.CARD and not self.seller_card:
            raise ValidationError({'seller_card': 'Укажите карту для вывода.'})
        if self.destination_type == self.DestinationType.REQUISITES and not self.requisites:
            raise ValidationError({'requisites': 'Укажите реквизиты для вывода на счёт.'})

    @property
    def destination_display(self):
        """Красивое отображение куда идут деньги"""
        if self.destination_type == self.DestinationType.CARD and self.seller_card:
            return f'Карта {self.seller_card.masked_number}'
        elif self.destination_type == self.DestinationType.REQUISITES and self.requisites:
            return f'Счёт {self.requisites.bank_name}'
        return '—'
# ==============================================================================
# CASHBACK CONFIG — заглушка, потом настроишь процент
# ==============================================================================

class CashbackConfig(models.Model):
    """
    Настройки кэшбэка. Одна запись на всю систему.
    Пока заглушка — процент 0, кэшбэк не начисляется.
    Когда будешь готов — просто поменяй percent в Admin.
    """
    percent     = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        verbose_name='Процент кэшбэка (%)',
        help_text='0.00 = кэшбэк отключён. Например 2.00 = 2%'
    )
    is_active   = models.BooleanField(default=False, verbose_name='Кэшбэк включён')
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Настройка кэшбэка'
        verbose_name_plural = 'Настройки кэшбэка'

    def __str__(self):
        return f'Кэшбэк: {self.percent}% | {"Включён" if self.is_active else "Отключён"}'

    @classmethod
    def get(cls):
        """Получить текущие настройки (или создать с дефолтами)."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


"""
Добавь этот код в КОНЕЦ своего bank/models.py
(после класса CashbackConfig)
"""

# ==============================================================================
# 1. СПРАВОЧНИК БАНКОВ (BankBrand)
# ==============================================================================

class BankBrand(models.Model):
    """
    Справочник банков Кыргызстана.
    Хранит визуальные данные для красивого UI карточек.

    Заполняется вручную через Django Admin.
    Примеры: МБанк (#00B140), Оптима (#003DA5), Бакай (#E31E24), Элкарт (#005BAA)
    """
    name     = models.CharField(max_length=100, unique=True, verbose_name='Название банка')
    slug     = models.SlugField(max_length=100, unique=True, verbose_name='Slug')
    logo     = models.ImageField(
        upload_to='bank_brands/',
        null=True, blank=True,
        verbose_name='Логотип банка'
    )
    bg_color = models.CharField(
        max_length=7,
        default='#1a1a2e',
        verbose_name='HEX цвет фона карточки',
        help_text='Например: #00B140 для МБанка',
        validators=[
            RegexValidator(
                regex=r'^#[0-9A-Fa-f]{6}$',
                message='Введите корректный HEX цвет, например #00B140'
            )
        ]
    )
    # Цвет текста — автоматически белый или тёмный в зависимости от фона
    text_color = models.CharField(
        max_length=7,
        default='#FFFFFF',
        verbose_name='HEX цвет текста',
    )

    class Meta:
        verbose_name = 'Банк'
        verbose_name_plural = 'Банки'
        ordering = ['name']

    def __str__(self):
        return self.name


# ==============================================================================
# 2. КАРТЫ КЛИЕНТОВ (CustomerCard)
# Для оплаты на чекауте. Полный номер и CVV НЕ ХРАНЯТСЯ (PCI DSS).
# Храним только токен и маскированный номер.
# ==============================================================================

class CustomerCard(models.Model):
    """
    Привязанная карта клиента для оплаты заказов.

    Безопасность:
    - payment_token — токен от платёжного шлюза (Stripe/CloudPayments/etc)
    - masked_number — только для отображения, например "4111 **** **** 1111"
    - Полный номер и CVV НИКОГДА не хранятся в БД
    """
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user          = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='customer_cards',
        verbose_name='Клиент'
    )
    bank          = models.ForeignKey(
        BankBrand,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='customer_cards',
        verbose_name='Банк'
    )

    # Токен от платёжного шлюза — используется для списания
    payment_token = models.CharField(
        max_length=255,
        verbose_name='Платёжный токен',
        help_text='Токен от платёжного шлюза. Никогда не показывать пользователю.'
    )

    # Только для UI — показываем клиенту
    masked_number = models.CharField(
        max_length=19,
        verbose_name='Маскированный номер',
        help_text='Например: 4111 **** **** 1111'
    )

    # Срок действия — только месяц/год
    expiry_month  = models.PositiveSmallIntegerField(verbose_name='Месяц окончания')
    expiry_year   = models.PositiveSmallIntegerField(verbose_name='Год окончания')

    # Тип карты для иконки
    CARD_TYPE_CHOICES = [
        ('visa',       'Visa'),
        ('mastercard', 'Mastercard'),
        ('elcard',     'Элкарт'),
        ('mir',        'Мир'),
        ('other',      'Другая'),
    ]
    card_type = models.CharField(
        max_length=20,
        choices=CARD_TYPE_CHOICES,
        default='other',
        verbose_name='Тип карты'
    )

    is_default  = models.BooleanField(default=False, verbose_name='Основная карта', db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Карта клиента'
        verbose_name_plural = 'Карты клиентов'
        indexes = [models.Index(fields=['user', 'is_default'])]

    def __str__(self):
        return f'{self.user.username} | {self.masked_number}'

    @property
    def expiry_display(self):
        """Возвращает срок действия в формате MM/YY"""
        return f'{self.expiry_month:02d}/{str(self.expiry_year)[-2:]}'

    def save(self, *args, **kwargs):
        # Если помечаем как основную — снимаем флаг с остальных
        if self.is_default:
            CustomerCard.objects.filter(
                user=self.user,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


# ==============================================================================
# 3. КАРТЫ ПРОДАВЦОВ (SellerCard)
# Для вывода средств. Храним полный номер (не токен —
# выплаты инициирует сам маркетплейс через банковский API).
# ==============================================================================

class SellerCard(models.Model):
    """
    Карта продавца для получения выплат.

    Отличие от CustomerCard:
    - Храним полный номер карты (продавец сам вводит для получения выплат)
    - Нет payment_token (выплату инициирует администратор/система)
    - Верификация администратором обязательна
    """
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='seller_cards',
        verbose_name='Продавец'
    )
    bank        = models.ForeignKey(
        BankBrand,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='seller_cards',
        verbose_name='Банк'
    )

    # Полный 16-значный номер карты
    card_number = models.CharField(
        max_length=16,
        verbose_name='Номер карты (16 цифр)',
    )

    cardholder_name = models.CharField(
        max_length=255,
        verbose_name='Имя держателя карты',
        help_text='Как написано на карте, заглавными буквами'
    )

    expiry_month = models.PositiveSmallIntegerField(verbose_name='Месяц окончания')
    expiry_year  = models.PositiveSmallIntegerField(verbose_name='Год окончания')

    is_default   = models.BooleanField(default=False, db_index=True, verbose_name='Основная карта')
    is_verified  = models.BooleanField(default=False, verbose_name='Верифицирована администратором')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Карта продавца'
        verbose_name_plural = 'Карты продавцов'
        indexes = [models.Index(fields=['user', 'is_default'])]

    def __str__(self):
        masked = f'{self.card_number[:4]} **** **** {self.card_number[-4:]}'
        return f'{self.user.username} | {masked}'

    @property
    def masked_number(self):
        """Маскированный номер для отображения в UI"""
        return f'{self.card_number[:4]} **** **** {self.card_number[-4:]}'

    @property
    def expiry_display(self):
        return f'{self.expiry_month:02d}/{str(self.expiry_year)[-2:]}'

    def clean(self):
        # Ровно 16 цифр
        if not self.card_number.isdigit() or len(self.card_number) != 16:
            raise ValidationError({'card_number': 'Номер карты должен содержать ровно 16 цифр.'})

        # Алгоритм Луна — проверка валидности номера карты
        digits = [int(d) for d in self.card_number]
        for i in range(len(digits) - 2, -1, -2):
            digits[i] *= 2
            if digits[i] > 9:
                digits[i] -= 9
        if sum(digits) % 10 != 0:
            raise ValidationError({'card_number': 'Номер карты не прошёл проверку (алгоритм Луна).'})

        # Срок действия
        if not (1 <= self.expiry_month <= 12):
            raise ValidationError({'expiry_month': 'Месяц должен быть от 1 до 12.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.is_default:
            SellerCard.objects.filter(
                user=self.user,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)



# ==============================================================================
# 4. ЗАЯВКИ НА ПОПОЛНЕНИЕ (TopUpRequest)
# Жизненный цикл: pending → approved/rejected
# ==============================================================================
class TopUpStatus(models.TextChoices):
    PENDING   = 'pending',   'Ожидает подтверждения'
    APPROVED  = 'approved',  'Одобрено'
    REJECTED  = 'rejected',  'Отклонено'


class TopUpRequest(models.Model):
    """
    Заявка клиента на пополнение кошелька.

    Жизненный цикл:
      pending → approved  (админ одобрил → деньги зачислены)
              ↘ rejected  (админ отклонил → ничего не происходит)

    В будущем: вместо ручного одобрения будет автоматический
    вызов банковского API который проверит списание с карты клиента.
    """
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user        = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='topup_requests',
        verbose_name='Клиент',
    )
    wallet      = models.ForeignKey(
        'Wallet',
        on_delete=models.PROTECT,
        related_name='topup_requests',
        verbose_name='Кошелёк',
    )
    amount      = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name='Сумма пополнения',
    )
    status      = models.CharField(
        max_length=10,
        choices=TopUpStatus.choices,
        default=TopUpStatus.PENDING,
        db_index=True,
        verbose_name='Статус',
    )

    # Комментарий от клиента (необязательно)
    comment     = models.TextField(
        blank=True,
        verbose_name='Комментарий клиента',
    )

    # Кто обработал
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='processed_topups',
        verbose_name='Обработал',
    )
    admin_comment = models.TextField(blank=True, verbose_name='Комментарий администратора')
    created_at    = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Заявка на пополнение'
        verbose_name_plural = 'Заявки на пополнение'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f'{self.user.username} | +{self.amount} KGS | {self.get_status_display()}'

    def clean(self):
        if self.amount <= 0:
            raise ValidationError({'amount': 'Сумма пополнения должна быть больше нуля.'})