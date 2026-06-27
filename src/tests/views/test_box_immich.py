import os
import tempfile
from pathlib import Path

import pytest
from django.urls import reverse

from diathek.core.models import ImmichState
from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.integration


class FakeClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        self.album_name = None
        self.uploads = []
        self.added = []

    def get_or_create_album(self, name):
        self.album_name = name
        return {"id": "album-1", "albumName": name}

    def upload_asset(self, **kwargs):
        self.uploads.append(kwargs)
        return {"id": f"asset-{len(self.uploads)}", "status": "created"}

    def add_to_album(self, album_id, asset_ids):
        self.added.append((album_id, list(asset_ids)))

    def bulk_check(self, items):
        return [
            {"action": "reject", "reason": "duplicate", "assetId": "a"} for _ in items
        ]

    def album_web_url(self, album_id):
        return f"https://immich.test/albums/{album_id}"


@pytest.fixture
def immich_url(settings):
    settings.IMMICH_BASE_URL = "https://immich.test"
    return settings.IMMICH_BASE_URL


@pytest.fixture
def rendered(mocker):
    created = []

    def _render(image):
        fd, name = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        path = Path(name)
        created.append(path)
        return path

    mocker.patch("diathek.core.tasks.render_processed_image", side_effect=_render)
    mocker.patch("diathek.core.tasks.sha1_hex", return_value="sha1-checksum")
    return created


@pytest.fixture
def fake_client(mocker):
    fake = FakeClient("https://immich.test", "api-key-123")
    mocker.patch("diathek.core.tasks.ImmichClient", return_value=fake)
    return fake


@pytest.fixture
def upload_client(client):
    user = UserFactory(can_upload=True, immich_api_key="api-key-123")
    client.force_login(user)
    client.user = user
    return client


@pytest.fixture
def no_upload_client(client):
    user = UserFactory(can_upload=False, immich_api_key="api-key-123")
    client.force_login(user)
    client.user = user
    return client


# --- permissions -----------------------------------------------------------


@pytest.mark.django_db
def test_finalize_requires_login(client):
    box = BoxFactory()

    response = client.post(reverse("box_immich_finalize", args=[box.uuid]))

    assert response.status_code == 302


@pytest.mark.django_db
def test_finalize_requires_upload_permission(no_upload_client):
    box = BoxFactory()

    response = no_upload_client.post(reverse("box_immich_finalize", args=[box.uuid]))

    assert response.status_code == 302


@pytest.mark.django_db
def test_status_requires_upload_permission(no_upload_client):
    box = BoxFactory()

    response = no_upload_client.get(reverse("box_immich_status", args=[box.uuid]))

    assert response.status_code == 302


@pytest.mark.django_db
def test_finalize_requires_post(upload_client):
    box = BoxFactory()

    response = upload_client.get(reverse("box_immich_finalize", args=[box.uuid]))

    assert response.status_code == 405


@pytest.mark.django_db
def test_finalize_missing_box_returns_404(upload_client):
    response = upload_client.post(
        reverse("box_immich_finalize", args=["00000000-0000-0000-0000-000000000000"])
    )

    assert response.status_code == 404


# --- finalize happy path ---------------------------------------------------


@pytest.mark.django_db
def test_finalize_uploads_box(upload_client, immich_url, rendered, fake_client):
    box = BoxFactory(name="Sommer 90")
    ImageFactory(box=box, sequence_in_box=1)
    ImageFactory(box=box, sequence_in_box=2)

    response = upload_client.post(reverse("box_immich_finalize", args=[box.uuid]))

    assert response.status_code == 200
    box.refresh_from_db()
    assert box.immich_state == ImmichState.UPLOADED
    assert box.immich_album_url == "https://immich.test/albums/album-1"
    assert len(fake_client.uploads) == 2
    content = response.content.decode()
    assert "In Immich öffnen" in content
    assert box.immich_album_url in content


@pytest.mark.django_db
def test_finalize_sets_in_progress_and_enqueues(upload_client, immich_url, mocker):
    enqueue = mocker.patch("diathek.core.views.finalize_box").enqueue
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1)

    response = upload_client.post(reverse("box_immich_finalize", args=[box.uuid]))

    box.refresh_from_db()
    assert box.immich_state == ImmichState.IN_PROGRESS
    enqueue.assert_called_once_with(box.id, upload_client.user.id)
    content = response.content.decode()
    assert "every 2s" in content
    assert "0 / 1" in content


