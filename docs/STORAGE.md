# Media Storage

Media is served either from a local directory on the server or from Cloudflare R2. The
mode is switched at `/dashboard/admin/storage/` and takes effect **without a restart**.

## Why the Indirection

Uploads do not go straight to `MEDIA_ROOT`. The `storage_config` app resolves a backend
at runtime from a singleton `StorageConfiguration` row. An administrator can therefore
move a live deployment between local disk and R2 without a redeploy, and roll back the
same way.

## Configuration

| Field | Notes |
| --- | --- |
| `enabled` | Off means local disk; on means R2 |
| `account_id` | Cloudflare account |
| `endpoint_override` | Blank derives `https://ACCOUNT_ID.r2.cloudflarestorage.com` |
| `access_key_id` | Stored in clear |
| Secret Access Key | Encrypted; **never displayed again** after saving |
| `bucket_name` | Target bucket |
| `location_prefix` | Defaults to `media`; blank stores from the bucket root |
| `use_signed_urls` | Recommended on |
| `signed_url_expiry` | Seconds; default 900 |
| `custom_domain` | Only usable with signed URLs off |

## Credential Encryption

The Secret Access Key is encrypted at rest with `BATIKCRAFT_CREDENTIAL_ENCRYPTION_KEY`,
which is deliberately **separate from `DJANGO_SECRET_KEY`**.

The reason is operational: rotating the Django secret key is a routine security action,
and if credentials were tied to it, every rotation would silently break media storage.
Changing or losing the credential key means re-entering the Secret Access Key by hand.

## Private by Default

Signed URLs with a private bucket are the recommended configuration.

Sensitive files — `.batikmodel` packages, `.batikpack` libraries, project sources, and
payment proofs — are **streamed through Django after an access check**, never served by a
direct storage URL. The download endpoints verify ownership, purchase status, or auction
outcome before releasing a byte.

A custom domain is only available with signed URLs off, which makes objects publicly
servable. Do not use it on a bucket holding licensed models or source packages.

## Payment Proofs

Stored under the `payment-proofs/` prefix and never linked as public media. The proof
endpoint checks that the requester is the transaction's creator, its buyer, or a
superuser.

With local media, **do not** add a `location /media/payment-proofs/` block to Nginx.

## Migrating Existing Media

```bash
python manage.py migrate_media_to_r2 --dry-run     # inspect, upload nothing
python manage.py migrate_media_to_r2               # copy everything
python manage.py migrate_media_to_r2 --prefix nfts # one prefix only
python manage.py migrate_media_to_r2 --overwrite   # replace on size mismatch
python manage.py migrate_media_to_r2 --delete-local # only after verification
```

Run without `--delete-local` first, verify the site and model downloads, take a backup,
then remove the local folder deliberately.

## Rollback

Turn off **Use Cloudflare R2**. Provided the local `media/` folder is intact, the next
upload uses local storage immediately. No restart.
