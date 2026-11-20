from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required

from orders.models import Order


@login_required
def update_order_status(request, order_id, new_status):
    order = get_object_or_404(Order, id=order_id)

    if request.user.role == 'employee':
        if order.status == 'new' and new_status == 'processing':
            order.status = 'processing'
            order.employee = request.user
            order.save()
            return redirect('orders:employee_processing_orders')

        elif order.status == 'processing' and new_status == 'delivering':
            order.status = 'delivering'
            order.save()
            return redirect('orders:employee_delivery_orders')

    elif request.user.role == 'courier':
        if order.status == 'delivering' and new_status == 'on_the_way':
            order.status = 'on_the_way'
            order.courier = request.user
            order.save()
            return redirect('orders:courier_orders')

        elif order.status == 'on_the_way' and new_status == 'delivered':
            order.status = 'delivered'
            order.save()
            return redirect('orders:courier_orders')

    return redirect('dashboard:home')