"""
bank/views.py

Эндпоинты для продавца:
  - Просмотр баланса и истории транзакций
  - Добавление банковских реквизитов
  - Создание заявки на вывод средств
  - Просмотр статуса заявок

Эндпоинты для администратора:
  - Список заявок на вывод
  - Одобрить / Отклонить заявку
"""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from .models import (
    BankRequisites,
    FrozenBalance,
    LedgerEntry,
    PayoutRequest,
    PayoutStatus,
    Wallet,
    Currency,
    CashbackConfig,  # ← добавь
)
from .services import (
    approve_payout,
    create_payout_request,
    get_or_create_wallet,
    reject_payout,
    client_payout_request,
)

from .models import CustomerCard, SellerCard, BankBrand

from .models import TopUpRequest, TopUpStatus
from .services import create_topup_request, approve_topup, reject_topup


# ==============================================================================
# ПРОДАВЕЦ — БАЛАНС
# ==============================================================================

@login_required
def seller_balance(request):
    """Главная страница кошелька продавца."""
    if request.user.role not in ('seller', ) and not request.user.is_staff:
        return redirect('dashboard:home')

    wallet = get_or_create_wallet(request.user)

    # Замороженные средства
    frozen_total = FrozenBalance.objects.filter(
        wallet=wallet,
        is_released=False,
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

    # Последние 20 записей леджера
    ledger = LedgerEntry.objects.filter(
        wallet=wallet
    ).select_related('transaction').order_by('-created_at')[:20]

    # Активные заявки на вывод
    pending_payouts = PayoutRequest.objects.filter(
        user=request.user,
        status=PayoutStatus.PENDING,
    )

    # История выплат
    payout_history = PayoutRequest.objects.filter(
        user=request.user,
    ).exclude(status=PayoutStatus.PENDING).order_by('-created_at')[:10]

    return render(request, 'bank/seller_balance.html', {
        'wallet': wallet,
        'frozen_total': frozen_total,
        'ledger': ledger,
        'pending_payouts': pending_payouts,
        'payout_history': payout_history,
    })


# ==============================================================================
# ПРОДАВЕЦ — РЕКВИЗИТЫ
# ==============================================================================

@login_required
def requisites_list(request):
    """Список банковских реквизитов продавца."""
    requisites = BankRequisites.objects.filter(user=request.user).order_by('-is_default', '-created_at')
    return render(request, 'bank/requisites_list.html', {'requisites': requisites})


@login_required
def requisites_add(request):
    """Добавить банковские реквизиты."""
    if request.method == 'POST':
        try:
            req = BankRequisites(
                user=request.user,
                requisite_type=request.POST.get('requisite_type', 'individual'),
                bank_name=request.POST.get('bank_name', '').strip(),
                bik=request.POST.get('bik', '').strip(),
                account_number=request.POST.get('account_number', '').strip(),
                inn=request.POST.get('inn', '').strip(),
                company_name=request.POST.get('company_name', '').strip(),
                full_name=request.POST.get('full_name', '').strip(),
                is_default=request.POST.get('is_default') == 'on',
            )
            req.full_clean()
            req.save()
            messages.success(request, 'Реквизиты добавлены. Ожидайте верификации администратором.')
            return redirect('bank:requisites_list')
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'bank/requisites_add.html')


@login_required
def requisites_delete(request, pk):
    """Удалить реквизиты (только если нет активных заявок)."""
    req = get_object_or_404(BankRequisites, pk=pk, user=request.user)

    has_active = PayoutRequest.objects.filter(
        requisites=req,
        status=PayoutStatus.PENDING,
    ).exists()

    if has_active:
        messages.error(request, 'Нельзя удалить реквизиты с активной заявкой на вывод.')
        return redirect('bank:requisites_list')

    req.delete()
    messages.success(request, 'Реквизиты удалены.')
    return redirect('bank:requisites_list')


# ==============================================================================
# ПРОДАВЕЦ — ВЫВОД СРЕДСТВ
# ==============================================================================

@login_required
def payout_create(request):
    """Создать заявку на вывод средств."""
    if request.method != 'POST':
        return redirect('bank:seller_balance')

    amount_str = request.POST.get('amount', '').strip()
    requisites_id = request.POST.get('requisites_id', '').strip()

    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        messages.error(request, 'Неверная сумма.')
        return redirect('bank:seller_balance')

    requisites = get_object_or_404(BankRequisites, id=requisites_id, user=request.user)

    try:
        payout = create_payout_request(
            user=request.user,
            amount=amount,
            requisites=requisites,
        )
        messages.success(
            request,
            f'Заявка на вывод {amount} KGS создана. Ожидайте обработки администратором.'
        )
    except Exception as e:
        messages.error(request, str(e))

    return redirect('bank:seller_balance')


# ==============================================================================
# АДМИНИСТРАТОР — СПИСОК ЗАЯВОК НА ВЫВОД
# ==============================================================================

