from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def role_required(role):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if request.user.role != role and not request.user.is_superuser:
                messages.error(request, "Akun Anda tidak memiliki akses ke halaman tersebut.")
                return redirect("dashboard_router")
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
