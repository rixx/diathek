import datetime
import hashlib
import json
import uuid
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError

from diathek.core.models import Image
from diathek.core.models.image import (
    image_original_upload_to,
    image_thumb_detail_upload_to,
    image_thumb_small_upload_to,
)
from tests.factories import BoxFactory, ImageFactory, PlaceFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_image_save_bumps_version_each_time():
    image = ImageFactory()
    assert image.version == 1

    image.description = "hi"
    image.save()
    assert image.version == 2

    image.save(bump_version=False)
    assert image.version == 2


@pytest.mark.django_db
def test_image_factory_immich_uploaded_trait_marks_current():
    image = ImageFactory(immich_uploaded=True)

    assert image.immich_asset_id == f"asset-{image.uuid}"
    assert image.immich_is_current
    image.refresh_from_db()
    assert image.immich_is_current


@pytest.mark.django_db
def test_image_factory_immich_uploaded_trait_build_does_not_save():
    image = ImageFactory.build(immich_uploaded=True)

    assert image.immich_asset_id == f"asset-{image.uuid}"
    assert image.immich_signature == image.compute_immich_signature()
    assert image.pk is None


@pytest.mark.django_db
def test_image_has_open_todos_true_for_each_todo_flag():
    assert ImageFactory.build(place_todo=True).has_open_todos()
    assert ImageFactory.build(date_todo=True).has_open_todos()
    assert ImageFactory.build(edit_todo="fix").has_open_todos()


@pytest.mark.django_db
def test_image_has_open_todos_false_when_clean():
    assert not ImageFactory.build().has_open_todos()


@pytest.mark.django_db
def test_image_needs_flip_alone_is_not_an_open_todo():
    # needs_flip is a permanent "this image is mirrored" record baked into the
    # upload as an EXIF orientation flag; it no longer blocks archival.
    assert not ImageFactory.build(needs_flip=True).has_open_todos()


@pytest.mark.django_db
def test_image_has_coords_requires_both_values():
    assert ImageFactory.build(
        latitude=Decimal("52.5"), longitude=Decimal("13.4")
    ).has_coords
    assert not ImageFactory.build(latitude=Decimal("52.5"), longitude=None).has_coords
    assert not ImageFactory.build(latitude=None, longitude=None).has_coords


@pytest.mark.django_db
def test_image_has_location_via_place_or_coords():
    place = PlaceFactory()
    assert ImageFactory.build(place=place).has_location
    assert ImageFactory.build(
        place=None, latitude=Decimal("52.5"), longitude=Decimal("13.4")
    ).has_location
    assert not ImageFactory.build(place=None).has_location


@pytest.mark.django_db
def test_compute_immich_signature_includes_coords_when_set():
    image = ImageFactory.build()
    before = image.compute_immich_signature()

    image.latitude = Decimal("52.520007")
    image.longitude = Decimal("13.404954")

    assert image.compute_immich_signature() != before


@pytest.mark.django_db
def test_compute_immich_signature_unchanged_without_coords():
    """Adding the feature must not silently invalidate coordless uploads."""
    image = ImageFactory.build(place=None, date_earliest=None, date_latest=None)

    expected = hashlib.sha256(
        json.dumps(
            {
                "content_hash": image.content_hash,
                "place": None,
                "date": None,
                "capture_datetime": None,
                "date_display": image.date_display,
                "description": image.description,
                "needs_flip": image.needs_flip,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    assert image.compute_immich_signature() == expected


@pytest.mark.django_db
def test_image_date_representative_returns_midpoint():
    image = ImageFactory.build(
        date_earliest=datetime.date(1987, 6, 1), date_latest=datetime.date(1987, 8, 31)
    )

    assert image.date_representative() == datetime.date(1987, 7, 16)


@pytest.mark.django_db
def test_image_date_representative_returns_none_when_any_bound_missing():
    assert (
        ImageFactory.build(date_earliest=None, date_latest=None).date_representative()
        is None
    )
    assert (
        ImageFactory.build(
            date_earliest=datetime.date(1987, 1, 1), date_latest=None
        ).date_representative()
        is None
    )


@pytest.mark.django_db
def test_effective_capture_datetime_returned_when_day_matches():
    image = ImageFactory.build(
        date_earliest=datetime.date(1987, 6, 15),
        date_latest=datetime.date(1987, 6, 15),
        immich_capture_datetime="1987-06-15T14:30:00+02:00",
    )

    capture = image.effective_capture_datetime()

    assert capture == datetime.datetime(
        1987, 6, 15, 14, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=2))
    )


@pytest.mark.django_db
def test_effective_capture_datetime_rebases_time_onto_current_date():
    # Editing the rough date keeps the pulled time-of-day, rebased onto the new
    # (representative) day — so the precise time is not silently dropped.
    image = ImageFactory.build(
        date_earliest=datetime.date(1990, 1, 1),
        date_latest=datetime.date(1990, 1, 1),
        immich_capture_datetime="1987-06-15T14:30:00+02:00",
    )

    assert image.effective_capture_datetime() == datetime.datetime(
        1990, 1, 1, 14, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=2))
    )


