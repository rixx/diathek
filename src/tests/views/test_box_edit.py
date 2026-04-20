import pytest
from django.urls import reverse

from diathek.core.models import Box
from tests.factories import BoxFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def upload_client(client):
    user = UserFactory(is_staff=False, can_upload=True)
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
def test_box_create_requires_login(client):
    response = client.get(reverse("box_create"))

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_box_create_requires_upload_permission(non_upload_client):
    response = non_upload_client.get(reverse("box_create"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_box_create_renders_form(upload_client):
    response = upload_client.get(reverse("box_create"))

    assert response.status_code == 200
    assert b"Neue Box" in response.content


@pytest.mark.django_db
def test_box_create_sets_sort_order_to_max_plus_one(upload_client):
    BoxFactory(name="Alpha", sort_order=3)
    BoxFactory(name="Beta", sort_order=7)

    response = upload_client.post(
        reverse("box_create"), {"name": "Neue Kiste", "description": "frisch"}
    )

    created = Box.objects.get(name="Neue Kiste")
    assert response.status_code == 302
    assert response.url == reverse("box_grid", args=[created.uuid])
    assert created.sort_order == 8
    assert created.description == "frisch"


@pytest.mark.django_db
def test_box_create_first_box_starts_at_one(upload_client):
    upload_client.post(reverse("box_create"), {"name": "Erste", "description": ""})

    assert Box.objects.get(name="Erste").sort_order == 1


@pytest.mark.django_db
def test_box_create_requires_name(upload_client):
    response = upload_client.post(
        reverse("box_create"), {"name": "", "description": "ohne Namen"}
    )

    assert response.status_code == 200
    assert not Box.objects.exists()
    assert b"field-error" in response.content


@pytest.mark.django_db
def test_box_edit_updates_name_and_description(upload_client):
    box = BoxFactory(name="Alt", description="alte Beschreibung", sort_order=4)

    response = upload_client.post(
        reverse("box_edit", args=[box.uuid]),
        {"name": "Neu", "description": "neue Beschreibung"},
    )

    box.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("box_grid", args=[box.uuid])
    assert box.name == "Neu"
    assert box.description == "neue Beschreibung"
    assert box.sort_order == 4


@pytest.mark.django_db
def test_box_edit_requires_upload_permission(non_upload_client):
    box = BoxFactory(name="Geheim")

    response = non_upload_client.get(reverse("box_edit", args=[box.uuid]))

    assert response.status_code == 302


@pytest.mark.django_db
def test_box_edit_rejects_archived_box(upload_client):
    box = BoxFactory(name="Archiviert", archived=True)

    response = upload_client.get(reverse("box_edit", args=[box.uuid]))

    assert response.status_code == 302
    assert response.url == reverse("box_grid", args=[box.uuid])


@pytest.mark.django_db
def test_box_edit_post_on_archived_box_is_rejected(upload_client):
    box = BoxFactory(name="Archiviert", description="unveränderlich", archived=True)

    response = upload_client.post(
        reverse("box_edit", args=[box.uuid]), {"name": "Neu", "description": "Versuch"}
    )

    box.refresh_from_db()
    assert response.status_code == 302
    assert box.name == "Archiviert"
    assert box.description == "unveränderlich"


@pytest.mark.django_db
def test_box_edit_unknown_box_returns_404(upload_client):
    response = upload_client.get(
        reverse("box_edit", args=["00000000-0000-0000-0000-000000000000"])
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_box_edit_renders_form_with_existing_values(upload_client):
    box = BoxFactory(name="Vorhanden", description="Schon da")

    response = upload_client.get(reverse("box_edit", args=[box.uuid]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Vorhanden" in content
    assert "Schon da" in content
