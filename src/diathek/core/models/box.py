import uuid

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.utils import timezone

from diathek.core.models.base import BaseModel


class Box(BaseModel):
    name = models.CharField(max_length=200)
    uuid = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, db_index=True
    )
    description = models.TextField(blank=True)
    sort_order = models.IntegerField(default=0)
    archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    log_action_prefix = "box"
    log_tracked_fields = (
        "name",
        "description",
        "sort_order",
        "archived",
        "archived_at",
    )

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self):
        return self.name

    def _get_log_box_id(self):
        return self.pk

    @property
    def progress(self):
        qs = self.images.all()
        total = qs.count()
        todo_place = qs.filter(place_todo=True).count()
        todo_date = qs.filter(date_todo=True).count()
        todo_flip = qs.filter(needs_flip=True).count()
        todo_edit = qs.exclude(edit_todo="").count()
        tagged = qs.exclude(
            place__isnull=True, date_earliest__isnull=True, date_latest__isnull=True
        ).count()
        done = qs.filter(
            place_todo=False,
            date_todo=False,
            needs_flip=False,
            edit_todo="",
            place__isnull=False,
            date_earliest__isnull=False,
        ).count()
        return {
            "total": total,
            "tagged": tagged,
            "todo_place": todo_place,
            "todo_date": todo_date,
            "todo_flip": todo_flip,
            "todo_edit": todo_edit,
            "done": done,
        }

    @property
    def can_archive(self):
        if self.archived:
            return False
        return not any(image.has_open_todos() for image in self.images.all())

    def archive(self, user=None):
        from diathek.core.models.auditlog import AuditLog
        from diathek.core.models.image import Image

        with transaction.atomic():
            locked = Box.objects.select_for_update().get(pk=self.pk)
            if not locked.can_archive:
                raise ValueError("Box kann nicht archiviert werden.")

            for image in locked.images.all():
                image.delete_originals_and_details()

            locked.archived = True
            locked.archived_at = timezone.now()
            locked.save(user=user)

            AuditLog.objects.filter(
                box=locked, content_type=ContentType.objects.get_for_model(Image)
            ).delete()

            self.refresh_from_db()
