from .midtrans import environment_name, is_enabled


def payment_gateway_context(request):
    return {
        "midtrans_enabled": is_enabled(),
        "midtrans_environment": environment_name(),
    }
