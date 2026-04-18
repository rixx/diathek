import datetime
import uuid

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError

from diathek.core.models import Image
from diathek.core.models.image import (
    image_original_upload_to,
    image_thumb_detail_upload_to,
    image_thumb_small_upload_to,
)
from tests.factories import BoxFactory, ImageFactory

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
def test_image_has_open_todos_true_for_each_todo_flag():
    assert ImageFactory.build(place_todo=True).has_open_todos()
    assert ImageFactory.build(date_todo=True).has_open_todos()
    assert ImageFactory.build(needs_flip=True).has_open_todos()
    assert ImageFactory.build(edit_todo="fix").has_open_todos()


@pytest.mark.django_db
def test_image_has_open_todos_false_when_clean():
    assert not ImageFactory.build().has_open_todos()


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
