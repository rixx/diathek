from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from diathek.core.models.base import BaseModel


class DriverState(BaseModel):
    PRESENCE_WINDOW_SECONDS = 60

    current_box = models.ForeignKey(
        "core.Box", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    current_image = models.ForeignKey(
        "core.Image", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    log_action_prefix = None

    def __str__(self):
        return f"DriverState(driver={self.driver_id}, image={self.current_image_id})"

    @classmethod
    def get(cls):
        """Return the singleton DriverState row.

        Missing is a hard error, not a silent reconstruction — the row is
        provisioned by a data migration at install time. See PLAN.md.
        """
        return cls.objects.get(pk=1)

    @classmethod
    def presence_cutoff(cls):
        return timezone.now() - timedelta(seconds=cls.PRESENCE_WINDOW_SECONDS)

    @property
    def active_driver(self):
        if self.driver is None:
            return None
        if self.driver.last_poll is None:
            return None
        if self.driver.last_poll < self.presence_cutoff():
            return None
        return self.driver
