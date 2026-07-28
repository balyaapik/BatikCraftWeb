from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from core.admin_views import admin_required

from .forms import PaymentGatewaySettingForm
from .models import PaymentGatewaySetting
from .xendit import environment_name, is_enabled


@admin_required
@require_http_methods(["GET", "POST"])
def payment_gateway_settings(request):
    configuration = PaymentGatewaySetting.objects.filter(
        provider=PaymentGatewaySetting.Provider.XENDIT
    ).first()

    if request.method == "POST" and request.POST.get("action") == "reset_environment":
        if configuration is not None:
            configuration.delete()
            messages.success(
                request,
                "Override database dihapus. Checkout kembali mengikuti environment server.",
            )
        else:
            messages.info(request, "Checkout sudah mengikuti environment server.")
        return redirect("admin_dashboard:payment_gateway_settings")

    form_instance = configuration or PaymentGatewaySetting(
        provider=PaymentGatewaySetting.Provider.XENDIT
    )
    form = PaymentGatewaySettingForm(request.POST or None, instance=form_instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Konfigurasi Xendit berhasil disimpan.")
        return redirect("admin_dashboard:payment_gateway_settings")

    using_database = configuration is not None
    active_api_key = (
        configuration.api_key
        if using_database
        else str(getattr(settings, "XENDIT_API_KEY", "") or "")
    )
    active_webhook_token = (
        configuration.webhook_token
        if using_database
        else str(getattr(settings, "XENDIT_WEBHOOK_TOKEN", "") or "")
    )
    webhook_url = request.build_absolute_uri(reverse("payments:xendit_webhook"))

    return render(
        request,
        "admin_dashboard/payment_gateway_settings.html",
        {
            "form": form,
            "configuration": configuration,
            "using_database": using_database,
            "gateway_enabled": is_enabled(),
            "gateway_environment": environment_name(),
            "api_key_present": bool(active_api_key.strip()),
            "webhook_token_present": bool(active_webhook_token.strip()),
            "webhook_url": webhook_url,
        },
    )
