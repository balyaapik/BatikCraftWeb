from django import forms

from .models import BlogPost, NFTAsset, User


class AdminBlogPostForm(forms.ModelForm):
    class Meta:
        model = BlogPost
        fields = (
            "title",
            "slug",
            "excerpt",
            "content",
            "cover_url",
            "is_published",
            "published_at",
        )
        widgets = {
            "excerpt": forms.Textarea(attrs={"rows": 3, "maxlength": 320}),
            "content": forms.Textarea(attrs={"rows": 18}),
            "published_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Kosongkan untuk membuat slug otomatis dari judul."


class AdminUserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "username",
            "display_name",
            "email",
            "role",
            "bio",
            "wallet_address",
            "is_active",
            "is_staff",
        )
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}


class AdminNFTForm(forms.ModelForm):
    class Meta:
        model = NFTAsset
        fields = (
            "owner",
            "title",
            "description",
            "image",
            "image_url",
            "status",
            "starting_price",
            "reserve_price",
            "auction_starts_at",
            "auction_ends_at",
            "token_id",
            "blockchain",
            "contract_address",
            "source_project_id",
            "source_app_version",
            "metadata",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "auction_starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "auction_ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "metadata": forms.Textarea(attrs={"rows": 8}),
        }
