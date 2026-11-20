from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum, F
from datetime import timedelta

from orders.models import OrderItem


@login_required
def seller_sales_analytics(request):
    if request.user.role != 'seller':
        return redirect('dashboard:home')

    period = request.GET.get('period', 'today')
    now = timezone.now()
    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == 'yesterday':
        start_date = start_date - timedelta(days=1)
        end_date = start_date + timedelta(days=1)
    elif period == 'week':
        start_date = start_date - timedelta(days=7)
        end_date = now
    elif period == 'month':
        start_date = start_date - timedelta(days=30)
        end_date = now
    else:
        end_date = now

    sold_items = OrderItem.objects.filter(
        order__status='delivered',
        product__seller=request.user
    ).select_related('order', 'product')

    if period == 'yesterday':
        sold_items = sold_items.filter(order__created_at__gte=start_date, order__created_at__lt=end_date)
    else:
        sold_items = sold_items.filter(order__created_at__gte=start_date, order__created_at__lte=end_date)

    sold_items = sold_items.order_by('-order__created_at')

    total_revenue = sold_items.annotate(
        item_revenue=F('quantity') * F('sale_price')
    ).aggregate(total=Sum('item_revenue'))['total'] or 0

    total_profit = sold_items.annotate(
        item_profit=(F('sale_price') - F('purchase_price')) * F('quantity')
    ).aggregate(total=Sum('item_profit'))['total'] or 0

    for item in sold_items:
        item.single_profit = item.sale_price - item.purchase_price
        item.total_profit = item.single_profit * item.quantity
        item.is_loss = item.single_profit < 0

    return render(request, 'orders/seller/sales_analytics.html', {
        'sold_items': sold_items,
        'total_revenue': total_revenue,
        'total_profit': total_profit,
        'current_period': period,
        'title': 'Финансовый отчет'
    })