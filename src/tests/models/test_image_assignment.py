import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase

from diathek.core.models import Image
from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_next_sequence_for_none_returns_none():
    assert Image.next_sequence_for(None) is None


@pytest.mark.django_db
def test_next_sequence_for_empty_box_starts_at_one():
    box = BoxFactory()

    assert Image.next_sequence_for(box) == 1


@pytest.mark.django_db
def test_next_sequence_for_appends_after_max():
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1)
    ImageFactory(box=box, sequence_in_box=7)

    assert Image.next_sequence_for(box) == 8


class AssignToBoxTests(TestCase):
    def _stash_files(self, image, *, with_detail=True):
        image.image.save("scan.jpg", ContentFile(b"orig"), save=False)
        image.thumb_small.save(f"{image.uuid}.webp", ContentFile(b"thumb"), save=False)
        if with_detail:
            image.thumb_detail.save(
                f"{image.uuid}.webp", ContentFile(b"detail"), save=False
            )
        image.save()

    def test_assign_to_new_box_moves_files_and_updates_sequence(self):
        user = UserFactory()
        source_box = BoxFactory()
        target_box = BoxFactory()
        image = ImageFactory(box=source_box, sequence_in_box=1, filename="scan.jpg")
        self._stash_files(image)
        old_original = image.image.name
        old_thumb = image.thumb_small.name
        old_detail = image.thumb_detail.name

        with self.captureOnCommitCallbacks(execute=True):
            image.assign_to_box(target_box, sequence=5, user=user)

        image.refresh_from_db()
        assert image.box_id == target_box.pk
        assert image.sequence_in_box == 5
        assert str(target_box.uuid) in image.image.name
        assert str(target_box.uuid) in image.thumb_small.name
        assert str(target_box.uuid) in image.thumb_detail.name
        assert default_storage.exists(image.image.name)
        assert not default_storage.exists(old_original)
        assert not default_storage.exists(old_thumb)
        assert not default_storage.exists(old_detail)

    def test_assign_skips_missing_detail_thumb(self):
        target_box = BoxFactory()
        image = ImageFactory(filename="scan.jpg")
        self._stash_files(image, with_detail=False)

        with self.captureOnCommitCallbacks(execute=True):
            image.assign_to_box(target_box, sequence=1)

        image.refresh_from_db()
        assert image.thumb_detail.name in ("", None)

    def test_assign_same_box_same_sequence_is_noop(self):
        box = BoxFactory()
        image = ImageFactory(box=box, sequence_in_box=3)
        version_before = image.version

        image.assign_to_box(box, sequence=3)

        image.refresh_from_db()
        assert image.version == version_before

    def test_assign_same_box_new_sequence_updates_only_sequence(self):
        box = BoxFactory()
        image = ImageFactory(box=box, sequence_in_box=3)

        image.assign_to_box(box, sequence=9)

        image.refresh_from_db()
        assert image.sequence_in_box == 9

    def test_assign_unsorted_to_box_and_back_round_trips_files(self):
        box = BoxFactory()
        image = ImageFactory(box=None, sequence_in_box=None, filename="scan.jpg")
        self._stash_files(image, with_detail=False)

        with self.captureOnCommitCallbacks(execute=True):
            image.assign_to_box(box, sequence=1)

        image.refresh_from_db()
        assert image.box_id == box.pk
        assert "unsorted" not in image.image.name
