from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from orders.models import Order, OrderItem
from products.models import Product
from orders.forms import OrderCheckoutForm

from bank.models import CustomerCard


@login_required
def create_order_from_product(request, product_id):
    if request.method != 'POST':
        return redirect('dashboard:home')

    if request.user.role != 'client':
        return redirect('dashboard:home')

    product = get_object_or_404(Product, id=product_id)

    try:
        quantity = int(request.POST.get('quantity', 1))
    except ValueError:
        messages.error(request, 'Некорректное количество')
        return redirect('products:detail', slug=product.slug)

    if quantity < 1:
        messages.error(request, 'Количество минимум 1')
        return redirect('products:detail', slug=product.slug)

    if product.stock <= 0:
        messages.error(request, 'Товар закончился')
        return redirect('products:detail', slug=product.slug)

    if quantity > product.stock:
        messages.error(request, f'Доступно только {product.stock} шт')
        return redirect('products:detail', slug=product.slug)

    order = Order.objects.create(
        client=request.user
    )

    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.title,
        quantity=quantity,
        purchase_price=product.purchase_price,
        sale_price=product.price
    )

    product.stock -= quantity
    product.save()

    messages.success(request, 'Заказ создан')
    return redirect('orders:client_orders')



# КАРДАРДЫН ЗАКАЗДАРЫ
@login_required
def client_orders(request):
    if request.user.role != 'client':
        return redirect('dashboard:home')

    active_orders = Order.objects.filter(
        client=request.user
    ).exclude(status='delivered').order_by('-created_at')

    delivered_orders = Order.objects.filter(
        client=request.user,
        status='delivered'
    ).order_by('-created_at')

    return render(request, 'orders/client/client_orders.html', {
        'active_orders': active_orders,
        'delivered_orders': delivered_orders,
    })

@login_required
def client_history(request):
    if request.user.role != 'client':
        return redirect('dashboard:home')

    orders = Order.objects.filter(
        client=request.user,
        status='delivered'
    ).order_by('-created_at')

    return render(
        request,
        'orders/client/client_history.html',
        {'orders': orders}
    )


@login_required
def cancel_order(request, order_id):
    order = get_object_or_404(
        Order,
        id=order_id,
        client=request.user
    )

    if order.status != 'new':
        return redirect('orders:client_orders')

    for item in order.items.all():
        if item.product:
            item.product.stock += item.quantity
            item.product.save()

    order.delete()
    return redirect('orders:client_orders')


@login_required
def edit_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, status='new')

    if request.method == 'POST':
        item_ids = request.POST.getlist('item_ids')
        quantities = request.POST.getlist('quantities')

        for item_id, qty in zip(item_ids, quantities):
            item = get_object_or_404(OrderItem, id=item_id, order=order)

            desired_qty = int(qty)
            if desired_qty <= item.product.stock and desired_qty > 0:
                item.quantity = desired_qty
                item.save()

        return redirect('orders:client_orders')

    return render(request, 'orders/client/edit_order.html', {'order': order})


# orders/views/client_orders.py
# Замени функцию create_order_from_cart на эту версию

@login_required
def create_order_from_cart(request):
    from cart.views import get_or_create_cart
    from bank.services import get_or_create_wallet, process_purchase
    from bank.models import Currency

    cart = get_or_create_cart(request)

    selected_str = request.GET.get('selected_items', '') or request.POST.get('selected_items', '')

    if selected_str:
        selected_ids = [int(i) for i in selected_str.split(',') if i.strip().isdigit()]
        cart_items = cart.items.filter(id__in=selected_ids)
    else:
        cart_items = cart.items.all()

    if request.method == 'GET':
        # Передаём баланс кошелька для отображения в шаблоне
        wallet = get_or_create_wallet(request.user)
        cards = CustomerCard.objects.filter(      # ← добавь эту строку
        user=request.user
        ).select_related('bank').order_by('-is_default')

        form = OrderCheckoutForm()
        return render(request, 'orders/checkout.html', {
            'form': form,
            'cart_items': cart_items,
            'selected_items_str': selected_str,
            'wallet_balance': wallet.balance,   # ← баланс для шаблона
            'customer_cards': cards,
            'order_total': sum(item.product.price * item.quantity for item in cart_items), 
        })

    if request.method == 'POST':
        form = OrderCheckoutForm(request.POST)

        if not cart_items.exists():
            return redirect('cart:detail')

        # Проверяем сток
        for item in cart_items:
            if item.quantity > item.product.stock:
                messages.error(request, f'Товар "{item.product.title}" закончился.')
                return redirect('cart:detail')

        if form.is_valid():
            payment_method = form.cleaned_data.get('payment_method', 'cash')

            # Если оплата с кошелька — проверяем баланс ПЕРЕД созданием заказа
            if payment_method == 'wallet':
                wallet = get_or_create_wallet(request.user)

                # Считаем общую сумму заказа
                order_total = sum(
                    item.product.price * item.quantity
                    for item in cart_items
                )

                if wallet.balance < order_total:
                    messages.error(
                        request,
                        f'Недостаточно средств на кошельке. '
                        f'Нужно: {order_total} KGS, '
                        f'на балансе: {wallet.balance} KGS.'
                    )
                    return render(request, 'orders/checkout.html', {
                        'form': form,
                        'cart_items': cart_items,
                        'selected_items_str': selected_str,
                        'wallet_balance': wallet.balance,
                        'customer_cards': cards,  
                        'order_total': sum(item.product.price * item.quantity for item in cart_items), 
                    })

            # Создаём заказ
            order = form.save(commit=False)
            order.client = request.user
            order.status = 'new'
            order.save()

            # Сохраняем товары
            for item in cart_items:
                OrderItem.objects.create(
                    order=order,
                    product=item.product,
                    product_name=item.product.title,
                    quantity=item.quantity,
                    purchase_price=item.product.purchase_price,
                    sale_price=item.product.price,
                )
                item.product.stock -= item.quantity
                item.product.save()

            # Если кошелёк — списываем деньги через bank.services
            if payment_method == 'wallet':
                try:
                    # Находим продавца первого товара
                    # (если несколько продавцов — нужна более сложная логика)
                    seller = cart_items.first().product.seller
                    process_purchase(
                        order=order,
                        buyer=request.user,
                        seller=seller,
                        amount=order_total,
                    )
                except Exception as e:
                    # Если списание не удалось — удаляем заказ и показываем ошибку
                    order.delete()
                    messages.error(request, f'Ошибка оплаты: {e}')
                    return render(request, 'orders/checkout.html', {
                        'form': form,
                        'cart_items': cart_items,
                        'selected_items_str': selected_str,
                        'wallet_balance': wallet.balance,
                    })

            # Удаляем из корзины
            cart_items.delete()

            messages.success(request, 'Заказ оформлен!')
            return redirect('orders:client_orders')

        else:
            wallet = get_or_create_wallet(request.user)
            return render(request, 'orders/checkout.html', {
                'form': form,
                'cart_items': cart_items,
                'selected_items_str': selected_str,
                'wallet_balance': wallet.balance,
                'order_total': sum(item.product.price * item.quantity for item in cart_items), 
            })

    return redirect('cart:detail')