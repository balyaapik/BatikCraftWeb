"""
Migration 0005 – Sync PaymentGatewaySetting with the Xendit model.

What migration 0002 created (Midtrans era):
  • provider: choices=[("midtrans","Midtrans")], default="midtrans"
  • is_production: help_text referring to "Midtrans Production"
  • server_key     CharField(max_length=255, blank=True)
  • client_key     CharField(max_length=255, blank=True)
  • merchant_id    CharField(max_length=100, blank=True)
  • allowed_payments TextField(default="qris,gopay,...")

What the current model expects (Xendit era):
  • provider: choices=[("xendit","Xendit")], default="xendit"
  • is_production: help_text="Centang jika menggunakan Xendit Live API key."
  • api_key        CharField(max_length=255, blank=True)
  • webhook_token  CharField(max_length=255, blank=True)
  NO server_key, NO client_key, NO merchant_id, NO allowed_payments
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0004_attempt_xendit_columns"),
    ]

    operations = [
        # 1. Drop the four Midtrans-only columns.
        migrations.RemoveField(
            model_name="paymentgatewaysetting",
            name="server_key",
        ),
        migrations.RemoveField(
            model_name="paymentgatewaysetting",
            name="client_key",
        ),
        migrations.RemoveField(
            model_name="paymentgatewaysetting",
            name="merchant_id",
        ),
        migrations.RemoveField(
            model_name="paymentgatewaysetting",
            name="allowed_payments",
        ),
        # 2. Add the two Xendit-specific columns.
        migrations.AddField(
            model_name="paymentgatewaysetting",
            name="api_key",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="paymentgatewaysetting",
            name="webhook_token",
            field=models.CharField(blank=True, max_length=255),
        ),
        # 3. Update provider choices/default to Xendit.
        migrations.AlterField(
            model_name="paymentgatewaysetting",
            name="provider",
            field=models.CharField(
                choices=[("xendit", "Xendit")],
                default="xendit",
                max_length=24,
                unique=True,
            ),
        ),
        # 4. Update is_production help_text to mention Xendit.
        migrations.AlterField(
            model_name="paymentgatewaysetting",
            name="is_production",
            field=models.BooleanField(
                default=False,
                help_text="Centang jika menggunakan Xendit Live API key.",
            ),
        ),
    ]
