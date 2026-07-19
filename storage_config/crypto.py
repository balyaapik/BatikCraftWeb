import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet() -> Fernet:
    source = str(
        getattr(settings, "BATIKCRAFT_CREDENTIAL_ENCRYPTION_KEY", "")
        or settings.SECRET_KEY
    )
    if not source:
        raise ImproperlyConfigured(
            "BATIKCRAFT_CREDENTIAL_ENCRYPTION_KEY atau DJANGO_SECRET_KEY wajib tersedia."
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(source.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ImproperlyConfigured(
            "Kredensial R2 tidak dapat didekripsi. Periksa kunci enkripsi aplikasi."
        ) from exc
