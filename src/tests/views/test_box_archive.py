import pytest
from django.urls import reverse

from tests.factories import BoxFactory, ImageFactory, UserFactory

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
def test_archive_requires_staff(auth_client):
    box = BoxFactory()

    response = auth_client.get(reverse("box_archive", args=[box.uuid]))

    assert response.status_code == 302


@pytest.mark.django_db
def test_archive_get_shows_confirmation_when_ready(staff_client):
    box = BoxFactory(name="Omas Schachtel")
    ImageFactory(box=box, sequence_in_box=1, immich_uploaded=True)

    response = staff_client.get(reverse("box_archive", args=[box.uuid]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Omas Schachtel" in content
    assert "Endgültig archivieren" in content


@pytest.mark.django_db
def test_archive_get_lists_open_todos_when_not_ready(staff_client):
    box = BoxFactory()
    blocker = ImageFactory(
        box=box, sequence_in_box=1, filename="offen.jpg", place_todo=True
    )

    response = staff_client.get(reverse("box_archive", args=[box.uuid]))

    content = response.content.decode()
    assert "kann nicht archiviert werden" in content
    assert blocker.filename in content


@pytest.mark.django_db
def test_archive_post_archives_when_name_matches(staff_client):
    box = BoxFactory(name="Fertig")
    ImageFactory(box=box, sequence_in_box=1, immich_uploaded=True)

    response = staff_client.post(
        reverse("box_archive", args=[box.uuid]), {"confirm_name": "Fertig"}
    )

    box.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("box_grid", args=[box.uuid])
    assert box.archived is True


@pytest.mark.django_db
def test_archive_post_rejects_wrong_confirmation(staff_client):
    box = BoxFactory(name="Korrekt")
    ImageFactory(box=box, sequence_in_box=1, immich_uploaded=True)

    response = staff_client.post(
        reverse("box_archive", args=[box.uuid]), {"confirm_name": "Falsch"}
    )

    box.refresh_from_db()
    assert response.status_code == 200
    assert box.archived is False
    assert b"field-error" in response.content


@pytest.mark.django_db
def test_archive_already_archived_redirects_to_grid(staff_client):
    box = BoxFactory(archived=True)

    response = staff_client.get(reverse("box_archive", args=[box.uuid]))

    assert response.status_code == 302
    assert response.url == reverse("box_grid", args=[box.uuid])


@pytest.mark.django_db
def test_archive_post_with_blocker_surfaces_error(staff_client):
    box = BoxFactory(name="Block")
    # Immich-complete but still has an open todo, so box.archive() raises.
    ImageFactory(box=box, sequence_in_box=1, place_todo=True, immich_uploaded=True)
    # confirm_name wouldn't even be shown because can_archive is False;
    # but if someone POSTs anyway, we show the error and don't archive.
    response = staff_client.post(
        reverse("box_archive", args=[box.uuid]), {"confirm_name": "Block"}
    )

    box.refresh_from_db()
    assert response.status_code == 200
    assert box.archived is False
    assert "Box kann nicht archiviert werden." in response.content.decode()


@pytest.mark.django_db
def test_archive_post_blocked_when_not_immich_complete(staff_client):
    box = BoxFactory(name="Unhochgeladen")
    # no open todos, so can_archive is True, but no Immich upload yet
    ImageFactory(box=box, sequence_in_box=1)

    response = staff_client.post(
        reverse("box_archive", args=[box.uuid]), {"confirm_name": "Unhochgeladen"}
    )

    box.refresh_from_db()
    assert response.status_code == 200
    assert box.archived is False
    assert (
        "Box muss zuerst vollständig zu Immich hochgeladen werden"
        in response.content.decode()
    )


@pytest.mark.django_db
def test_grid_for_archived_box_shows_immich_fallback(staff_client):
    box = BoxFactory(archived=True)

    response = staff_client.get(reverse("box_grid", args=[box.uuid]))

    content = response.content.decode()
    assert "archiviert" in content
    assert "Nicht zu Immich hochgeladen." in content


@pytest.mark.django_db
def test_grid_for_archived_box_shows_immich_album_link(staff_client):
    box = BoxFactory(
        archived=True, immich_album_url="https://immich.test/albums/album-1"
    )

    response = staff_client.get(reverse("box_grid", args=[box.uuid]))

    content = response.content.decode()
    assert "In Immich öffnen" in content
    assert "https://immich.test/albums/album-1" in content
