from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path(
        "settlements/<uuid:public_id>/checkout/",
        views.start_xendit_checkout,
        name="start_checkout",
    ),
    path(
        "settlements/<uuid:public_id>/status/",
        views.settlement_gateway_status,
        name="settlement_status",
    ),
    path(
        "settlements/<uuid:public_id>/sync/",
        views.sync_xendit_status,
        name="sync_status",
    ),
    path(
        "xendit/webhook/",
        views.xendit_webhook,
        name="xendit_webhook",
    ),
]
