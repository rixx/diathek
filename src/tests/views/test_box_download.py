import io
import zipfile

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_client(client):
    user = UserFactory(name="Karin")
    client.force_login(user)
    client.user = user
    return client


@pytest.fixture
def box(db):
    return BoxFactory(name="Dachboden")


def _image_with_original(box, sequence, filename, content):
    image = ImageFactory(box=box, sequence_in_box=sequence, filename=filename)
    image.image.save(filename, ContentFile(content), save=False)
    image.save(skip_log=True, bump_version=False)
    return image


def _read_zip(response):
    return zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))


@pytest.mark.django_db
def test_box_download_requires_login(client, box):
    response = client.get(reverse("box_download", args=[box.uuid]))

    assert response.status_code == 302


@pytest.mark.django_db
def test_box_download_returns_404_for_missing_box(auth_client):
    response = auth_client.get(
        reverse("box_download", args=["00000000-0000-0000-0000-000000000000"])
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_box_download_returns_404_for_archived_box(auth_client, box):
    _image_with_original(box, 1, "a.jpg", b"jpeg-bytes")
    box.archived = True
    box.save(user=auth_client.user)

    response = auth_client.get(reverse("box_download", args=[box.uuid]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_box_download_returns_404_without_original_files(auth_client, box):
    # An image row exists, but its original file is gone — nothing to zip.
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("box_download", args=[box.uuid]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_box_download_streams_zip_of_originals_in_sequence_order(auth_client, box):
    _image_with_original(box, 2, "b.jpg", b"second-bytes")
    _image_with_original(box, 1, "a.jpg", b"first-bytes")

    response = auth_client.get(reverse("box_download", args=[box.uuid]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert response["Content-Disposition"] == 'attachment; filename="Dachboden.zip"'
    archive = _read_zip(response)
    assert archive.namelist() == ["a.jpg", "b.jpg"]
    assert archive.read("a.jpg") == b"first-bytes"
    assert archive.read("b.jpg") == b"second-bytes"
    assert archive.testzip() is None


@pytest.mark.django_db
def test_box_download_skips_images_without_original(auth_client, box):
    _image_with_original(box, 1, "a.jpg", b"first-bytes")
    ImageFactory(box=box, sequence_in_box=2, filename="fileless.jpg")

    response = auth_client.get(reverse("box_download", args=[box.uuid]))

    archive = _read_zip(response)
    assert archive.namelist() == ["a.jpg"]


@pytest.mark.django_db
def test_box_download_escapes_box_name_in_filename(auth_client):
    box = BoxFactory(name="Schöne Dias")
    _image_with_original(box, 1, "a.jpg", b"bytes")

    response = auth_client.get(reverse("box_download", args=[box.uuid]))

    assert (
        response["Content-Disposition"]
        == "attachment; filename*=utf-8''Sch%C3%B6ne%20Dias.zip"
    )


@pytest.mark.django_db
def test_grid_shows_download_link_for_box_with_images(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    content = response.content.decode()
    assert reverse("box_download", args=[box.uuid]) in content
    assert "Herunterladen" in content


@pytest.mark.django_db
def test_grid_hides_download_link_for_empty_box(auth_client, box):
    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    assert "Herunterladen" not in response.content.decode()


@pytest.mark.django_db
def test_grid_hides_download_link_for_archived_box(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    box.archived = True
    box.save(user=auth_client.user)

    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    assert "Herunterladen" not in response.content.decode()
