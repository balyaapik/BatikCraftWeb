from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework.authtoken.models import Token
from core.models import BlogPost, NFTAsset, User


class Command(BaseCommand):
    help = "Membuat akun dan konten demo BatikCraft"

    def handle(self, *args, **options):
        admin_user, _ = User.objects.get_or_create(username="admin_demo", defaults={
            "email": "admin@example.com", "display_name": "BatikCraft Admin", "role": User.Role.CREATOR,
            "is_staff": True, "is_superuser": True,
        })
        admin_user.email = "admin@example.com"
        admin_user.display_name = "BatikCraft Admin"
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.set_password("BatikCraft123!")
        admin_user.save()

        creator, _ = User.objects.get_or_create(username="creator_demo", defaults={
            "email": "creator@example.com", "display_name": "Sanggar Arunika", "role": User.Role.CREATOR
        })
        creator.set_password("BatikCraft123!")
        creator.save()
        buyer, _ = User.objects.get_or_create(username="buyer_demo", defaults={
            "email": "buyer@example.com", "display_name": "Nusantara Collector", "role": User.Role.BUYER
        })
        buyer.set_password("BatikCraft123!")
        buyer.save()
        Token.objects.get_or_create(user=creator)
        Token.objects.get_or_create(user=buyer)

        samples = [
            ("Sekar Jagad Harmoni", "https://images.unsplash.com/photo-1590246814883-57c511e25d45?auto=format&fit=crop&w=1000&q=80", "1250000"),
            ("Parang Sagara", "https://images.unsplash.com/photo-1583391733981-5d9f01e6a1c2?auto=format&fit=crop&w=1000&q=80", "1750000"),
            ("Kawung Digital", "https://images.unsplash.com/photo-1609942072337-c3370e820005?auto=format&fit=crop&w=1000&q=80", "950000"),
        ]
        for title, image_url, price in samples:
            NFTAsset.objects.get_or_create(owner=creator, title=title, defaults={
                "description": "Eksplorasi motif Nusantara melalui BatikCraft Studio.",
                "image_url": image_url,
                "status": NFTAsset.Status.LISTED,
                "starting_price": Decimal(price),
                "auction_starts_at": timezone.now(),
                "metadata": {"generated_with": "BatikCraft Studio"},
            })

        BlogPost.objects.get_or_create(slug="masa-depan-batik-digital", defaults={
            "title": "Masa Depan Batik Digital",
            "excerpt": "Teknologi generatif membuka cara baru untuk merancang, mengarsipkan, dan memperdagangkan karya batik.",
            "content": "BatikCraft menghubungkan proses kreatif di Studio dengan galeri digital dan marketplace. Setiap karya tetap membawa cerita, metadata proses, dan identitas kreatornya.",
            "is_published": True,
            "published_at": timezone.now(),
        })
        self.stdout.write(self.style.SUCCESS("Data demo berhasil dibuat."))
        self.stdout.write("Admin: admin_demo / BatikCraft123!")
        self.stdout.write("Creator: creator_demo / BatikCraft123!")
        self.stdout.write("Buyer: buyer_demo / BatikCraft123!")
