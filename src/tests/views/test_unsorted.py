import json

import pytest
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from diathek.core.models import Image
from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_client(client):
    user = UserFactory()
    client.force_login(user)
    client.user = user
    return client


@pytest.mark.django_db
def test_unsorted_view_requires_login(client):
    response = client.get(reverse("unsorted"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_unsorted_view_lists_unassigned_images_and_active_boxes(auth_client):
    unassigned = ImageFactory(box=None, sequence_in_box=None, filename="a.jpg")
    ImageFactory(filename="b.jpg")  # in a box, should be hidden
    BoxFactory(name="Dachboden")
    BoxFactory(name="Keller", archived=True)

    response = auth_client.get(reverse("unsorted"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert str(unassigned.uuid) in content
    assert "Dachboden" in content
    assert "Keller" not in content


@pytest.mark.django_db
def test_unsorted_view_shows_empty_message_when_nothing_to_sort(auth_client):
    response = auth_client.get(reverse("unsorted"))

    assert b"Keine unsortierten" in response.content


@pytest.mark.django_db
def test_assign_requires_post(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("unsorted_assign"))

    assert response.status_code == 405


@pytest.mark.django_db
def test_assign_rejects_missing_params(auth_client):
    response = auth_client.post(reverse("unsorted_assign"), {})

    assert response.status_code == 400
    assert "angegeben" in response.json()["error"]


@pytest.mark.django_db
def test_assign_rejects_archived_box(auth_client):
    box = BoxFactory(archived=True)
    image = ImageFactory(box=None, sequence_in_box=None)

    response = auth_client.post(
        reverse("unsorted_assign"),
        {"box_uuid": str(box.uuid), "image_uuids": [str(image.uuid)]},
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_assign_rejects_unknown_images(auth_client):
    box = BoxFactory()

    response = auth_client.post(
        reverse("unsorted_assign"),
        {
            "box_uuid": str(box.uuid),
            "image_uuids": ["00000000-0000-0000-0000-000000000000"],
        },
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_assign_rejects_duplicate_filenames_within_batch(auth_client):
    box = BoxFactory()
    a = ImageFactory(box=None, sequence_in_box=None, filename="scan.jpg")
    b = ImageFactory(box=None, sequence_in_box=None, filename="scan.jpg")

    response = auth_client.post(
        reverse("unsorted_assign"),
        {"box_uuid": str(box.uuid), "image_uuids": [str(a.uuid), str(b.uuid)]},
    )

    assert response.status_code == 400
    assert "Doppelte" in response.json()["error"]


@pytest.mark.django_db
def test_assign_rejects_filename_collision_with_existing_box_image(auth_client):
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, filename="scan.jpg")
    unsorted_image = ImageFactory(box=None, sequence_in_box=None, filename="scan.jpg")

    response = auth_client.post(
        reverse("unsorted_assign"),
        {"box_uuid": str(box.uuid), "image_uuids": [str(unsorted_image.uuid)]},
    )

    assert response.status_code == 400
    assert "existiert bereits" in response.json()["error"]
    unsorted_image.refresh_from_db()
    assert unsorted_image.box is None


class AssignSuccessTests(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.client.force_login(self.user)

    def _image_with_thumb(self, *, filename):
        image = ImageFactory(box=None, sequence_in_box=None, filename=filename)
        image.thumb_small.save(f"{image.uuid}.webp", ContentFile(b"thumb"), save=False)
        image.save()
        return image

    def test_assign_moves_multiple_images_and_assigns_sequences(self):
        box = BoxFactory()
        ImageFactory(box=box, sequence_in_box=4, filename="existing.jpg")
        first = self._image_with_thumb(filename="b.jpg")
        second = self._image_with_thumb(filename="a.jpg")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("unsorted_assign"),
                {
                    "box_uuid": str(box.uuid),
                    "image_uuids": [str(first.uuid), str(second.uuid)],
                },
            )

        assert response.status_code == 200
        payload = json.loads(response.content)
        assert payload["box"] == box.name
        first.refresh_from_db()
        second.refresh_from_db()
        assert {first.sequence_in_box, second.sequence_in_box} == {5, 6}
        ordered = list(
            Image.objects.filter(box=box)
            .order_by("sequence_in_box")
            .values_list("filename", flat=True)
        )
        assert ordered == ["existing.jpg", "a.jpg", "b.jpg"]
