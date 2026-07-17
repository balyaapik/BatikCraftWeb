from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Bid,
    BlogPost,
    ModelAsset,
    ModelPurchase,
    NFTAsset,
    User,
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "BatikCraft",
            {
                "fields": (
                    "role",
                    "display_name",
                    "bio",
                    "wallet_address",
                    "avatar",
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("BatikCraft", {"fields": ("role", "email", "display_name")}),
    )
    list_display = ("username", "email", "role", "is_staff")
    list_filter = ("role", "is_staff", "is_active")


@admin.register(NFTAsset)
class NFTAssetAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "owner",
        "status",
        "starting_price",
        "created_at",
    )
    list_filter = ("status", "blockchain")
    search_fields = (
        "title",
        "owner__username",
        "source_project_id",
        "token_id",
    )


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("nft", "bidder", "amount", "created_at")
    search_fields = ("nft__title", "bidder__username")


@admin.register(ModelAsset)
class ModelAssetAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "seller",
        "version",
        "price",
        "status",
        "created_at",
    )
    list_filter = (
        "status",
        "category",
        "base_model_family",
        "license_type",
    )
    search_fields = (
        "name",
        "seller__username",
        "source_model_id",
        "version",
    )


@admin.register(ModelPurchase)
class ModelPurchaseAdmin(admin.ModelAdmin):
    list_display = (
        "model",
        "buyer",
        "amount_paid",
        "status",
        "download_count",
        "purchased_at",
    )
    list_filter = ("status",)
    search_fields = ("model__name", "buyer__username")


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "is_published",
        "published_at",
        "updated_at",
    )
    list_filter = ("is_published",)
    prepopulated_fields = {"slug": ("title",)}
