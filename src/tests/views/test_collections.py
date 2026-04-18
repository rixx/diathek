import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from diathek.core.models import Collection
from tests.factories import BoxFactory, CollectionFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def staff_client(client):
    user = UserFactory(is_staff=True)
    client.force_login(user)
    client.user = user
    return client


@pytest.fixture
def auth_client(client):
    user = UserFactory()
    client.force_login(user)
    client.user = user
    return client


@pytest.mark.django_db
def test_collection_list_requires_login(client):
    response = client.get(reverse("collection_list"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_collection_list_shows_collections_and_create_for_staff(staff_client):
    CollectionFactory(title="1987 Jahrgang")

    response = staff_client.get(reverse("collection_list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "1987 Jahrgang" in content
    assert reverse("collection_create") in content


@pytest.mark.django_db
def test_collection_list_hides_create_for_non_staff(auth_client):
    response = auth_client.get(reverse("collection_list"))

    assert response.status_code == 200
    assert reverse("collection_create") not in response.content.decode()


@pytest.mark.django_db
def test_collection_list_shows_empty_state(auth_client):
    response = auth_client.get(reverse("collection_list"))

    assert b"Noch keine Sammlungen" in response.content


@pytest.mark.django_db
def test_collection_detail_renders_boxes_and_immich(auth_client):
    box = BoxFactory(name="Altarchiv", archived=True)
    collection = CollectionFactory(title="Opa", immich_url="https://immich/x")
    collection.boxes.add(box)

    response = auth_client.get(reverse("collection_detail", args=[collection.pk]))

    content = response.content.decode()
    assert "Altarchiv" in content
    assert "https://immich/x" in content


@pytest.mark.django_db
def test_collection_detail_shows_placeholder_without_immich_url(auth_client):
    collection = CollectionFactory()

    response = auth_client.get(reverse("collection_detail", args=[collection.pk]))

    assert b"Immich-Link noch nicht bereit" in response.content


@pytest.mark.django_db
def test_collection_detail_shows_edit_only_for_staff(staff_client):
    collection = CollectionFactory()

    response = staff_client.get(reverse("collection_detail", args=[collection.pk]))

    assert reverse("collection_edit", args=[collection.pk]) in response.content.decode()


@pytest.mark.django_db
def test_collection_detail_returns_empty_boxes_message(auth_client):
    collection = CollectionFactory()

    response = auth_client.get(reverse("collection_detail", args=[collection.pk]))

    assert b"Keine Boxen zugeordnet" in response.content


@pytest.mark.django_db
def test_collection_detail_renders_cover_and_description(auth_client):
    box = BoxFactory()
    image = ImageFactory(box=box, sequence_in_box=1)
    image.thumb_small.save("x.webp", ContentFile(b"thumb"), save=True)
    collection = CollectionFactory(
        title="Sommer", description="schöner Sommer", cover_image=image
    )
    collection.boxes.add(box)

    response = auth_client.get(reverse("collection_detail", args=[collection.pk]))

    content = response.content.decode()
    assert "schöner Sommer" in content
    assert image.thumb_small.url in content


@pytest.mark.django_db
def test_collection_edit_requires_staff(auth_client):
    response = auth_client.get(reverse("collection_create"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_collection_create_flow(staff_client):
    box = BoxFactory(name="Neue Box")

    response = staff_client.post(
        reverse("collection_create"),
        {
            "title": "Frisch",
            "immich_url": "",
            "description": "",
            "cover_image": "",
            "boxes": [str(box.pk)],
        },
        follow=False,
    )

    assert response.status_code == 302
    created = Collection.objects.get(title="Frisch")
    assert response.url == reverse("collection_detail", args=[created.pk])
    assert list(created.boxes.all()) == [box]


@pytest.mark.django_db
def test_collection_edit_updates_existing(staff_client):
    box = BoxFactory()
    collection = CollectionFactory(title="Alt")
    collection.boxes.add(box)
    image = ImageFactory(box=box, sequence_in_box=1)

    response = staff_client.post(
        reverse("collection_edit", args=[collection.pk]),
        {
            "title": "Neu",
            "immich_url": "https://immich.example/y",
            "description": "",
            "cover_image": str(image.pk),
            "boxes": [str(box.pk)],
        },
    )

    collection.refresh_from_db()
    assert response.status_code == 302
    assert collection.title == "Neu"
    assert collection.cover_image_id == image.pk
    assert collection.immich_url == "https://immich.example/y"


@pytest.mark.django_db
def test_collection_edit_get_renders_form(staff_client):
    collection = CollectionFactory(title="X")

    response = staff_client.get(reverse("collection_edit", args=[collection.pk]))

    assert response.status_code == 200
    assert b'value="X"' in response.content


@pytest.mark.django_db
def test_collection_edit_shows_form_errors(staff_client):
    response = staff_client.post(
        reverse("collection_create"),
        {"title": "", "immich_url": "", "description": "", "cover_image": ""},
    )

    assert response.status_code == 200
    assert b"form-field--error" in response.content
