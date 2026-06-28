import contextlib
import uuid
from datetime import datetime, timedelta

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
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
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

    # Exact local capture timestamp (ISO 8601, with offset) pulled from an Immich
    # photo. Kept alongside the day-precision date fields so the export can bake
    # back the original time and timezone; ignored once the date is edited away
    # from it. See ``immich_export.build_args_for_image``.
    immich_capture_datetime = models.CharField(max_length=40, blank=True)
    immich_asset_id = models.CharField(max_length=64, blank=True)
    immich_checksum = models.CharField(max_length=64, blank=True)
    immich_uploaded_at = models.DateTimeField(null=True, blank=True)
    immich_owner = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="immich_uploads",
    )
    immich_signature = models.CharField(max_length=64, blank=True)

    log_action_prefix = "image"
    log_tracked_fields = (
        "filename",
        "box",
        "sequence_in_box",
        "place",
        "latitude",
        "longitude",
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
        return bool(self.place_todo or self.date_todo or self.edit_todo)

    @property
    def has_coords(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def has_location(self):
        """True when a location is known via a named place or direct coordinates."""
        return self.place_id is not None or self.has_coords

    def date_representative(self):
        if self.date_earliest is None or self.date_latest is None:
            return None
        span = (self.date_latest - self.date_earliest).days
        return self.date_earliest + timedelta(days=span // 2)

    def effective_capture_datetime(self):
        """The exact capture timestamp baked into the export, or ``None``.

        Combines the representative date (the single source of truth for the day)
        with the time-of-day and UTC offset stored in
        :attr:`immich_capture_datetime`. The stored time starts from an Immich
        pull and can then be nudged by the user; it is rebased onto whatever date
        the date field currently resolves to, so editing the rough date keeps the
        time. ``None`` when nothing was pulled, the value is unparseable, or no
        date is set (no day to attach the time to) — the export falls back to noon.
        """
        if not self.immich_capture_datetime:
            return None
        rep = self.date_representative()
        if rep is None:
            return None
        try:
            parsed = datetime.fromisoformat(self.immich_capture_datetime)
        except ValueError:
            return None
        return datetime.combine(rep, parsed.timetz())

    def immich_capture_time(self):
        """``HH:MM:SS`` for the editable capture-time input, or ``""`` if none."""
        capture = self.effective_capture_datetime()
        return capture.strftime("%H:%M:%S") if capture else ""

    def immich_capture_offset_label(self):
        """The capture time's UTC offset (e.g. ``UTC+02:00``), shown read-only."""
        capture = self.effective_capture_datetime()
        if capture is None:
            return ""
        offset = capture.strftime("%z")
        return f"UTC{offset[:3]}:{offset[3:]}" if offset else ""

    def capture_datetime_with_time(self, time_obj):
        """Return the ISO value to store for a user-set capture time-of-day.

        Combines the representative date with ``time_obj``, preserving the UTC
        offset of the existing pulled value so a tweak ("ten minutes later")
        keeps the original timezone. Returns ``""`` when there is no date to
        attach the time to.
        """
        rep = self.date_representative()
        if rep is None:
            return ""
        tzinfo = None
        # No prior pull, or a stored value we can't read → no offset to preserve.
        with contextlib.suppress(ValueError):
            tzinfo = datetime.fromisoformat(self.immich_capture_datetime).tzinfo
        return datetime.combine(rep, time_obj, tzinfo=tzinfo).isoformat()

    def compute_immich_signature(self):
        import hashlib
        import json

        rep = self.date_representative()
        capture = self.effective_capture_datetime()
        payload = {
            "content_hash": self.content_hash,
            "place": self.place.name if self.place_id else None,
            "date": rep.isoformat() if rep else None,
            "capture_datetime": capture.isoformat() if capture else None,
            "date_display": self.date_display,
            "description": self.description,
            "needs_flip": self.needs_flip,
        }
        if self.has_coords:
            payload["latitude"] = str(self.latitude)
            payload["longitude"] = str(self.longitude)
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @property
    def immich_is_current(self):
        return bool(self.immich_asset_id) and (
            self.immich_signature == self.compute_immich_signature()
        )

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
