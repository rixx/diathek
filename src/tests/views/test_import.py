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
    user = UserFactory()
    client.force_login(user)
    client.user = user
    return client


@pytest.mark.django_db
def test_import_get_requires_login(client):
    response = client.get(reverse("import"))

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_import_get_renders_form_with_existing_boxes(auth_client):
    BoxFactory(name="Omas Dachboden")

    response = auth_client.get(reverse("import"))

    assert response.status_code == 200
    assert b"Omas Dachboden" in response.content


@pytest.mark.django_db
def test_import_get_excludes_archived_boxes_from_choices(auth_client):
    BoxFactory(name="Aktive Box")
    BoxFactory(name="Alte Box", archived=True)

    response = auth_client.get(reverse("import"))

    content = response.content.decode("utf-8")
    assert "Aktive Box" in content
    assert "Alte Box" not in content


@pytest.mark.django_db
def test_import_uploads_to_unsorted_when_no_box_chosen(auth_client):
    response = auth_client.post(
        reverse("import"),
        {
            "box_choice": ImportForm.BOX_UNSORTED,
            "files": [make_uploaded_jpeg("scan_002.jpg")],
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("unsorted")
    image = Image.objects.get()
    assert image.box is None
    assert image.sequence_in_box is None
    assert image.filename == "scan_002.jpg"
    assert image.content_hash
    assert image.thumb_small
    assert image.width > 0


@pytest.mark.django_db
def test_import_creates_new_box_and_assigns_sequences_by_filename(auth_client):
    response = auth_client.post(
        reverse("import"),
        {
            "box_choice": ImportForm.BOX_NEW,
            "new_box_name": "Omas Dachboden",
            "new_box_description": "rote Kiste",
            "files": [
                make_uploaded_jpeg("scan_002.jpg", color=(10, 10, 10)),
                make_uploaded_jpeg("scan_001.jpg", color=(20, 20, 20)),
            ],
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("index")
    box = Box.objects.get(name="Omas Dachboden")
    assert box.description == "rote Kiste"
    ordered = list(box.images.order_by("sequence_in_box"))
    assert [img.filename for img in ordered] == ["scan_001.jpg", "scan_002.jpg"]
    assert [img.sequence_in_box for img in ordered] == [1, 2]


@pytest.mark.django_db
def test_import_new_box_requires_name(auth_client):
    response = auth_client.post(
        reverse("import"),
        {
            "box_choice": ImportForm.BOX_NEW,
            "new_box_name": "",
            "files": [make_uploaded_jpeg("scan.jpg")],
        },
    )

    assert response.status_code == 200
    assert not Box.objects.exists()
    assert not Image.objects.exists()
    assert b"Namen" in response.content


@pytest.mark.django_db
def test_import_appends_sequences_to_existing_box(auth_client):
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    ImageFactory(box=box, sequence_in_box=2, filename="b.jpg")

    auth_client.post(
        reverse("import"),
        {"box_choice": str(box.pk), "files": [make_uploaded_jpeg("c.jpg")]},
    )

    added = box.images.get(filename="c.jpg")
    assert added.sequence_in_box == 3


@pytest.mark.django_db
def test_import_rejects_duplicate_filenames_within_batch(auth_client):
    response = auth_client.post(
        reverse("import"),
        {
            "box_choice": ImportForm.BOX_UNSORTED,
            "files": [
                make_uploaded_jpeg("scan.jpg", color=(1, 2, 3)),
                make_uploaded_jpeg("scan.jpg", color=(4, 5, 6)),
            ],
        },
    )

    assert response.status_code == 200
    assert not Image.objects.exists()
    assert b"Doppelte Dateinamen" in response.content


@pytest.mark.django_db
def test_import_rejects_filename_collision_in_target_box(auth_client):
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, filename="scan.jpg")

    response = auth_client.post(
        reverse("import"),
        {"box_choice": str(box.pk), "files": [make_uploaded_jpeg("scan.jpg")]},
    )

    assert response.status_code == 200
    assert box.images.count() == 1
    assert b"existiert bereits" in response.content


@pytest.mark.django_db
def test_import_skips_duplicate_content_hash(auth_client):
    box = BoxFactory()
    raw = make_jpeg_bytes(color=(123, 45, 67))
    auth_client.post(
        reverse("import"),
        {
            "box_choice": str(box.pk),
            "files": [SimpleUploadedFile("a.jpg", raw, "image/jpeg")],
        },
    )
    assert box.images.count() == 1

    response = auth_client.post(
        reverse("import"),
        {
            "box_choice": str(box.pk),
            "files": [SimpleUploadedFile("b.jpg", raw, "image/jpeg")],
        },
    )

    assert response.status_code == 302
    assert box.images.count() == 1


@pytest.mark.django_db
def test_import_skips_duplicate_hash_in_unsorted(auth_client):
    raw = make_jpeg_bytes(color=(42, 42, 42))
    auth_client.post(
        reverse("import"),
        {
            "box_choice": ImportForm.BOX_UNSORTED,
            "files": [SimpleUploadedFile("a.jpg", raw, "image/jpeg")],
        },
    )
    assert Image.objects.count() == 1

    auth_client.post(
        reverse("import"),
        {
            "box_choice": ImportForm.BOX_UNSORTED,
            "files": [SimpleUploadedFile("b.jpg", raw, "image/jpeg")],
        },
    )

    assert Image.objects.count() == 1


@pytest.mark.django_db
def test_import_rejects_non_image_file(auth_client):
    response = auth_client.post(
        reverse("import"),
        {
            "box_choice": ImportForm.BOX_UNSORTED,
            "files": [SimpleUploadedFile("broken.jpg", b"not an image", "image/jpeg")],
        },
    )

    assert response.status_code == 200
    assert not Image.objects.exists()
    assert b"kein g" in response.content


@pytest.mark.django_db
def test_import_rerenders_when_no_files_submitted(auth_client):
    response = auth_client.post(
        reverse("import"), {"box_choice": ImportForm.BOX_UNSORTED}
    )

    assert response.status_code == 200
    assert b"errorlist" in response.content or b"required" in response.content.lower()
    assert not Image.objects.exists()


@pytest.mark.django_db
def test_import_builds_detail_thumb_for_large_images(auth_client):
    from diathek.core.thumbnails import THUMB_DETAIL_MAX

    response = auth_client.post(
        reverse("import"),
        {
            "box_choice": ImportForm.BOX_UNSORTED,
            "files": [
                make_uploaded_jpeg(
                    "big.jpg",
                    width=THUMB_DETAIL_MAX + 200,
                    height=THUMB_DETAIL_MAX + 100,
                )
            ],
        },
    )

    assert response.status_code == 302
    image = Image.objects.get()
    assert image.thumb_detail
