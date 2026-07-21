from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path(
        "settlements/<uuid:public_id>/checkout/",
        views.start_midtrans_checkout,
        name="start_checkout",
    ),
    path(
        "settlements/<uuid:public_id>/status/",
        views.settlement_gateway_status,
        name="settlement_status",
    ),
    path(
        "settlements/<uuid:public_id>/sync/",
        views.sync_midtrans_status,
        name="sync_status",
    ),
    path(
        "midtrans/webhook/",
        views.midtrans_webhook,
        name="midtrans_webhook",
    ),
]