@pytest.mark.django_db
def test_effective_capture_datetime_uses_representative_midpoint():
    image = ImageFactory.build(
        date_earliest=datetime.date(1987, 6, 1),
        date_latest=datetime.date(1987, 8, 31),
        immich_capture_datetime="1987-06-15T14:30:00+02:00",
    )

    assert image.effective_capture_datetime() == datetime.datetime(
        1987, 7, 16, 14, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=2))
    )


@pytest.mark.django_db
def test_effective_capture_datetime_none_when_unset_or_no_date():
    no_value = ImageFactory.build(
        date_earliest=datetime.date(1987, 6, 15),
        date_latest=datetime.date(1987, 6, 15),
        immich_capture_datetime="",
    )
    no_date = ImageFactory.build(
        date_earliest=None,
        date_latest=None,
        immich_capture_datetime="1987-06-15T14:30:00+02:00",
    )

    assert no_value.effective_capture_datetime() is None
    assert no_date.effective_capture_datetime() is None


@pytest.mark.django_db
def test_effective_capture_datetime_none_when_malformed():
    image = ImageFactory.build(
        date_earliest=datetime.date(1987, 6, 15),
        date_latest=datetime.date(1987, 6, 15),
        immich_capture_datetime="not-a-datetime",
    )

    assert image.effective_capture_datetime() is None


@pytest.mark.django_db
def test_immich_capture_time_and_offset_label_for_input():
    image = ImageFactory.build(
        date_earliest=datetime.date(1987, 6, 15),
        date_latest=datetime.date(1987, 6, 15),
        immich_capture_datetime="1987-06-15T14:30:00+02:00",
    )

    assert image.immich_capture_time() == "14:30:00"
    assert image.immich_capture_offset_label() == "UTC+02:00"


@pytest.mark.django_db
def test_immich_capture_offset_label_blank_when_naive():
    image = ImageFactory.build(
        date_earliest=datetime.date(1987, 6, 15),
        date_latest=datetime.date(1987, 6, 15),
        immich_capture_datetime="1987-06-15T14:30:00",
    )

    assert image.immich_capture_time() == "14:30:00"
    assert image.immich_capture_offset_label() == ""


@pytest.mark.django_db
def test_immich_capture_time_and_label_blank_without_capture():
    image = ImageFactory.build(
        date_earliest=datetime.date(1987, 6, 15),
        date_latest=datetime.date(1987, 6, 15),
        immich_capture_datetime="",
    )

    assert image.immich_capture_time() == ""
    assert image.immich_capture_offset_label() == ""


@pytest.mark.django_db
def test_capture_datetime_with_time_preserves_offset_and_uses_date():
    image = ImageFactory.build(
        date_earliest=datetime.date(1987, 6, 15),
        date_latest=datetime.date(1987, 6, 15),
        immich_capture_datetime="1987-06-15T14:30:00+02:00",
    )

    result = image.capture_datetime_with_time(datetime.time(14, 40, 0))

    assert result == "1987-06-15T14:40:00+02:00"


@pytest.mark.django_db
def test_capture_datetime_with_time_blank_without_date():
    image = ImageFactory.build(
        date_earliest=None,
        date_latest=None,
        immich_capture_datetime="1987-06-15T14:30:00+02:00",
    )

    assert image.capture_datetime_with_time(datetime.time(14, 40, 0)) == ""


