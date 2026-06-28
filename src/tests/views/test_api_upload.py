import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from diathek.core.forms import ImportForm
from diathek.core.models import Box, Image
from tests.factories import BoxFactory, ImageFactory, UserFactory
from tests.helpers import make_jpeg_bytes, make_uploaded_jpeg

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_client(client):
    user = UserFactory(is_staff=True, can_upload=True)
    client.force_login(user)
    client.user = user
    return client


@pytest.fixture
def non_upload_client(client):
    user = UserFactory(is_staff=True, can_upload=False)
    client.force_login(user)
    client.user = user
    return client


@pytest.mark.django_db
def test_api_upload_requires_login(client):
    response = client.post(reverse("api_upload"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_api_upload_requires_upload_permission(non_upload_client):
    response = non_upload_client.post(reverse("api_upload"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_api_upload_allows_non_staff_with_can_upload(client):
    user = UserFactory(is_staff=False, can_upload=True)
    client.force_login(user)

    response = client.post(
        reverse("api_upload"), {"files": [make_uploaded_jpeg("scan.jpg")]}
    )

    assert response.status_code == 200
    assert Image.objects.count() == 1


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
def test_api_upload_into_box_assigns_sequence(auth_client):
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, filename="existing.jpg")

    response = auth_client.post(
        reverse("api_upload"),
        {
            "files": [make_uploaded_jpeg("scan.jpg", color=(7, 8, 9))],
            "box": str(box.pk),
        },
    )

    assert response.status_code == 200
    added = box.images.get(filename="scan.jpg")
    assert added.sequence_in_box == 2
    assert added.box_id == box.pk


@pytest.mark.django_db
def test_api_upload_into_box_rejects_filename_conflict(auth_client):
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, filename="scan.jpg")

    response = auth_client.post(
        reverse("api_upload"),
        {
            "files": [make_uploaded_jpeg("scan.jpg", color=(9, 9, 9))],
            "box": str(box.pk),
        },
    )

    assert response.status_code == 400
    assert "existiert bereits" in response.json()["error"]
    assert box.images.count() == 1


@pytest.mark.django_db
def test_api_upload_dedup_is_scoped_per_box(auth_client):
    raw = make_jpeg_bytes(color=(3, 3, 3))
    box = BoxFactory()
    other = BoxFactory()
    auth_client.post(
        reverse("api_upload"),
        {"files": [SimpleUploadedFile("a.jpg", raw, "image/jpeg")], "box": str(box.pk)},
    )

    # Same bytes again into the same box: skipped as a duplicate.
    same_box = auth_client.post(
        reverse("api_upload"),
        {"files": [SimpleUploadedFile("b.jpg", raw, "image/jpeg")], "box": str(box.pk)},
    )
    assert same_box.json()["skipped"] == ["b.jpg"]
    assert box.images.count() == 1

    # Same bytes into a different box: allowed, because dedup is per box.
    other_box = auth_client.post(
        reverse("api_upload"),
        {
            "files": [SimpleUploadedFile("c.jpg", raw, "image/jpeg")],
            "box": str(other.pk),
        },
    )
    assert other_box.json()["skipped"] == []
    assert other.images.count() == 1


@pytest.mark.django_db
def test_api_upload_rejects_unknown_box(auth_client):
    response = auth_client.post(
        reverse("api_upload"),
        {"files": [make_uploaded_jpeg("scan.jpg")], "box": "9999"},
    )

    assert response.status_code == 404
    assert "Box nicht gefunden" in response.json()["error"]
    assert not Image.objects.exists()


@pytest.mark.django_db
def test_api_upload_rejects_archived_box(auth_client):
    box = BoxFactory(archived=True)

    response = auth_client.post(
        reverse("api_upload"),
        {"files": [make_uploaded_jpeg("scan.jpg")], "box": str(box.pk)},
    )

    assert response.status_code == 404
    assert not Image.objects.exists()


@pytest.mark.django_db
def test_upload_prepare_requires_login(client):
    response = client.post(reverse("upload_prepare"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_upload_prepare_requires_upload_permission(non_upload_client):
    response = non_upload_client.post(reverse("upload_prepare"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_upload_prepare_requires_post(auth_client):
    response = auth_client.get(reverse("upload_prepare"))

    assert response.status_code == 405


@pytest.mark.django_db
def test_upload_prepare_unsorted_for_staff_targets_unsorted(auth_client):
    response = auth_client.post(
        reverse("upload_prepare"), {"box_choice": ImportForm.BOX_UNSORTED}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["box"] == ""
    assert payload["redirect"] == reverse("unsorted")


@pytest.mark.django_db
def test_upload_prepare_unsorted_for_non_staff_targets_index(client):
    user = UserFactory(is_staff=False, can_upload=True)
    client.force_login(user)

    response = client.post(reverse("upload_prepare"), {"box_choice": ""})

    assert response.status_code == 200
    assert response.json()["redirect"] == reverse("index")


@pytest.mark.django_db
def test_upload_prepare_creates_new_box(auth_client):
    response = auth_client.post(
        reverse("upload_prepare"),
        {
            "box_choice": ImportForm.BOX_NEW,
            "new_box_name": "Omas Dachboden",
            "new_box_description": "rote Kiste",
        },
    )

    assert response.status_code == 200
    box = Box.objects.get(name="Omas Dachboden")
    assert box.description == "rote Kiste"
    payload = response.json()
    assert payload["box"] == str(box.pk)
    assert payload["label"] == "Omas Dachboden"
    assert payload["redirect"] == reverse("box_grid", args=[box.uuid])


@pytest.mark.django_db
def test_upload_prepare_new_box_requires_name(auth_client):
    response = auth_client.post(
        reverse("upload_prepare"),
        {"box_choice": ImportForm.BOX_NEW, "new_box_name": "  "},
    )

    assert response.status_code == 400
    assert "Namen" in response.json()["error"]
    assert not Box.objects.exists()


@pytest.mark.django_db
def test_upload_prepare_resolves_existing_box(auth_client):
    box = BoxFactory(name="Bestehend")

    response = auth_client.post(reverse("upload_prepare"), {"box_choice": str(box.pk)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["box"] == str(box.pk)
    assert payload["redirect"] == reverse("box_grid", args=[box.uuid])


@pytest.mark.django_db
def test_upload_prepare_rejects_unknown_box(auth_client):
    response = auth_client.post(reverse("upload_prepare"), {"box_choice": "9999"})

    assert response.status_code == 404
    assert "Box nicht gefunden" in response.json()["error"]


@pytest.mark.django_db
def test_unsorted_view_orders_images_by_filename(auth_client):
    ImageFactory(box=None, sequence_in_box=None, filename="c.jpg")
    ImageFactory(box=None, sequence_in_box=None, filename="a.jpg")
    ImageFactory(box=None, sequence_in_box=None, filename="b.jpg")

    response = auth_client.get(reverse("unsorted"))

    content = response.content.decode("utf-8")
    assert content.index("a.jpg") < content.index("b.jpg") < content.index("c.jpg")
