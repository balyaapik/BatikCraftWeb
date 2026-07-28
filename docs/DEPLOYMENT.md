# Deployment: VPS, MySQL, and Cloudflare R2

Moving BatikCraftWeb to a VPS with Django and Gunicorn, Nginx as a reverse proxy,
MySQL 8.0.11+ or 8.4 LTS on InnoDB, and optional Cloudflare R2 media storage.

---

## 1. Install the MySQL Driver

Ubuntu / Debian:

```bash
sudo apt update
sudo apt install -y build-essential default-libmysqlclient-dev pkg-config
python -m pip install -r requirements-mysql.txt
```

For local Docker testing:

```bash
docker compose -f docker-compose.mysql.yml up --build
```

---

## 2. Create the Database

```sql
CREATE DATABASE batikcraft
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'batikcraft'@'localhost' IDENTIFIED BY 'REPLACE_WITH_A_STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON batikcraft.* TO 'batikcraft'@'localhost';
FLUSH PRIVILEGES;
```

Use InnoDB. When `DATABASE_URL` points at MySQL, Django's configuration automatically
enables `utf8mb4`, `STRICT_TRANS_TABLES`, and the `read committed` isolation level.

```env
DATABASE_URL=mysql://batikcraft:URL_ENCODED_PASSWORD@127.0.0.1:3306/batikcraft
```

Special characters in the username or password must be URL-encoded.

---

## 3. Migrating Data from SQLite or PostgreSQL

Pause writes first so the snapshot is consistent.

```bash
python manage.py dumpdata \
  --natural-foreign \
  --natural-primary \
  --exclude contenttypes \
  --exclude auth.permission \
  --exclude sessions \
  --indent 2 \
  > batikcraft-data.json
```

**Back up the old database and the `media/` folder before continuing.**

Point `DATABASE_URL` at MySQL, then:

```bash
python manage.py migrate
python manage.py loaddata batikcraft-data.json
python manage.py check --database default
python manage.py test
```

Migration `core.0003_mysql_partial_unique_guards` creates MySQL-specific generated
columns and unique indexes that enforce:

- one `source_project_id` per creator;
- one `source_model_id` version per seller;
- one `paid` purchase per buyer and model.

Django may still warn that declarative partial unique constraints are unsupported on
MySQL. The equivalent integrity is held by those indexes.

---

## 4. The Credential Encryption Key

Generate a key **separate** from `DJANGO_SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(60))"
```

```env
BATIKCRAFT_CREDENTIAL_ENCRYPTION_KEY=THE_GENERATED_VALUE
```

This key encrypts the R2 credentials stored in the database. **Do not change or remove it
without re-entering the R2 Secret Access Key** — the stored value becomes undecryptable.
Keeping it separate is what lets `DJANGO_SECRET_KEY` be rotated safely.

---

## 5. Configuring Cloudflare R2

1. Create a **private** R2 bucket.
2. Create an API token with Object Read & Write, scoped to that bucket only.
3. Go to `/dashboard/admin/storage/`.
4. Fill in the Account ID, Access Key ID, Secret Access Key, and bucket name.
5. Leave **signed URLs** on so `.batikmodel` and `.batikpack` files stay private.
6. Press **Test connection and save**.

The standard endpoint is derived automatically:

```text
https://ACCOUNT_ID.r2.cloudflarestorage.com
```

Use a custom endpoint only for a jurisdiction-specific bucket or a particular
compatibility requirement.

### Custom Domain

A custom domain is only available with signed URLs **off**. That mode makes objects
publicly servable and is not recommended for a bucket holding licensed models or source
packages.

---

## 6. Migrating Local Media to R2

Inspect first, without uploading:

```bash
python manage.py migrate_media_to_r2 --dry-run
```

Copy everything:

```bash
python manage.py migrate_media_to_r2
```

Options:

```bash
# One prefix only
python manage.py migrate_media_to_r2 --prefix nfts

# Replace an R2 object when the key matches but the size differs
python manage.py migrate_media_to_r2 --overwrite

# Delete the local copy only after the R2 object is verified
python manage.py migrate_media_to_r2 --delete-local
```

Run without `--delete-local` first. Once the site and model downloads are verified, take
a backup and remove the local media folder deliberately.

---

## 7. Gunicorn

```bash
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn batikcraft_web.wsgi:application --bind 127.0.0.1:8000
```

Nginx continues to serve `/static/`. With R2 active, Nginx does not need to serve media
at all. Model and source package downloads are always streamed through Django after an
access check.

**Never add a `location /media/payment-proofs/` block.** Those files are private
financial documents; serving them by URL exposes them to anyone who guesses the path.

---

## 8. Scheduled Work

Auctions do not close themselves. Schedule:

```bash
python manage.py close_expired_auctions
```

---

## 9. Production Checklist

- [ ] `DJANGO_SECRET_KEY` rotated to a fresh value
- [ ] `BATIKCRAFT_CREDENTIAL_ENCRYPTION_KEY` set to a different fresh value
- [ ] `DJANGO_DEBUG=False`
- [ ] `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` filled in
- [ ] `DATABASE_URL` set
- [ ] Xendit configured, webhook token set
- [ ] `migrate` and `collectstatic` run
- [ ] `close_expired_auctions` scheduled
- [ ] R2 bucket private, signed URLs on
- [ ] Database and media backups verified restorable

The application refuses to start with `DJANGO_DEBUG=False` while `DJANGO_SECRET_KEY`
still holds the example value. With debug off, HSTS, `SECURE_SSL_REDIRECT`, and `Secure`
cookies are enabled by default.

---

## 10. Rollback

Back to local media:

1. Turn off **Use Cloudflare R2** in the admin dashboard.
2. Confirm the local `media/` folder is still present.
3. No restart is needed; the next upload uses local media immediately.

For a database rollback: stop the application, restore the previous database backup, then
point `DATABASE_URL` back.
