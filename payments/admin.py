from django.contrib import admin

from .models import (
    CreatorPayout,
    ListingFeeInvoice,
    PaymentGatewayAttempt,
    PaymentGatewayEvent,
    PaymentGatewaySetting,
    PlatformFeeSetting,
)
from .services import dispatch_creator_payout


@admin.register(PaymentGatewayAttempt)
class PaymentGatewayAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "order_id",
        "purpose",
        "settlement",
        "listing_fee",
        "provider",
        "environment",
        "amount",
        "status",
        "payment_type",
        "created_at",
    )
    list_filter = ("purpose", "provider", "environment", "status", "payment_type")
    search_fields = (
        "order_id",
        "transaction_id",
        "settlement__invoice_number",
        "settlement__buyer__username",
        "listing_fee__invoice_number",
        "listing_fee__creator__username",
    )
    readonly_fields = (
        "public_id",
        "order_id",
        "invoice_id",
        "invoice_url",
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


@admin.register(PaymentGatewaySetting)
class PaymentGatewaySettingAdmin(admin.ModelAdmin):
    list_display = (
        "provider",
        "enabled",
        "is_production",
        "updated_at",
    )

    list_editable = (
        "enabled",
        "is_production",
    )


@admin.register(CreatorPayout)
class CreatorPayoutAdmin(admin.ModelAdmin):
    list_display = (
        "reference_id",
        "creator",
        "settlement",
        "amount",
        "status",
        "created_at",
    )

    actions = ("resend_creator_payout",)

    list_filter = (
        "status",
    )

    search_fields = (
        "reference_id",
        "creator__username",
    )

    readonly_fields = (
        "reference_id",
        "response_payload",
        "created_at",
        "updated_at",
        "completed_at",
    )

    @admin.action(description="Kirim ulang payout ke Xendit")
    def resend_creator_payout(self, request, queryset):
        sent = 0
        for payout in queryset:
            dispatch_creator_payout(payout.pk)
            sent += 1
        self.message_user(request, f"{sent} payout diproses ulang.")


@admin.register(PlatformFeeSetting)
class PlatformFeeSettingAdmin(admin.ModelAdmin):
    list_display = (
        "listing_fee_percent",
        "minimum_listing_fee",
        "vat_percent",
        "auto_payout_enabled",
        "updated_at",
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        # Konfigurasi bersifat singleton; baris dibuat otomatis oleh load().
        return not PlatformFeeSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ListingFeeInvoice)
class ListingFeeInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "nft",
        "creator",
        "fee_amount",
        "vat_amount",
        "total_amount",
        "status",
        "due_at",
        "paid_at",
    )
    list_filter = ("status",)
    search_fields = (
        "invoice_number",
        "nft__title",
        "creator__username",
    )
    readonly_fields = (
        "public_id",
        "invoice_number",
        "created_at",
        "updated_at",
    )