@pytest.mark.django_db
def test_capture_datetime_with_time_drops_offset_when_stored_value_malformed():
    image = ImageFactory.build(
        date_earliest=datetime.date(1987, 6, 15),
        date_latest=datetime.date(1987, 6, 15),
        immich_capture_datetime="not-a-datetime",
    )

    result = image.capture_datetime_with_time(datetime.time(14, 40, 0))

    assert result == "1987-06-15T14:40:00"


@pytest.mark.django_db
def test_compute_immich_signature_changes_with_capture_datetime():
    kwargs = {
        "date_earliest": datetime.date(1987, 6, 15),
        "date_latest": datetime.date(1987, 6, 15),
    }
    without = ImageFactory.build(immich_capture_datetime="", **kwargs)
    with_time = ImageFactory.build(
        immich_capture_datetime="1987-06-15T14:30:00+02:00", **kwargs
    )

    assert with_time.compute_immich_signature() != without.compute_immich_signature()


@pytest.mark.django_db
def test_compute_immich_signature_is_deterministic():
    place = PlaceFactory()
    kwargs = {
        "content_hash": "abc123",
        "place": place,
        "date_earliest": datetime.date(1987, 6, 1),
        "date_latest": datetime.date(1987, 8, 31),
        "date_display": "Sommer 1987",
        "description": "Oma im Garten",
        "needs_flip": True,
    }
    first = ImageFactory.build(**kwargs)
    second = ImageFactory.build(**kwargs)

    assert first.compute_immich_signature() == second.compute_immich_signature()


