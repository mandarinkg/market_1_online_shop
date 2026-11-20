# bank/urls.py — полная версия, замени свой файл

from django.urls import path
from . import views

app_name = 'bank'

urlpatterns = [
    # ── ПРОДАВЕЦ ──
    path('balance/',                             views.seller_balance,       name='seller_balance'),
    path('requisites/',                          views.requisites_list,      name='requisites_list'),
    path('requisites/add/',                      views.requisites_add,       name='requisites_add'),
    path('requisites/<uuid:pk>/delete/',         views.requisites_delete,    name='requisites_delete'),
    path('payout/create/',                       views.payout_create,        name='payout_create'),

    # ── КЛИЕНТ ──
    path('wallet/',                              views.client_wallet,        name='client_wallet'),
    path('wallet/payout/',                       views.client_payout_create, name='client_payout_create'),
    path('wallet/topup/',                        views.topup_create,         name='topup_create'),       # ← новый

    # ── КАРТЫ КЛИЕНТА ──
    path('cards/',                               views.cards_list,           name='cards_list'),
    path('cards/add/',                           views.card_add,             name='card_add'),
    path('cards/set-default/',                   views.card_set_default,     name='card_set_default'),
    path('cards/delete/',                        views.card_delete,          name='card_delete'),

    # ── АДМИНИСТРАТОР — ВЫПЛАТЫ ──
    path('admin/payouts/',                                  views.admin_payout_list,    name='admin_payout_list'),
    path('admin/payouts/<uuid:payout_id>/approve/',         views.admin_payout_approve, name='admin_payout_approve'),
    path('admin/payouts/<uuid:payout_id>/reject/',          views.admin_payout_reject,  name='admin_payout_reject'),

    # ── АДМИНИСТРАТОР — ПОПОЛНЕНИЯ ──
    path('admin/topups/',                                   views.admin_topup_list,    name='admin_topup_list'),    # ← новый
    path('admin/topups/<uuid:topup_id>/approve/',           views.admin_topup_approve, name='admin_topup_approve'), # ← новый
    path('admin/topups/<uuid:topup_id>/reject/',            views.admin_topup_reject,  name='admin_topup_reject'),  # ← новый
]