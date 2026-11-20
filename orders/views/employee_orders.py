from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction

from orders.models import Order, OrderItem


def _employee_required(request):
    """Вспомогательная проверка роли сотрудника."""
    return request.user.is_authenticated and request.user.role == 'employee'


# ==============================================================================
# ЭТАП 1 — НОВЫЕ ЗАКАЗЫ
# ==============================================================================

@login_required
def employee_new_orders(request):
    if not _employee_required(request):
        return redirect('dashboard:home')

    # Сотрудник видит только:
    # 1) заказы без claimed_by (никто не взял)
    # 2) заказы которые взял именно он сам
    orders = Order.objects.filter(
        status='new'
    ).filter(
        claimed_by__isnull=True  # свободные заказы
    ).prefetch_related(
        'items__product__shop',
        'items__product__seller',
    ).order_by('-created_at')

    return render(request, 'orders/employee/employee_new_orders.html', {
        'orders': orders,
    })


@login_required
@require_POST
def ajax_claim_order(request, order_id):
    """
    AJAX: сотрудник принимает заказ.
    - claimed_by = request.user (изоляция — другие не увидят)
    - status → processing
    - страница не перезагружается
    """
    if not _employee_required(request):
        return JsonResponse({'ok': False, 'error': 'Нет доступа'}, status=403)

    with transaction.atomic():
        order = Order.objects.select_for_update().filter(
            id=order_id,
            status='new',
            claimed_by__isnull=True,  # защита от гонки
        ).first()

        if not order:
            return JsonResponse({
                'ok': False,
                'error': 'Заказ уже взят другим сотрудником или не существует'
            }, status=409)

        order.claimed_by = request.user
        order.employee = request.user
        order.status = 'processing'
        order.save(update_fields=['claimed_by', 'employee', 'status'])

    return JsonResponse({'ok': True, 'order_id': order_id})


# ==============================================================================
# ЭТАП 2 — СБОРКА (PROCESSING)
# ==============================================================================

@login_required
def employee_processing_orders(request):
    if not _employee_required(request):
        return redirect('dashboard:home')

    # Сотрудник видит ТОЛЬКО свои заказы на сборке
    orders = Order.objects.filter(
        status='processing',
        claimed_by=request.user,
    ).prefetch_related(
        'items__product__shop',
        'items__product__seller',
    ).order_by('-created_at')

    # Считаем прогресс сборки для каждого заказа
    orders_data = []
    for order in orders:
        items = list(order.items.all())
        total = len(items)
        collected = sum(1 for i in items if i.is_collected)
        orders_data.append({
            'order': order,
            'items': items,
            'total': total,
            'collected': collected,
            'all_collected': total > 0 and collected == total,
            'pct': int(collected / total * 100) if total > 0 else 0,
        })

    return render(request, 'orders/employee/employee_processing_orders.html', {
        'orders_data': orders_data,
    })


@login_required
@require_POST
def ajax_toggle_item_collected(request, item_id):
    """
    AJAX: переключить галочку is_collected на позиции заказа.
    Только сотрудник который взял этот заказ может менять.
    """
    if not _employee_required(request):
        return JsonResponse({'ok': False, 'error': 'Нет доступа'}, status=403)

    item = get_object_or_404(
        OrderItem.objects.select_related('order'),
        id=item_id,
        order__claimed_by=request.user,   # только свои
        order__status='processing',
    )

    item.is_collected = not item.is_collected
    item.save(update_fields=['is_collected'])

    # Проверяем — все ли позиции собраны
    order = item.order
    all_collected = not order.items.filter(is_collected=False).exists()

    return JsonResponse({
        'ok': True,
        'is_collected': item.is_collected,
        'all_collected': all_collected,
        'order_id': order.id,
    })


@login_required
@require_POST
def ajax_send_to_delivery(request, order_id):
    """
    AJAX: перевести заказ на этап 'delivering' (передать курьеру).
    Только если все позиции собраны.
    """
    if not _employee_required(request):
        return JsonResponse({'ok': False, 'error': 'Нет доступа'}, status=403)

    with transaction.atomic():
        order = Order.objects.select_for_update().filter(
            id=order_id,
            status='processing',
            claimed_by=request.user,
        ).first()

        if not order:
            return JsonResponse({'ok': False, 'error': 'Заказ не найден'}, status=404)

        if order.items.filter(is_collected=False).exists():
            return JsonResponse({
                'ok': False,
                'error': 'Не все товары собраны'
            }, status=400)

        order.status = 'delivering'
        order.save(update_fields=['status'])

    return JsonResponse({'ok': True, 'order_id': order_id})


# ==============================================================================
# ЭТАП 3 — ПЕРЕДАЧА КУРЬЕРУ (DELIVERING)
# ==============================================================================

@login_required
def employee_delivery_orders(request):
    if not _employee_required(request):
        return redirect('dashboard:home')

    # Сотрудник видит только заказы которые он собирал
    orders = Order.objects.filter(
        status='delivering',
        claimed_by=request.user,
    ).prefetch_related(
        'items__product__shop',
        'items__product__seller',
    ).order_by('-created_at')

    return render(request, 'orders/employee/employee_delivery_orders.html', {
        'orders': orders,
    })