@login_required
def admin_payout_list(request):
    """Список всех заявок на вывод для администратора."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('dashboard:home')

    status_filter = request.GET.get('status', 'pending')

    payouts = PayoutRequest.objects.select_related(
        'user', 'wallet', 'requisites', 'processed_by'
    ).order_by('-created_at')

    if status_filter != 'all':
        payouts = payouts.filter(status=status_filter)

    return render(request, 'bank/admin_payout_list.html', {
        'payouts': payouts,
        'status_filter': status_filter,
        'pending_count': PayoutRequest.objects.filter(status='pending').count(),
    })


@login_required
def admin_payout_approve(request, payout_id):
    """Одобрить заявку на вывод."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('dashboard:home')

    if request.method != 'POST':
        return redirect('bank:admin_payout_list')

    comment = request.POST.get('comment', '').strip()

    try:
        approve_payout(payout_id=payout_id, admin_user=request.user, comment=comment)
        messages.success(request, 'Заявка одобрена. Средства выплачены.')
    except Exception as e:
        messages.error(request, str(e))

    return redirect('bank:admin_payout_list')


@login_required
def admin_payout_reject(request, payout_id):
    """Отклонить заявку на вывод — деньги вернутся на баланс продавца."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('dashboard:home')

    if request.method != 'POST':
        return redirect('bank:admin_payout_list')

    comment = request.POST.get('comment', '').strip()

    try:
        reject_payout(payout_id=payout_id, admin_user=request.user, comment=comment)
        messages.success(request, 'Заявка отклонена. Средства возвращены на баланс.')
    except Exception as e:
        messages.error(request, str(e))

    return redirect('bank:admin_payout_list')





"""
bank/views.py — добавь эти view-функции в конец своего bank/views.py
"""


# ==============================================================================
# КЛИЕНТ — КОШЕЛЁК
# ==============================================================================

@login_required
def client_wallet(request):
    """Кошелёк клиента — баланс, история, кэшбэк, вывод."""

    wallet = get_or_create_wallet(request.user)

    # Замороженные (деньги на выводе в ожидании)
    frozen_total = FrozenBalance.objects.filter(
        wallet=wallet,
        is_released=False,
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

    # История последних 20 операций
    ledger = LedgerEntry.objects.filter(
        wallet=wallet
    ).select_related('transaction').order_by('-created_at')[:20]

    # Активные заявки на вывод
    pending_payouts = PayoutRequest.objects.filter(
        user=request.user,
        status=PayoutStatus.PENDING,
    )

    # История выплат
    payout_history = PayoutRequest.objects.filter(
        user=request.user,
    ).exclude(status=PayoutStatus.PENDING).order_by('-created_at')[:10]

    pending_topups = TopUpRequest.objects.filter(
        user=request.user,
        status=TopUpStatus.PENDING,
    )
    # Реквизиты клиента
    requisites = BankRequisites.objects.filter(user=request.user).order_by('-is_default')

    # Настройки кэшбэка (для отображения процента)
    cashback_config = CashbackConfig.get()

    return render(request, 'bank/client_wallet.html', {
        'wallet': wallet,
        'frozen_total': frozen_total,
        'ledger': ledger,
        'pending_payouts': pending_payouts,
        'payout_history': payout_history,
        'requisites': requisites,
        'cashback_config': cashback_config,
        'pending_topups': pending_topups,
    })


@login_required
def client_payout_create(request):
    """Клиент создаёт заявку на вывод кэшбэка/возвратов."""
    if request.method != 'POST':
        return redirect('bank:client_wallet')

    amount_str    = request.POST.get('amount', '').strip()
    requisites_id = request.POST.get('requisites_id', '').strip()

    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        messages.error(request, 'Неверная сумма.')
        return redirect('bank:client_wallet')

    requisites = get_object_or_404(BankRequisites, id=requisites_id, user=request.user)

    try:
        client_payout_request(
            user=request.user,
            amount=amount,
            requisites=requisites,
        )
        messages.success(request, f'Заявка на вывод {amount} KGS создана.')
    except Exception as e:
        messages.error(request, str(e))

    return redirect('bank:client_wallet')




"""
Добавь эти view-функции в bank/views.py
и эти url-пути в bank/urls.py
"""

# ══════════════════════════════════════════
# bank/views.py — добавь в конец файла
# ══════════════════════════════════════════



@login_required
def cards_list(request):
    """Список привязанных карт клиента."""
    cards = CustomerCard.objects.filter(
        user=request.user
    ).select_related('bank').order_by('-is_default', '-created_at')

    banks = BankBrand.objects.all()

    return render(request, 'bank/cards_page.html', {
        'cards': cards,
        'banks': banks,
    })


@login_required
def card_add(request):
    """Привязать новую карту."""
    if request.method != 'POST':
        return redirect('bank:cards_list')

    card_number_raw = request.POST.get('card_number', '').replace(' ', '').strip()
    expiry          = request.POST.get('expiry', '').strip()       # MM/YY
    cardholder_name = request.POST.get('cardholder_name', '').strip()
    bank_id         = request.POST.get('bank_id', '').strip()

    # Базовая валидация
    if not card_number_raw.isdigit() or len(card_number_raw) != 16:
        messages.error(request, 'Номер карты должен содержать 16 цифр.')
        return redirect('bank:cards_list')

    try:
        month, year = expiry.split('/')
        expiry_month = int(month)
        expiry_year  = int('20' + year)
    except (ValueError, IndexError):
        messages.error(request, 'Неверный формат срока действия. Используйте MM/YY.')
        return redirect('bank:cards_list')

    # Маскируем номер для отображения
    masked = f'{card_number_raw[:4]} **** **** {card_number_raw[-4:]}'

    # Определяем тип карты по первой цифре
    first_digit = card_number_raw[0]
    if first_digit == '4':
        card_type = 'visa'
    elif first_digit == '5':
        card_type = 'mastercard'
    else:
        card_type = 'other'

    bank = None
    if bank_id:
        try:
            bank = BankBrand.objects.get(id=bank_id)
        except BankBrand.DoesNotExist:
            pass

    # На продакшене здесь будет вызов платёжного шлюза для получения токена.
    # Пока генерируем заглушку-токен.
    import uuid as _uuid
    payment_token = f'tok_{_uuid.uuid4().hex}'

    CustomerCard.objects.create(
        user=request.user,
        bank=bank,
        payment_token=payment_token,
        masked_number=masked,
        expiry_month=expiry_month,
        expiry_year=expiry_year,
        card_type=card_type,
        is_default=not CustomerCard.objects.filter(user=request.user).exists(),
    )

    messages.success(request, f'Карта {masked} успешно добавлена.')
    return redirect('bank:cards_list')


@login_required
def card_set_default(request):
    """Сделать карту основной."""
    if request.method != 'POST':
        return redirect('bank:cards_list')

    card_id = request.POST.get('card_id')
    try:
        card = CustomerCard.objects.get(id=card_id, user=request.user)
        card.is_default = True
        card.save()
        messages.success(request, f'Карта {card.masked_number} теперь основная.')
    except CustomerCard.DoesNotExist:
        messages.error(request, 'Карта не найдена.')

    return redirect('bank:cards_list')


@login_required
def card_delete(request):
    """Удалить карту."""
    if request.method != 'POST':
        return redirect('bank:cards_list')

    card_id = request.POST.get('card_id')
    try:
        card = CustomerCard.objects.get(id=card_id, user=request.user)
        masked = card.masked_number
        card.delete()
        messages.success(request, f'Карта {masked} удалена.')
    except CustomerCard.DoesNotExist:
        messages.error(request, 'Карта не найдена.')

    return redirect('bank:cards_list')



# Добавь эти функции в КОНЕЦ bank/views.py


# ==============================================================================
# КЛИЕНТ — ЗАЯВКА НА ПОПОЛНЕНИЕ
# ==============================================================================

@login_required
def topup_create(request):
    """Клиент создаёт заявку на пополнение кошелька."""
    if request.method != 'POST':
        return redirect('bank:client_wallet')

    amount_str = request.POST.get('amount', '').strip()
    comment    = request.POST.get('comment', '').strip()

    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        messages.error(request, 'Введите корректную сумму.')
        return redirect('bank:client_wallet')

    try:
        create_topup_request(
            user=request.user,
            amount=amount,
            comment=comment,
        )
        messages.success(
            request,
            f'Заявка на пополнение {amount} KGS отправлена. '
            f'Ожидайте подтверждения администратора.'
        )
    except Exception as e:
        messages.error(request, str(e))

    return redirect('bank:client_wallet')


# ==============================================================================
# АДМИНИСТРАТОР — СПИСОК ЗАЯВОК НА ПОПОЛНЕНИЕ
# ==============================================================================

@login_required
def admin_topup_list(request):
    """Список заявок на пополнение для администратора."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('dashboard:home')

    status_filter = request.GET.get('status', 'pending')

    topups = TopUpRequest.objects.select_related(
        'user', 'wallet', 'processed_by'
    ).order_by('-created_at')

    if status_filter != 'all':
        topups = topups.filter(status=status_filter)

    return render(request, 'bank/admin_topup_list.html', {
        'topups':        topups,
        'status_filter': status_filter,
        'pending_count': TopUpRequest.objects.filter(status='pending').count(),
    })


@login_required
def admin_topup_approve(request, topup_id):
    """Одобрить заявку на пополнение."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('dashboard:home')

    if request.method != 'POST':
        return redirect('bank:admin_topup_list')

    comment = request.POST.get('comment', '').strip()

    try:
        approve_topup(topup_id=topup_id, admin_user=request.user, comment=comment)
        messages.success(request, 'Заявка одобрена. Баланс клиента пополнен.')
    except Exception as e:
        messages.error(request, str(e))

    return redirect('bank:admin_topup_list')


@login_required
def admin_topup_reject(request, topup_id):
    """Отклонить заявку на пополнение."""
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('dashboard:home')

    if request.method != 'POST':
        return redirect('bank:admin_topup_list')

    comment = request.POST.get('comment', '').strip()

    try:
        reject_topup(topup_id=topup_id, admin_user=request.user, comment=comment)
        messages.success(request, 'Заявка отклонена.')
    except Exception as e:
        messages.error(request, str(e))

    return redirect('bank:admin_topup_list')