# --- finalize rejection guards ---------------------------------------------


@pytest.mark.django_db
def test_finalize_rejects_archived_box(upload_client, immich_url, mocker):
    enqueue = mocker.patch("diathek.core.views.finalize_box").enqueue
    box = BoxFactory(archived=True)
    ImageFactory(box=box, sequence_in_box=1)

    response = upload_client.post(reverse("box_immich_finalize", args=[box.uuid]))

    box.refresh_from_db()
    assert box.immich_state == ImmichState.NOT_UPLOADED
    enqueue.assert_not_called()
    assert "Archivierte Box kann nicht hochgeladen werden." in response.content.decode()


@pytest.mark.django_db
def test_finalize_rejects_without_immich_key(client, immich_url, mocker):
    enqueue = mocker.patch("diathek.core.views.finalize_box").enqueue
    user = UserFactory(can_upload=True, immich_api_key="")
    client.force_login(user)
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1)

    response = client.post(reverse("box_immich_finalize", args=[box.uuid]))

    box.refresh_from_db()
    assert box.immich_state == ImmichState.NOT_UPLOADED
    enqueue.assert_not_called()
    content = response.content.decode()
    assert "Immich-API-Schlüssel hinterlegen" in content


@pytest.mark.django_db
def test_finalize_rejects_without_base_url(upload_client, settings, mocker):
    settings.IMMICH_BASE_URL = ""
    enqueue = mocker.patch("diathek.core.views.finalize_box").enqueue
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1)

    response = upload_client.post(reverse("box_immich_finalize", args=[box.uuid]))

    box.refresh_from_db()
    assert box.immich_state == ImmichState.NOT_UPLOADED
    enqueue.assert_not_called()
    assert "Immich-Server ist nicht konfiguriert." in response.content.decode()


@pytest.mark.django_db
def test_finalize_rejects_open_todos(upload_client, immich_url, mocker):
    enqueue = mocker.patch("diathek.core.views.finalize_box").enqueue
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, place_todo=True)

    response = upload_client.post(reverse("box_immich_finalize", args=[box.uuid]))

    box.refresh_from_db()
    assert box.immich_state == ImmichState.NOT_UPLOADED
    enqueue.assert_not_called()
    assert "Box hat noch offene Aufgaben." in response.content.decode()


@pytest.mark.django_db
def test_finalize_rejects_when_already_in_progress(upload_client, immich_url, mocker):
    enqueue = mocker.patch("diathek.core.views.finalize_box").enqueue
    box = BoxFactory(immich_state=ImmichState.IN_PROGRESS)
    ImageFactory(box=box, sequence_in_box=1)

    response = upload_client.post(reverse("box_immich_finalize", args=[box.uuid]))

    box.refresh_from_db()
    assert box.immich_state == ImmichState.IN_PROGRESS
    enqueue.assert_not_called()
    assert "Upload läuft bereits." in response.content.decode()


@pytest.mark.django_db
def test_finalize_rejects_empty_box(upload_client, immich_url, mocker):
    enqueue = mocker.patch("diathek.core.views.finalize_box").enqueue
    box = BoxFactory()

    response = upload_client.post(reverse("box_immich_finalize", args=[box.uuid]))

    box.refresh_from_db()
    assert box.immich_state == ImmichState.NOT_UPLOADED
    enqueue.assert_not_called()
    assert "Box enthält keine Bilder." in response.content.decode()


# --- status endpoint variants ----------------------------------------------


@pytest.mark.django_db
def test_status_not_uploaded_shows_button(upload_client):
    box = BoxFactory()

    response = upload_client.get(reverse("box_immich_status", args=[box.uuid]))

    content = response.content.decode()
    assert "Zu Immich hochladen" in content
    assert reverse("box_immich_finalize", args=[box.uuid]) in content


