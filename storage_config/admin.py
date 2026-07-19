from django.contrib import admin

from .models import StorageConfiguration


@admin.register(StorageConfiguration)
class StorageConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "backend_status",
        "bucket_name",
        "account_id",
        "updated_at",
        "updated_by",
    )
    readonly_fields = (
        "singleton_id",
        "enabled",
        "account_id",
        "endpoint_override",
        "access_key_id",
        "bucket_name",
        "location_prefix",
        "use_signed_urls",
        "signed_url_expiry",
        "custom_domain",
        "updated_by",
        "updated_at",
        "secret_status",
    )
    fields = readonly_fields

    @admin.display(description="Backend")
    def backend_status(self, obj):
        return "Cloudflare R2" if obj.enabled else "Lokal VPS"

    @admin.display(description="Secret Access Key")
    def secret_status(self, obj):
        return "Tersimpan (terenkripsi)" if obj.has_secret_access_key else "Belum tersimpan"

    def has_add_permission(self, request):
        return not StorageConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
