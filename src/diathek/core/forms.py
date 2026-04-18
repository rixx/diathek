from django import forms
from django.contrib.auth.password_validation import validate_password

from diathek.core.models import Box, User


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


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        items = list(data) if isinstance(data, (list, tuple)) else [data]
        if not items and self.required:
            raise forms.ValidationError(self.error_messages["required"])
        return [single_clean(item, initial) for item in items]


class ImportForm(forms.Form):
    BOX_UNSORTED = "__unsorted__"
    BOX_NEW = "__new__"

    box_choice = forms.ChoiceField(label="Box")
    new_box_name = forms.CharField(
        label="Name der neuen Box", required=False, max_length=200
    )
    new_box_description = forms.CharField(
        label="Beschreibung der neuen Box",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    files = MultipleFileField(label="Dateien")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [
            (self.BOX_UNSORTED, "— Ohne Box (später zuordnen) —"),
            (self.BOX_NEW, "+ Neue Box anlegen"),
        ]
        choices.extend(
            (str(box.pk), box.name)
            for box in Box.objects.filter(archived=False).order_by("sort_order", "name")
        )
        self.fields["box_choice"].choices = choices

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("box_choice") == self.BOX_NEW and not cleaned.get(
            "new_box_name"
        ):
            self.add_error(
                "new_box_name", "Bitte einen Namen für die neue Box angeben."
            )
        return cleaned
