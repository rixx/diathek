import pytest
from django.urls import reverse

from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_client(client):
    client.force_login(UserFactory())
    return client


@pytest.fixture
def staff_client(client):
    client.force_login(UserFactory(is_staff=True))
    return client


@pytest.mark.django_db
def test_index_requires_login(client):
    response = client.get(reverse("index"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_index_lists_active_boxes_and_shows_unsorted_banner(staff_client):
    BoxFactory(name="Dachboden")
    archived = BoxFactory(name="Altarchiv", archived=True)
    ImageFactory(box=None, sequence_in_box=None)

    response = staff_client.get(reverse("index"))

    content = response.content.decode("utf-8")
    assert "Dachboden" in content
    # archived boxes appear in their own dedicated section, not the active list
    assert content.count("Altarchiv") == 1
    assert "Archivierte Boxen" in content
    assert archived.name in content
    assert "1 unsortierte" in content


@pytest.mark.django_db
def test_index_hides_upload_and_unsorted_for_non_staff(auth_client):
    ImageFactory(box=None, sequence_in_box=None)

    response = auth_client.get(reverse("index"))

    content = response.content.decode("utf-8")
    assert "Neue Bilder hochladen" not in content
    assert "unsortierte" not in content
    assert reverse("import") not in content
    assert reverse("unsorted") not in content


@pytest.mark.django_db
def test_index_shows_upload_button_for_can_upload_users(client):
    user = UserFactory(is_staff=False, can_upload=True)
    client.force_login(user)

    response = client.get(reverse("index"))

    content = response.content.decode("utf-8")
    assert "Neue Bilder hochladen" in content
    assert reverse("import") in content


@pytest.mark.django_db
def test_index_hides_upload_button_from_staff_without_can_upload(staff_client):
    response = staff_client.get(reverse("index"))

    content = response.content.decode("utf-8")
    assert "Neue Bilder hochladen" not in content


@pytest.mark.django_db
def test_index_without_boxes_shows_empty_message(auth_client):
    response = auth_client.get(reverse("index"))

    assert b"Noch keine Boxen" in response.content


@pytest.mark.django_db
def test_index_prompts_staff_to_archive_ready_boxes(staff_client):
    ready = BoxFactory(name="Fertigbox")
    ImageFactory(box=ready, sequence_in_box=1, immich_uploaded=True)
    not_ready = BoxFactory(name="Offenbox")
    ImageFactory(box=not_ready, sequence_in_box=1)  # not uploaded to Immich

    response = staff_client.get(reverse("index"))

    content = response.content.decode("utf-8")
    assert list(response.context["archive_ready_boxes"]) == [ready]
    assert "Bereit zum Archivieren" in content
    assert reverse("box_archive", args=[ready.uuid]) in content
    # boxes that are not ready are not offered for archival
    assert reverse("box_archive", args=[not_ready.uuid]) not in content


@pytest.mark.django_db
def test_index_hides_archive_prompt_from_non_staff(auth_client):
    ready = BoxFactory(name="Fertigbox")
    ImageFactory(box=ready, sequence_in_box=1, immich_uploaded=True)

    response = auth_client.get(reverse("index"))

    content = response.content.decode("utf-8")
    assert list(response.context["archive_ready_boxes"]) == []
    assert "Bereit zum Archivieren" not in content
    assert reverse("box_archive", args=[ready.uuid]) not in content


@pytest.mark.django_db
def test_index_omits_archive_prompt_when_no_box_ready(staff_client):
    box = BoxFactory(name="Offenbox")
    ImageFactory(box=box, sequence_in_box=1)  # not uploaded to Immich

    response = staff_client.get(reverse("index"))

    content = response.content.decode("utf-8")
    assert list(response.context["archive_ready_boxes"]) == []
    assert "Bereit zum Archivieren" not in content
