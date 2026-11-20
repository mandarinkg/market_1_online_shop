from django.urls import path
from . import views

app_name = 'orders'
 
urlpatterns = [
    # ---------------- CLIENT ----------------
    path('my-orders/', views.client_orders, name='client_orders'),
    path('history/', views.client_history, name='client_history'),
    path('create-from-product/<int:product_id>/', views.create_order_from_product, name='create_from_product'),
    path('cancel/<int:order_id>/', views.cancel_order, name='cancel_order'),
    path('edit/<int:order_id>/', views.edit_order, name='edit_order'),
    path('checkout/', views.create_order_from_cart, name='checkout'),
 
    # ---------------- EMPLOYEE ----------------
    path('employee/new/', views.employee_new_orders, name='employee_new_orders'),
    path('employee/processing/', views.employee_processing_orders, name='employee_processing_orders'),
    path('employee/delivery/', views.employee_delivery_orders, name='employee_delivery_orders'),
 
    # AJAX endpoints
    path('employee/claim/<int:order_id>/', views.ajax_claim_order, name='employee_claim_order'),
    path('employee/toggle-item/<int:item_id>/', views.ajax_toggle_item_collected, name='employee_toggle_item'),
    path('employee/send-delivery/<int:order_id>/', views.ajax_send_to_delivery, name='employee_send_delivery'),
 
    # ---------------- COURIER ----------------
    path('courier/', views.courier_orders, name='courier_orders'),
 
    # ---------------- ADMIN ----------------
    path('admin-orders/', views.admin_orders, name='admin_orders'),
 
    # ---------------- STATUS UPDATE (старый, оставь для других ролей) ----------------
    path('update/<int:order_id>/<str:new_status>/', views.update_order_status, name='update_status'),
 
    # ---------------- SELLER ANALYTICS ----------------
    path('seller/analytics/', views.seller_sales_analytics, name='seller_analytics'),
]
