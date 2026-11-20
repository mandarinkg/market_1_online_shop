from .client_orders import (
    create_order_from_product,
    client_orders,
    client_history,
    cancel_order,
    edit_order,
    create_order_from_cart,
)
from .admin_orders import (
    admin_orders,
)
from .employee_orders import (
    employee_new_orders,
    employee_processing_orders,
    employee_delivery_orders,
    ajax_claim_order,
    ajax_toggle_item_collected,
    ajax_send_to_delivery,
)
from .courier_orders import (
    courier_orders,
)
from .status_update import (
    update_order_status,
)
from .seller_orders import (
    seller_sales_analytics,
)