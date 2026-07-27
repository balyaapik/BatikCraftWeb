from decimal import Decimal

from django.db import migrations


def backfill_vat(apps, schema_editor):
    """Samakan data lama dengan skema baru tanpa mengubah nilai tagihan.

    Invoice yang sudah terbit sebelum PPN diberlakukan tidak boleh berubah
    totalnya. Karena itu subtotal disamakan dengan total lama dan tarif PPN
    dicatat 0%, bukan 11%.
    """
    AuctionSettlement = apps.get_model("core", "AuctionSettlement")
    AuctionSettlement.objects.filter(subtotal_amount=Decimal("0.00")).update(
        subtotal_amount=models_f("amount"),
        vat_percent=Decimal("0.00"),
        vat_amount=Decimal("0.00"),
    )


def models_f(name):
    from django.db.models import F

    return F(name)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_auctionsettlement_subtotal_amount_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_vat, noop),
    ]
