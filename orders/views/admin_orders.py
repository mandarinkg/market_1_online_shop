from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from orders.models import Order


@login_required
def admin_orders(request):
    if not (request.user.is_staff or request.user.is_superuser):
        from django.shortcuts import redirect
        return redirect('dashboard:home')

    orders = Order.objects.select_related(
        'client',
        'claimed_by',
        'courier',
    ).prefetch_related(
        'items__product__shop',
        'items__product__seller',
    ).order_by('-created_at')

    return render(
        request,
        'orders/admin/admin_orders.html',
        {'orders': orders}
    )