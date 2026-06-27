import os
import tempfile
from pathlib import Path

import pytest

from diathek.core.immich import ImmichError
from diathek.core.models import AuditLog, ImmichState
from diathek.core.tasks import finalize_box
from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.django_db


class FakeClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        self.album_name = None
        self.uploads = []
        self.added = []
        self.bulk_results = None
        self.album_callback = None
        self.upload_error_at = None

    def get_or_create_album(self, name):
        self.album_name = name
        if self.album_callback is not None:
            self.album_callback()
        return {"id": "album-1", "albumName": name}

    def upload_asset(self, **kwargs):
        self.uploads.append(kwargs)
        if (
            self.upload_error_at is not None
            and len(self.uploads) == self.upload_error_at
        ):
            raise ImmichError("upload kaputt")
        return {"id": f"asset-{len(self.uploads)}", "status": "created"}

    def add_to_album(self, album_id, asset_ids):
        self.added.append((album_id, list(asset_ids)))

    def bulk_check(self, items):
        if self.bulk_results is not None:
            return self.bulk_results
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
def user():
    return UserFactory(immich_api_key="api-key-123")


@pytest.fixture
def rendered(mocker):
    """Patch render_processed_image to create real temp files; track them."""
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


def test_happy_path_uploads_all_images(user, immich_url, rendered, fake_client):
    box = BoxFactory(name="Sommer 90")
    images = [ImageFactory(box=box, sequence_in_box=i) for i in (1, 2, 3)]

    finalize_box.enqueue(box.id, user.id)

    box.refresh_from_db()
    assert box.immich_state == ImmichState.UPLOADED
    assert box.immich_album_url == "https://immich.test/albums/album-1"
    assert box.immich_error == ""
    assert fake_client.album_name == "diathek-Sommer 90"

    # every image fully written
    for image in images:
        image.refresh_from_db()
        assert image.immich_asset_id
        assert image.immich_checksum == "sha1-checksum"
        assert image.immich_signature == image.compute_immich_signature()
        assert image.immich_uploaded_at is not None
        assert image.immich_owner_id == user.id

    # one upload per image with correct identifiers
    assert len(fake_client.uploads) == 3
    by_device = {u["device_asset_id"]: u for u in fake_client.uploads}
    for image in images:
        upload = by_device[str(image.uuid)]
        assert upload["filename"] == image.filename
        assert upload["device_id"] == "diathek"
        assert upload["checksum"] == "sha1-checksum"

    # album updated once with all asset ids
    assert len(fake_client.added) == 1
    album_id, asset_ids = fake_client.added[0]
    assert album_id == "album-1"
    assert sorted(asset_ids) == sorted(i.immich_asset_id for i in images)

    # temp files cleaned up
    assert all(not path.exists() for path in rendered)

    log = AuditLog.objects.get(action_type="box.immich_push")
    assert log.user_id == user.id
    assert log.box_id == box.id
    assert log.data["after"]["image_count"] == 3
    assert log.data["after"]["album_url"] == box.immich_album_url


def test_in_progress_state_set_before_work(user, immich_url, rendered, fake_client):
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1)
    seen = {}

    def _capture():
        from diathek.core.models import Box

        seen["state"] = Box.objects.get(pk=box.id).immich_state

    fake_client.album_callback = _capture

    finalize_box.enqueue(box.id, user.id)

    assert seen["state"] == ImmichState.IN_PROGRESS
    box.refresh_from_db()
    assert box.immich_state == ImmichState.UPLOADED


def test_resumable_skips_already_current_images(
    user, immich_url, rendered, fake_client
):
    box = BoxFactory()
    done = ImageFactory(box=box, sequence_in_box=1)
    done.immich_asset_id = "existing-asset"
    done.immich_checksum = "existing-sum"
    done.immich_signature = done.compute_immich_signature()
    done.save(skip_log=True, bump_version=False)
    fresh = ImageFactory(box=box, sequence_in_box=2)

    finalize_box.enqueue(box.id, user.id)

    box.refresh_from_db()
    assert box.immich_state == ImmichState.UPLOADED

    # only the fresh image was uploaded
    assert len(fake_client.uploads) == 1
    assert fake_client.uploads[0]["device_asset_id"] == str(fresh.uuid)

    # both ids land in the album
    _, asset_ids = fake_client.added[0]
    fresh.refresh_from_db()
    assert sorted(asset_ids) == sorted(["existing-asset", fresh.immich_asset_id])


def test_missing_api_key_fails(immich_url, rendered, fake_client, mocker):
    user = UserFactory(immich_api_key="")
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1)

    finalize_box.enqueue(box.id, user.id)

    box.refresh_from_db()
    assert box.immich_state == ImmichState.FAILED
    assert box.immich_error == "Kein Immich-API-Schlüssel konfiguriert."
    assert fake_client.uploads == []
    assert fake_client.album_name is None


def test_missing_base_url_fails(user, settings, rendered, fake_client):
    settings.IMMICH_BASE_URL = ""
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1)

    finalize_box.enqueue(box.id, user.id)

    box.refresh_from_db()
    assert box.immich_state == ImmichState.FAILED
    assert box.immich_error == "Immich-Server ist nicht konfiguriert."
    assert fake_client.uploads == []


def test_upload_error_marks_box_failed(user, immich_url, rendered, fake_client):
    box = BoxFactory()
    first = ImageFactory(box=box, sequence_in_box=1)
    ImageFactory(box=box, sequence_in_box=2)
    fake_client.upload_error_at = 2

    finalize_box.enqueue(box.id, user.id)

    box.refresh_from_db()
    assert box.immich_state == ImmichState.FAILED
    assert box.immich_error == "upload kaputt"

    # the first image is consistently persisted, not half-written
    first.refresh_from_db()
    assert first.immich_asset_id == "asset-1"
    assert first.immich_signature == first.compute_immich_signature()
    assert not AuditLog.objects.filter(action_type="box.immich_push").exists()


def test_verification_failure_marks_box_failed(user, immich_url, rendered, fake_client):
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1)
    ImageFactory(box=box, sequence_in_box=2)
    fake_client.bulk_results = [
        {"action": "reject", "reason": "duplicate", "assetId": "a"},
        {"action": "accept", "reason": None, "assetId": None},
    ]

    finalize_box.enqueue(box.id, user.id)

    box.refresh_from_db()
    assert box.immich_state == ImmichState.FAILED
    assert "1 von 2" in box.immich_error
    assert "fehlen" in box.immich_error


def test_empty_box_succeeds(user, immich_url, rendered, fake_client):
    box = BoxFactory()

    finalize_box.enqueue(box.id, user.id)

    box.refresh_from_db()
    assert box.immich_state == ImmichState.UPLOADED
    assert box.immich_album_url == "https://immich.test/albums/album-1"
    # no images -> no upload, no album mutation, no verification
    assert fake_client.uploads == []
    assert fake_client.added == []

    log = AuditLog.objects.get(action_type="box.immich_push")
    assert log.data["after"]["image_count"] == 0
