from decimal import Decimal
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, F, DecimalField

from products.models import Product
from orders.models import Order, OrderItem
from ..mixins import SellerRequiredMixin
from bank.services import get_or_create_wallet

class SellerDashboardView(LoginRequiredMixin, SellerRequiredMixin, TemplateView):
    template_name = 'dashboard/seller.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        sales_data = OrderItem.objects.filter(
            order__status='delivered', product__seller=user
        ).aggregate(total=Sum(F('quantity') * F('sale_price'), output_field=DecimalField()))

        wallet = get_or_create_wallet(user)

        context.update({
            'role': 'Продавец',
            'products_count': Product.objects.filter(seller=user).count(),
            'orders_count': Order.objects.count(),
            'total_sales_sum': sales_data['total'] or Decimal('0'),
            'seller_balance': wallet.balance,
        })
        return context