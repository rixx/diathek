import uuid
from datetime import timedelta

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from diathek.core.models.base import BaseModel
from diathek.core.models.box import Box


class DatePrecision(models.TextChoices):
    EXACT = "exact"
    MONTH = "month"
    SEASON = "season"
    YEAR = "year"
    RANGE = "range"
    DECADE = "decade"
    UNKNOWN = "unknown"


def _box_segment(instance):
    return str(instance.box.uuid) if instance.box_id else "unsorted"


def image_original_upload_to(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"boxes/{_box_segment(instance)}/originals/{instance.uuid}.{ext}"


def image_thumb_small_upload_to(instance, filename):
    return f"boxes/{_box_segment(instance)}/thumbs/{instance.uuid}.webp"


def image_thumb_detail_upload_to(instance, filename):
    return f"boxes/{_box_segment(instance)}/details/{instance.uuid}.webp"


class Image(BaseModel):
    uuid = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, db_index=True
    )
    box = models.ForeignKey(
        Box,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_index=True,
        related_name="images",
    )
    sequence_in_box = models.IntegerField(null=True, blank=True)
    filename = models.CharField(max_length=255)
    image = models.FileField(
        upload_to=image_original_upload_to, null=True, blank=True, max_length=500
    )
    thumb_small = models.FileField(
        upload_to=image_thumb_small_upload_to, null=True, blank=True, max_length=500
    )
    thumb_detail = models.FileField(
        upload_to=image_thumb_detail_upload_to, null=True, blank=True, max_length=500
    )
    content_hash = models.CharField(max_length=64, db_index=True, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    width = models.IntegerField(default=0)
    height = models.IntegerField(default=0)
    version = models.PositiveIntegerField(default=0)

    place = models.ForeignKey(
        "core.Place",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="images",
    )
    place_todo = models.BooleanField(default=False)
    date_earliest = models.DateField(null=True, blank=True)
    date_latest = models.DateField(null=True, blank=True)
    date_precision = models.CharField(
        max_length=16, choices=DatePrecision.choices, blank=True
    )
    date_display = models.CharField(max_length=100, blank=True)
    date_todo = models.BooleanField(default=False)
    needs_flip = models.BooleanField(default=False)
    edit_todo = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)

    log_action_prefix = "image"
    log_tracked_fields = (
        "filename",
        "box",
        "sequence_in_box",
        "place",
        "place_todo",
        "date_earliest",
        "date_latest",
        "date_precision",
        "date_display",
        "date_todo",
        "needs_flip",
        "edit_todo",
        "description",
    )

    class Meta:
        ordering = ("box", "sequence_in_box")
        constraints = [
            models.UniqueConstraint(
                fields=["box", "sequence_in_box"], name="image_unique_box_sequence"
            ),
            models.UniqueConstraint(
                fields=["box", "filename"], name="image_unique_box_filename"
            ),
        ]

    def __str__(self):
        return self.filename

    def _get_log_box_id(self):
        return self.box_id

    def has_open_todos(self):
        return bool(
            self.place_todo or self.date_todo or self.needs_flip or self.edit_todo
        )

    def date_representative(self):
        if self.date_earliest is None or self.date_latest is None:
            return None
        span = (self.date_latest - self.date_earliest).days
        return self.date_earliest + timedelta(days=span // 2)

    def save(self, *args, bump_version=True, **kwargs):
        if bump_version:
            self.version += 1
        super().save(*args, **kwargs)

    def delete_originals_and_details(self):
        changed = False
        if self.image:
            self.image.delete(save=False)
            self.image = None
            changed = True
        if self.thumb_detail:
            self.thumb_detail.delete(save=False)
            self.thumb_detail = None
            changed = True
        if changed:
            self.save(skip_log=True, bump_version=False)

    @classmethod
    def recent_date_displays(cls, limit=10):
        seen = set()
        out = []
        pool = (
            cls.objects.exclude(date_display="")
            .order_by("-updated_at")
            .values_list("date_display", flat=True)[: limit * 5]
        )
        for value in pool:
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
            if len(out) == limit:
                break
        return out

    @classmethod
    def next_sequence_for(cls, box):
        if box is None:
            return None
        last = cls.objects.filter(box=box).aggregate(
            value=models.Max("sequence_in_box")
        )["value"]
        return (last or 0) + 1

    def assign_to_box(self, new_box, *, sequence, user=None):
        if self.box_id == (new_box.pk if new_box else None):
            if self.sequence_in_box == sequence:
                return
            self.sequence_in_box = sequence
            self.save(user=user)
            return

        field_info = (
            ("image", image_original_upload_to),
            ("thumb_small", image_thumb_small_upload_to),
            ("thumb_detail", image_thumb_detail_upload_to),
        )

        contents = {}
        for attr, _ in field_info:
            field_file = getattr(self, attr)
            if not field_file:
                continue
            with default_storage.open(field_file.name, "rb") as handle:
                contents[attr] = (field_file.name, handle.read())

        self.box = new_box
        self.sequence_in_box = sequence

        old_names = []
        for attr, upload_to_fn in field_info:
            if attr not in contents:
                continue
            old_name, data = contents[attr]
            new_path = upload_to_fn(self, old_name)
            saved_name = default_storage.save(new_path, ContentFile(data))
            getattr(self, attr).name = saved_name
            old_names.append(old_name)

        with transaction.atomic():
            self.save(user=user)

            def _cleanup(names=tuple(old_names)):
                for name in names:
                    default_storage.delete(name)

            transaction.on_commit(_cleanup)


@receiver(post_delete, sender=Image)
def image_delete_files(sender, instance, **kwargs):
    for attr in ("image", "thumb_small", "thumb_detail"):
        field_file = getattr(instance, attr)
        if field_file:
            field_file.delete(save=False)
