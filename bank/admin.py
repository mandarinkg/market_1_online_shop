"""
bank/admin.py

Панель администратора для:
  - Просмотра кошельков и балансов
  - Обработки заявок на вывод (одобрить / отклонить)
  - Просмотра леджера (только чтение)
  - Верификации банковских реквизитов
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.contrib import messages

from .models import Wallet, FrozenBalance, Transaction, LedgerEntry, BankRequisites, PayoutRequest
from .services import approve_payout, reject_payout


# ==============================================================================
# WALLET
# ==============================================================================

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display  = ('user', 'currency', 'balance', 'frozen_total', 'created_at')
    list_filter   = ('currency',)
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('id', 'created_at', 'updated_at')

    def frozen_total(self, obj):
        """Сумма всех активных заморозок."""
        from django.db.models import Sum
        total = obj.frozen_entries.filter(is_released=False).aggregate(
            s=Sum('amount')
        )['s'] or 0
        return f'{total} KGS'

    frozen_total.short_description = 'Заморожено'


# ==============================================================================
# FROZEN BALANCE
# ==============================================================================

@admin.register(FrozenBalance)
class FrozenBalanceAdmin(admin.ModelAdmin):
    list_display  = ('wallet', 'amount', 'order', 'payout_request', 'is_released', 'created_at')
    list_filter   = ('is_released',)
    search_fields = ('wallet__user__username',)
    readonly_fields = ('id', 'created_at', 'released_at')


# ==============================================================================
# TRANSACTION + LEDGER (только чтение — финансовый аудит)
# ==============================================================================

class LedgerEntryInline(admin.TabularInline):
    model = LedgerEntry
    extra = 0
    readonly_fields = ('id', 'wallet', 'entry_type', 'amount', 'balance_before', 'balance_after', 'created_at')

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display  = ('id', 'transaction_type', 'order', 'initiated_by', 'created_at')
    list_filter   = ('transaction_type',)
    search_fields = ('initiated_by__username',)
    readonly_fields = ('id', 'created_at')
    inlines = [LedgerEntryInline]

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display  = ('id', 'wallet', 'entry_type', 'amount', 'balance_before', 'balance_after', 'created_at')
    list_filter   = ('entry_type',)
    search_fields = ('wallet__user__username',)
    readonly_fields = ('id', 'transaction', 'wallet', 'entry_type', 'amount',
                       'balance_before', 'balance_after', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ==============================================================================
# BANK REQUISITES
# ==============================================================================

@admin.register(BankRequisites)
class BankRequisitesAdmin(admin.ModelAdmin):
    list_display  = ('user', 'bank_name', 'bik', 'account_number', 'requisite_type', 'is_verified', 'is_default')
    list_filter   = ('requisite_type', 'is_verified')
    search_fields = ('user__username', 'bik', 'account_number', 'inn')
    readonly_fields = ('id', 'created_at')
    actions = ['verify_requisites']

    def verify_requisites(self, request, queryset):
        updated = queryset.update(is_verified=True)
        self.message_user(request, f'{updated} реквизитов верифицировано.', messages.SUCCESS)

    verify_requisites.short_description = 'Верифицировать выбранные реквизиты'


# ==============================================================================
# PAYOUT REQUEST — главная страница для администратора
# ==============================================================================

@admin.register(PayoutRequest)
class PayoutRequestAdmin(admin.ModelAdmin):
    list_display  = (
        'id', 'user', 'amount_display', 'status_colored',
        'requisites_info', 'created_at', 'processed_by', 'processed_at'
    )
    list_filter   = ('status',)
    search_fields = ('user__username', 'user__email')
    readonly_fields = (
        'id', 'user', 'wallet', 'requisites', 'amount',
        'created_at', 'processed_at', 'processed_by',
    )
    actions = ['action_approve', 'action_reject']

    fieldsets = (
        ('Заявка', {
            'fields': ('id', 'user', 'wallet', 'amount', 'status', 'created_at')
        }),
        ('Реквизиты', {
            'fields': ('requisites',)
        }),
        ('Обработка', {
            'fields': ('processed_by', 'processed_at', 'admin_comment')
        }),
    )

    def amount_display(self, obj):
        return f'{obj.amount} KGS'
    amount_display.short_description = 'Сумма'

    def status_colored(self, obj):
        colors = {
            'pending':   '#f59e0b',
            'approved':  '#3b82f6',
            'completed': '#22c55e',
            'rejected':  '#ef4444',
        }
        color = colors.get(obj.status, '#94a3b8')
        return format_html(
            '<span style="color:{};font-weight:700;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_colored.short_description = 'Статус'

    def requisites_info(self, obj):
        r = obj.requisites
        return format_html(
            '<small>{}<br>БИК: {} | Р/с: {}</small>',
            r.bank_name, r.bik, r.account_number
        )
    requisites_info.short_description = 'Реквизиты'

    def action_approve(self, request, queryset):
        """Одобрить выбранные заявки."""
        success = 0
        for payout in queryset.filter(status='pending'):
            try:
                approve_payout(payout.id, admin_user=request.user, comment='Одобрено через панель')
                success += 1
            except Exception as e:
                self.message_user(request, f'Ошибка #{payout.id}: {e}', messages.ERROR)
        if success:
            self.message_user(request, f'{success} заявок одобрено.', messages.SUCCESS)

    action_approve.short_description = '✅ Одобрить заявки'

    def action_reject(self, request, queryset):
        """Отклонить выбранные заявки."""
        success = 0
        for payout in queryset.filter(status='pending'):
            try:
                reject_payout(payout.id, admin_user=request.user, comment='Отклонено через панель')
                success += 1
            except Exception as e:
                self.message_user(request, f'Ошибка #{payout.id}: {e}', messages.ERROR)
        if success:
            self.message_user(request, f'{success} заявок отклонено.', messages.SUCCESS)

    action_reject.short_description = '❌ Отклонить заявки'