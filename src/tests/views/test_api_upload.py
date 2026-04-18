import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from diathek.core.models import Image
from tests.factories import ImageFactory, UserFactory
from tests.helpers import make_jpeg_bytes, make_uploaded_jpeg

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_client(client):
    user = UserFactory(is_staff=True)
    client.force_login(user)
    client.user = user
    return client


@pytest.fixture
def non_staff_client(client):
    user = UserFactory()
    client.force_login(user)
    client.user = user
    return client


@pytest.mark.django_db
def test_api_upload_requires_login(client):
    response = client.post(reverse("api_upload"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_api_upload_requires_staff(non_staff_client):
    response = non_staff_client.post(reverse("api_upload"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_api_upload_requires_post(auth_client):
    response = auth_client.get(reverse("api_upload"))

    assert response.status_code == 405


@pytest.mark.django_db
def test_api_upload_rejects_empty_request(auth_client):
    response = auth_client.post(reverse("api_upload"))

    assert response.status_code == 400
    assert "Keine Dateien" in response.json()["error"]
    assert not Image.objects.exists()


@pytest.mark.django_db
def test_api_upload_creates_unsorted_images(auth_client):
    response = auth_client.post(
        reverse("api_upload"),
        {
            "files": [
                make_uploaded_jpeg("scan_002.jpg", color=(10, 10, 10)),
                make_uploaded_jpeg("scan_001.jpg", color=(20, 20, 20)),
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [entry["filename"] for entry in payload["created"]] == [
        "scan_001.jpg",
        "scan_002.jpg",
    ]
    assert payload["skipped"] == []
    images = list(Image.objects.order_by("filename"))
    assert [img.filename for img in images] == ["scan_001.jpg", "scan_002.jpg"]
    assert all(img.box_id is None for img in images)
    assert all(img.sequence_in_box is None for img in images)
    assert all(img.content_hash for img in images)
    assert all(img.thumb_small for img in images)


@pytest.mark.django_db
def test_api_upload_rejects_duplicate_filenames_in_batch(auth_client):
    response = auth_client.post(
        reverse("api_upload"),
        {
            "files": [
                make_uploaded_jpeg("scan.jpg", color=(1, 2, 3)),
                make_uploaded_jpeg("scan.jpg", color=(4, 5, 6)),
            ]
        },
    )

    assert response.status_code == 400
    assert "Doppelte Dateinamen" in response.json()["error"]
    assert not Image.objects.exists()


@pytest.mark.django_db
def test_api_upload_skips_duplicate_content_hash(auth_client):
    raw = make_jpeg_bytes(color=(42, 42, 42))
    auth_client.post(
        reverse("api_upload"),
        {"files": [SimpleUploadedFile("a.jpg", raw, "image/jpeg")]},
    )
    assert Image.objects.count() == 1

    response = auth_client.post(
        reverse("api_upload"),
        {"files": [SimpleUploadedFile("b.jpg", raw, "image/jpeg")]},
    )

    assert response.status_code == 200
    assert response.json()["skipped"] == ["b.jpg"]
    assert response.json()["created"] == []
    assert Image.objects.count() == 1


@pytest.mark.django_db
def test_api_upload_rejects_non_image_file(auth_client):
    response = auth_client.post(
        reverse("api_upload"),
        {"files": [SimpleUploadedFile("broken.jpg", b"not an image", "image/jpeg")]},
    )

    assert response.status_code == 400
    assert "kein g" in response.json()["error"]
    assert not Image.objects.exists()


@pytest.mark.django_db
def test_unsorted_view_orders_images_by_filename(auth_client):
    ImageFactory(box=None, sequence_in_box=None, filename="c.jpg")
    ImageFactory(box=None, sequence_in_box=None, filename="a.jpg")
    ImageFactory(box=None, sequence_in_box=None, filename="b.jpg")

    response = auth_client.get(reverse("unsorted"))

    content = response.content.decode("utf-8")
    assert content.index("a.jpg") < content.index("b.jpg") < content.index("c.jpg")
