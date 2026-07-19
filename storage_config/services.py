from __future__ import annotations

import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.core.exceptions import ImproperlyConfigured
from storages.backends.s3 import S3Storage

from .models import StorageConfiguration


class StorageConnectionError(RuntimeError):
    pass


def storage_options(configuration: StorageConfiguration) -> dict:
    if not configuration.is_complete:
        raise ImproperlyConfigured("Konfigurasi Cloudflare R2 belum lengkap.")

    options = {
        "access_key": configuration.access_key_id,
        "secret_key": configuration.get_secret_access_key(),
        "bucket_name": configuration.bucket_name,
        "endpoint_url": configuration.endpoint_url,
        "region_name": "auto",
        "signature_version": "s3v4",
        "addressing_style": "virtual",
        "default_acl": None,
        "file_overwrite": False,
        "location": configuration.location_prefix,
        "querystring_auth": configuration.use_signed_urls,
        "querystring_expire": configuration.signed_url_expiry,
    }
    if not configuration.use_signed_urls:
        options["custom_domain"] = configuration.custom_domain
        options["url_protocol"] = "https:"
    return options


def build_r2_storage(configuration: StorageConfiguration) -> S3Storage:
    return S3Storage(**storage_options(configuration))


def _client(configuration: StorageConfiguration):
    if not configuration.is_complete:
        raise StorageConnectionError("Konfigurasi Cloudflare R2 belum lengkap.")
    return boto3.client(
        "s3",
        endpoint_url=configuration.endpoint_url,
        region_name="auto",
        aws_access_key_id=configuration.access_key_id,
        aws_secret_access_key=configuration.get_secret_access_key(),
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=8,
            read_timeout=15,
            s3={"addressing_style": "virtual"},
        ),
    )


def test_r2_connection(configuration: StorageConfiguration) -> None:
    client = _client(configuration)
    prefix = configuration.location_prefix.strip("/")
    key = f"_batikcraft/connection-check/{uuid.uuid4().hex}.txt"
    if prefix:
        key = f"{prefix}/{key}"

    created = False
    try:
        client.put_object(
            Bucket=configuration.bucket_name,
            Key=key,
            Body=b"BatikCraft R2 connection check",
            ContentType="text/plain",
        )
        created = True
        client.head_object(Bucket=configuration.bucket_name, Key=key)
    except (BotoCoreError, ClientError, ImproperlyConfigured) as exc:
        detail = str(exc)
        if isinstance(exc, ClientError):
            error = exc.response.get("Error", {})
            detail = f"{error.get('Code', 'R2Error')}: {error.get('Message', str(exc))}"
        raise StorageConnectionError(
            f"Koneksi ke bucket R2 gagal: {detail}"
        ) from exc
    finally:
        if created:
            try:
                client.delete_object(Bucket=configuration.bucket_name, Key=key)
            except (BotoCoreError, ClientError):
                pass
