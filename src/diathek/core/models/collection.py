from django.db import models

from diathek.core.models.base import BaseModel


class Collection(BaseModel):
    title = models.CharField(max_length=200)
    immich_url = models.URLField(blank=True)
    description = models.TextField(blank=True)
    cover_image = models.ForeignKey(
        "core.Image",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cover_for_collections",
    )
    boxes = models.ManyToManyField("core.Box", related_name="collections", blank=True)

    log_action_prefix = "collection"
    log_tracked_fields = ("title", "immich_url", "description", "cover_image")

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title
