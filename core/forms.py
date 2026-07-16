from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import Bid, NFTAsset, User


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "display_name", "role", "password1", "password2")


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("display_name", "email", "bio", "wallet_address", "avatar")
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}


class NFTForm(forms.ModelForm):
    class Meta:
        model = NFTAsset
        fields = (
            "title", "description", "image", "image_url", "starting_price", "reserve_price",
            "auction_starts_at", "auction_ends_at", "metadata",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "auction_starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "auction_ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "metadata": forms.Textarea(attrs={"rows": 5}),
        }


class BidForm(forms.ModelForm):
    class Meta:
        model = Bid
        fields = ("amount",)
        widgets = {"amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"})}