@pytest.mark.django_db
def test_compute_immich_signature_uses_none_when_unset():
    image = ImageFactory.build(place=None, date_earliest=None, date_latest=None)

    expected = hashlib.sha256(
        json.dumps(
            {
                "content_hash": image.content_hash,
                "place": None,
                "date": None,
                "capture_datetime": None,
                "date_display": image.date_display,
                "description": image.description,
                "needs_flip": image.needs_flip,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    assert image.compute_immich_signature() == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"), (("description", "geändert"), ("needs_flip", True))
)
def test_compute_immich_signature_changes_when_relevant_field_changes(field, value):
    image = ImageFactory.build(description="original", needs_flip=False)
    before = image.compute_immich_signature()

    setattr(image, field, value)

    assert image.compute_immich_signature() != before


@pytest.mark.django_db
def test_immich_is_current_false_without_asset_id():
    image = ImageFactory()
    image.immich_signature = image.compute_immich_signature()

    assert image.immich_is_current is False


@pytest.mark.django_db
def test_immich_is_current_false_when_signature_differs():
    image = ImageFactory(immich_asset_id="asset-1")
    image.immich_signature = "stale"

    assert image.immich_is_current is False


@pytest.mark.django_db
def test_immich_is_current_true_when_asset_and_signature_match():
    image = ImageFactory(immich_asset_id="asset-1")
    image.immich_signature = image.compute_immich_signature()

    assert image.immich_is_current is True


@pytest.mark.django_db
def test_image_unique_filename_per_box():
    box = BoxFactory()
    ImageFactory(box=box, filename="scan_001.jpg", sequence_in_box=1)

    with pytest.raises(IntegrityError):
        ImageFactory(box=box, filename="scan_001.jpg", sequence_in_box=2)


@pytest.mark.django_db
def test_image_unique_sequence_per_box():
    box = BoxFactory()
    ImageFactory(box=box, filename="a.jpg", sequence_in_box=1)

    with pytest.raises(IntegrityError):
        ImageFactory(box=box, filename="b.jpg", sequence_in_box=1)


@pytest.mark.django_db
def test_image_same_filename_allowed_in_different_boxes():
    box_a = BoxFactory()
    box_b = BoxFactory()
    ImageFactory(box=box_a, filename="scan.jpg", sequence_in_box=1)
    ImageFactory(box=box_b, filename="scan.jpg", sequence_in_box=1)

    assert Image.objects.count() == 2


@pytest.mark.django_db
def test_image_delete_originals_and_details_removes_files_keeps_thumb():
    image = ImageFactory()
    image.image.save("scan.jpg", ContentFile(b"original"), save=False)
    image.thumb_detail.save("detail.webp", ContentFile(b"detail"), save=False)
    image.thumb_small.save("thumb.webp", ContentFile(b"thumb"), save=False)
    image.save()

    image.delete_originals_and_details()

    image.refresh_from_db()
    assert not image.image
    assert not image.thumb_detail
    assert image.thumb_small  # kept for archive


@pytest.mark.django_db
def test_image_delete_originals_and_details_noop_when_no_files():
    image = ImageFactory()
    version_before = image.version

    image.delete_originals_and_details()

    image.refresh_from_db()
    assert image.version == version_before


@pytest.mark.django_db
def test_image_delete_removes_all_file_variants_from_storage():
    from pathlib import Path

    image = ImageFactory()
    image.image.save("scan.jpg", ContentFile(b"original"), save=False)
    image.thumb_detail.save("detail.webp", ContentFile(b"detail"), save=False)
    image.thumb_small.save("thumb.webp", ContentFile(b"thumb"), save=False)
    image.save()
    paths = [
        Path(image.image.path),
        Path(image.thumb_detail.path),
        Path(image.thumb_small.path),
    ]
    assert all(p.exists() for p in paths)

    image.delete()

    assert not any(p.exists() for p in paths)


@pytest.mark.django_db
def test_image_queryset_delete_removes_files_from_storage():
    from pathlib import Path

    image = ImageFactory()
    image.image.save("scan.jpg", ContentFile(b"original"), save=False)
    image.thumb_small.save("thumb.webp", ContentFile(b"thumb"), save=False)
    image.save()
    paths = [Path(image.image.path), Path(image.thumb_small.path)]

    Image.objects.filter(pk=image.pk).delete()

    assert not any(p.exists() for p in paths)


@pytest.mark.django_db
def test_image_cascade_delete_from_box_removes_files_from_storage():
    from pathlib import Path

    box = BoxFactory()
    image = ImageFactory(box=box)
    image.image.save("scan.jpg", ContentFile(b"original"), save=False)
    image.save()
    path = Path(image.image.path)
    assert path.exists()

    box.delete()

    assert not path.exists()


@pytest.mark.django_db
def test_image_delete_without_files_does_not_raise():
    image = ImageFactory()

    image.delete()

    assert not Image.objects.filter(pk=image.pk).exists()


def test_upload_paths_use_box_uuid_and_image_uuid():
    box_uuid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    image_uuid = uuid.UUID("00000000-0000-0000-0000-0000000000aa")

    class Stub:
        box_id = 1
        uuid = image_uuid

        class box:  # noqa: N801
            uuid = box_uuid

    assert (
        image_original_upload_to(Stub, "raw_001.JPG")
        == f"boxes/{box_uuid}/originals/{image_uuid}.jpg"
    )
    assert (
        image_thumb_small_upload_to(Stub, "irrelevant")
        == f"boxes/{box_uuid}/thumbs/{image_uuid}.webp"
    )
    assert (
        image_thumb_detail_upload_to(Stub, "irrelevant")
        == f"boxes/{box_uuid}/details/{image_uuid}.webp"
    )


@pytest.mark.django_db
def test_recent_date_displays_returns_distinct_values_ordered_by_updated_at():
    from django.utils import timezone

    now = timezone.now()
    older = ImageFactory(date_display="1987")
    newer = ImageFactory(date_display="Sommer 1987")
    duplicate = ImageFactory(date_display="1987")
    Image.objects.filter(pk=older.pk).update(
        updated_at=now - datetime.timedelta(days=2)
    )
    Image.objects.filter(pk=newer.pk).update(updated_at=now)
    Image.objects.filter(pk=duplicate.pk).update(
        updated_at=now - datetime.timedelta(days=1)
    )

    assert Image.recent_date_displays() == ["Sommer 1987", "1987"]


@pytest.mark.django_db
def test_recent_date_displays_skips_empty_strings():
    ImageFactory(date_display="")
    ImageFactory(date_display="1987")

    assert Image.recent_date_displays() == ["1987"]


@pytest.mark.django_db
def test_recent_date_displays_respects_limit():
    for year in range(1980, 1990):
        ImageFactory(date_display=str(year))

    assert len(Image.recent_date_displays(limit=3)) == 3


def test_upload_paths_fall_back_to_unsorted_when_box_missing():
    image_uuid = uuid.UUID("00000000-0000-0000-0000-0000000000aa")

    class Stub:
        box_id = None
        uuid = image_uuid
        box = None

    assert (
        image_original_upload_to(Stub, "noext")
        == f"boxes/unsorted/originals/{image_uuid}.bin"
    )
