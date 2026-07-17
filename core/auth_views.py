from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as django_auth_views
from django.shortcuts import redirect, render

from .captcha import captcha_image
from .forms import CaptchaAuthenticationForm, RegistrationForm


class CaptchaLoginView(django_auth_views.LoginView):
    """Website login that requires a fresh session-bound CAPTCHA."""

    template_name = "registration/login.html"
    authentication_form = CaptchaAuthenticationForm



def register(request):
    """Create a web account only after the CAPTCHA and user fields validate."""

    if request.user.is_authenticated:
        return redirect("dashboard_router")
    form = RegistrationForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Akun berhasil dibuat.")
        return redirect("dashboard_router")
    return render(request, "registration/register.html", {"form": form})


__all__ = ["CaptchaLoginView", "captcha_image", "register"]
