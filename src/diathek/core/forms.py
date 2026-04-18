from django import forms
from django.contrib.auth.password_validation import validate_password

from diathek.core.models import User


class RegistrationForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput, label="Passwort", strip=False
    )
    password_repeat = forms.CharField(
        widget=forms.PasswordInput, label="Passwort wiederholen", strip=False
    )

    def __init__(self, *args, invite, **kwargs):
        super().__init__(*args, **kwargs)
        self.invite = invite

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        repeat = cleaned.get("password_repeat")
        if password and repeat and password != repeat:
            self.add_error("password_repeat", "Passwörter stimmen nicht überein.")
        return cleaned

    def save(self):
        user = User.objects.create_user(
            username=self.invite.username,
            name=self.invite.name,
            password=self.cleaned_data["password"],
        )
        self.invite.mark_used(user)
        return user
