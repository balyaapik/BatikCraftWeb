from .xendit import environment_name, is_enabled


def payment_gateway_context(request):
    return {
        "xendit_enabled": is_enabled(),
        "xendit_environment": environment_name(),
    }
