import secrets

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


def generate_invite_code():
    return secrets.token_urlsafe(16)


class InviteCode(models.Model):
    code = models.CharField(
        max_length=64, unique=True, default=generate_invite_code, editable=False
    )
    username = models.CharField(max_length=64)
    name = models.CharField(max_length=120)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invites_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    used_by = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invite",
    )
    used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.username} ({self.code})"

    def get_absolute_url(self):
        return reverse("register", kwargs={"code": self.code})

    @property
    def is_used(self):
        return self.used_by_id is not None

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at < timezone.now()

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired

    def mark_used(self, user):
        self.used_by = user
        self.used_at = timezone.now()
        self.save(update_fields=["used_by", "used_at"])
