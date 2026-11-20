from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from orders.models import Order


@login_required
def courier_orders(request):
    if request.user.role != 'courier':
        return redirect('dashboard:home')

    return render(
        request,
        'orders/courier/courier_orders.html',
        {
            'delivery_orders': Order.objects.filter(status='delivering'),
            'route_orders': Order.objects.filter(
                courier=request.user,
                status='on_the_way'
            ),
            'completed_orders': Order.objects.filter(
                courier=request.user,
                status='delivered'
            ),
        }
    )