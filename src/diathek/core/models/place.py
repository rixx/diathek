from django.db import models

from diathek.core.models.base import BaseModel


class PlaceManager(models.Manager):
    def recent(self, limit=10):
        return (
            self.get_queryset()
            .annotate(last_used=models.Max("images__updated_at"))
            .order_by(models.F("last_used").desc(nulls_last=True), "name")[:limit]
        )


class Place(BaseModel):
    name = models.CharField(max_length=200, unique=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )

    log_action_prefix = "place"
    log_tracked_fields = ("name", "latitude", "longitude")

    objects = PlaceManager()

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    @property
    def has_coords(self):
        return self.latitude is not None and self.longitude is not None
