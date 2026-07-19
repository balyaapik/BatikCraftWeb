from django.contrib import messages
from django.shortcuts import redirect, render

from core.admin_views import admin_required

from .forms import StorageConfigurationForm
from .models import StorageConfiguration
from .services import StorageConnectionError, test_r2_connection


@admin_required
def storage_settings(request):
    configuration = StorageConfiguration.get_solo()
    form = StorageConfigurationForm(
        request.POST or None,
        instance=configuration,
    )

    if request.method == "POST" and form.is_valid():
        candidate = form.save(commit=False)
        candidate.updated_by = request.user
        action = request.POST.get("action", "save")

        if action == "save_test":
            try:
                test_r2_connection(candidate)
            except StorageConnectionError as exc:
                messages.error(request, str(exc))
            else:
                candidate.save()
                messages.success(
                    request,
                    "Koneksi Cloudflare R2 berhasil dan konfigurasi telah disimpan.",
                )
                return redirect("admin_dashboard:storage_settings")
        else:
            candidate.save()
            state = "Cloudflare R2" if candidate.enabled else "penyimpanan lokal VPS"
            messages.success(request, f"Konfigurasi disimpan. Backend aktif: {state}.")
            return redirect("admin_dashboard:storage_settings")

    context = {
        "form": form,
        "configuration": configuration,
        "backend_label": (
            "Cloudflare R2" if configuration.enabled else "Penyimpanan lokal VPS"
        ),
    }
    return render(request, "admin_dashboard/storage_settings.html", context)
