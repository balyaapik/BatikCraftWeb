from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Bid, BlogPost, NFTAsset, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("BatikCraft", {"fields": ("role", "display_name", "bio", "wallet_address", "avatar")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("BatikCraft", {"fields": ("role", "email", "display_name")}),)
    list_display = ("username", "email", "role", "is_staff")
    list_filter = ("role", "is_staff", "is_active")


@admin.register(NFTAsset)
class NFTAssetAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "status", "starting_price", "created_at")
    list_filter = ("status", "blockchain")
    search_fields = ("title", "owner__username", "source_project_id", "token_id")


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("nft", "bidder", "amount", "created_at")
    search_fields = ("nft__title", "bidder__username")


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ("title", "is_published", "published_at", "updated_at")
    list_filter = ("is_published",)
    prepopulated_fields = {"slug": ("title",)}
