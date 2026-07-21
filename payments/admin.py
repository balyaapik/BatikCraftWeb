from django.contrib import admin

from .models import PaymentGatewayAttempt, PaymentGatewayEvent


@admin.register(PaymentGatewayAttempt)
class PaymentGatewayAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "order_id",
        "settlement",
        "provider",
        "environment",
        "amount",
        "status",
        "payment_type",
        "created_at",
    )
    list_filter = ("provider", "environment", "status", "payment_type")
    search_fields = (
        "order_id",
        "transaction_id",
        "settlement__invoice_number",
        "settlement__buyer__username",
    )
    readonly_fields = (
        "public_id",
        "order_id",
        "snap_token",
        "redirect_url",
        "gateway_response",
        "created_at",
        "updated_at",
    )


@admin.register(PaymentGatewayEvent)
class PaymentGatewayEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_key",
        "attempt",
        "transaction_status",
        "signature_valid",
        "verified_with_api",
        "processed",
        "outcome",
        "created_at",
    )
    list_filter = (
        "transaction_status",
        "signature_valid",
        "verified_with_api",
        "processed",
    )
    search_fields = ("event_key", "attempt__order_id", "outcome")
    readonly_fields = (
        "attempt",
        "event_key",
        "transaction_status",
        "payload",
        "signature_valid",
        "verified_with_api",
        "processed",
        "outcome",
        "created_at",
    )
