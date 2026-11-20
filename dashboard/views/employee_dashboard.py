from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from orders.models import Order
from ..mixins import EmployeeRequiredMixin


class EmployeeDashboardView(LoginRequiredMixin, EmployeeRequiredMixin, TemplateView):
    template_name = 'dashboard/employee.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context.update({
            'role': 'Сотрудник',
            # Новые — свободные, никем не взятые
            'new_orders': Order.objects.filter(
                status='new',
                claimed_by__isnull=True
            ).count(),
            # В обработке — только МОИ
            'processing_orders': Order.objects.filter(
                status='processing',
                claimed_by=user
            ).count(),
            # На доставку — только МОИ
            'delivering_orders': Order.objects.filter(
                status='delivering',
                claimed_by=user
            ).count(),
        })
        return context