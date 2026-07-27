"""Aktifkan zona waktu tampilan sesuai preferensi pengguna.

Batas waktu lelang dan pembayaran tetap disimpan dalam UTC di basis data.
Middleware ini hanya menentukan zona waktu yang dipakai Django untuk merender
tanggal dan untuk menafsirkan masukan form yang tidak menyertakan offset.
"""

from __future__ import annotations

from django.utils import timezone

from .models import MarketplaceSetting, is_valid_timezone


def resolve_timezone(request) -> str:
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.timezone_name:
        if is_valid_timezone(user.timezone_name):
            return user.timezone_name
    default = MarketplaceSetting.load().default_timezone
    return default if is_valid_timezone(default) else "UTC"


class ActiveTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone.activate(resolve_timezone(request))
        try:
            return self.get_response(request)
        finally:
            # Thread pekerja dipakai ulang; jangan bocorkan zona waktu antar-request.
            timezone.deactivate()