@pytest.mark.django_db
def test_status_not_uploaded_without_key_shows_hint(client):
    user = UserFactory(can_upload=True, immich_api_key="")
    client.force_login(user)
    box = BoxFactory()

    response = client.get(reverse("box_immich_status", args=[box.uuid]))

    content = response.content.decode()
    assert "Zu Immich hochladen" not in content
    assert reverse("account_settings") in content


@pytest.mark.django_db
def test_status_in_progress_shows_count_and_polls(upload_client):
    box = BoxFactory(immich_state=ImmichState.IN_PROGRESS)
    ImageFactory(box=box, sequence_in_box=1, immich_uploaded=True)
    ImageFactory(box=box, sequence_in_box=2)

    response = upload_client.get(reverse("box_immich_status", args=[box.uuid]))

    content = response.content.decode()
    assert "1 / 2" in content
    assert "every 2s" in content
    assert reverse("box_immich_status", args=[box.uuid]) in content


@pytest.mark.django_db
def test_status_uploaded_shows_album_link(upload_client):
    box = BoxFactory(
        immich_state=ImmichState.UPLOADED,
        immich_album_url="https://immich.test/albums/album-1",
    )

    response = upload_client.get(reverse("box_immich_status", args=[box.uuid]))

    content = response.content.decode()
    assert "In Immich öffnen" in content
    assert "https://immich.test/albums/album-1" in content
    assert "every 2s" not in content


@pytest.mark.django_db
def test_status_failed_shows_error_and_retry(upload_client):
    box = BoxFactory(immich_state=ImmichState.FAILED, immich_error="Verbindung kaputt")

    response = upload_client.get(reverse("box_immich_status", args=[box.uuid]))

    content = response.content.decode()
    assert "Verbindung kaputt" in content
    assert "Erneut versuchen" in content
    assert reverse("box_immich_retry", args=[box.uuid]) in content
    assert "every 2s" not in content


# --- retry -----------------------------------------------------------------


@pytest.mark.django_db
def test_retry_from_failed_re_enqueues(upload_client, immich_url, mocker):
    enqueue = mocker.patch("diathek.core.views.finalize_box").enqueue
    box = BoxFactory(immich_state=ImmichState.FAILED, immich_error="kaputt")
    ImageFactory(box=box, sequence_in_box=1)

    response = upload_client.post(reverse("box_immich_retry", args=[box.uuid]))

    box.refresh_from_db()
    assert box.immich_state == ImmichState.IN_PROGRESS
    assert box.immich_error == ""
    enqueue.assert_called_once_with(box.id, upload_client.user.id)
    assert "every 2s" in response.content.decode()


@pytest.mark.django_db
def test_retry_runs_task_to_completion(
    upload_client, immich_url, rendered, fake_client
):
    box = BoxFactory(immich_state=ImmichState.FAILED, immich_error="kaputt")
    ImageFactory(box=box, sequence_in_box=1)

    response = upload_client.post(reverse("box_immich_retry", args=[box.uuid]))

    box.refresh_from_db()
    assert box.immich_state == ImmichState.UPLOADED
    assert len(fake_client.uploads) == 1
    assert "In Immich öffnen" in response.content.decode()


@pytest.mark.django_db
def test_retry_noop_when_not_failed(upload_client, mocker):
    enqueue = mocker.patch("diathek.core.views.finalize_box").enqueue
    box = BoxFactory(immich_state=ImmichState.NOT_UPLOADED)

    response = upload_client.post(reverse("box_immich_retry", args=[box.uuid]))

    box.refresh_from_db()
    assert box.immich_state == ImmichState.NOT_UPLOADED
    enqueue.assert_not_called()
    assert "Erneuter Versuch ist nur nach einem Fehler möglich." in (
        response.content.decode()
    )


@pytest.mark.django_db
def test_retry_rejects_archived_box(upload_client, immich_url, mocker):
    enqueue = mocker.patch("diathek.core.views.finalize_box").enqueue
    box = BoxFactory(archived=True, immich_state=ImmichState.FAILED)
    ImageFactory(box=box, sequence_in_box=1)

    response = upload_client.post(reverse("box_immich_retry", args=[box.uuid]))

    box.refresh_from_db()
    assert box.immich_state == ImmichState.FAILED
    enqueue.assert_not_called()
    assert "Archivierte Box kann nicht hochgeladen werden." in response.content.decode()
