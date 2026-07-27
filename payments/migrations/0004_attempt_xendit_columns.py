"""
Migration 0004 – Sync PaymentGatewayAttempt with the Xendit model.

What the initial migration (0001) created (Midtrans era):
  • provider: choices=[("midtrans","Midtrans")], default="midtrans"
  • snap_token  CharField(max_length=160, blank=True)
  • redirect_url URLField(max_length=600, blank=True)
  • fraud_status CharField(max_length=32, blank=True)

What the current model expects (Xendit era):
  • provider: choices=[("xendit","Xendit")], default="xendit"
  • invoice_id  CharField(max_length=120, blank=True, db_index=True)
  • invoice_url URLField(max_length=600, blank=True)
  NO snap_token, NO redirect_url, NO fraud_status

This migration brings the database into alignment without touching any other
table. It is safe to run against an empty database (no data migration needed
because these columns were never written to by the Xendit code path).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0003_creatorpayout"),
    ]

    operations = [
        # 1. Drop the three Midtrans-only columns.
        migrations.RemoveField(
            model_name="paymentgatewayattempt",
            name="snap_token",
        ),
        migrations.RemoveField(
            model_name="paymentgatewayattempt",
            name="redirect_url",
        ),
        migrations.RemoveField(
            model_name="paymentgatewayattempt",
            name="fraud_status",
        ),
        # 2. Add the two Xendit-specific columns.
        migrations.AddField(
            model_name="paymentgatewayattempt",
            name="invoice_id",
            field=models.CharField(blank=True, db_index=True, max_length=120),
        ),
        migrations.AddField(
            model_name="paymentgatewayattempt",
            name="invoice_url",
            field=models.URLField(blank=True, max_length=600),
        ),
        # 3. Update the provider field to reflect the Xendit choice/default.
        #    AlterField keeps existing rows intact; only the schema metadata
        #    (choices list, default value) is updated.
        migrations.AlterField(
            model_name="paymentgatewayattempt",
            name="provider",
            field=models.CharField(
                choices=[("xendit", "Xendit")],
                default="xendit",
                max_length=24,
            ),
        ),
    ]
