import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from diathek.core.immich import ImmichError
from diathek.core.models import AuditLog, Image
from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.integration

ASSET_WITH_BOTH = {
    "exifInfo": {
        "dateTimeOriginal": "1987-06-15T12:00:00.000Z",
        "latitude": 52.5200066,
        "longitude": 13.404954,
    }
}


@pytest.fixture
def auth_client(client):
    # Plain member (no upload rights) with an Immich key configured: pulling
    # metadata only needs a key, not upload permission.
    user = UserFactory(name="Karin", immich_api_key="api-key-123")
    client.force_login(user)
    client.user = user
    return client


@pytest.fixture
def image(db):
    box = BoxFactory(name="Dachboden")
    return ImageFactory(box=box, filename="scan_001.jpg", sequence_in_box=1)


@pytest.fixture
def fake_asset(mocker):
    """Patch the Immich client; configure the returned asset per test."""
    holder = {"asset": ASSET_WITH_BOTH, "error": False}

    class FakeClient:
        def __init__(self, base_url, api_key):
            self.base_url = base_url
            self.api_key = api_key

        def get_asset(self, asset_id):
            holder["asset_id"] = asset_id
            if holder["error"]:
                raise ImmichError("nope")
            return holder["asset"]

    mocker.patch("diathek.core.views.ImmichClient", FakeClient)
    return holder


LINK = (
    "https://photos.rixx.de/albums/fb8973c9-6389-4874-807d-3a02173378eb"
    "/photos/1ab444d5-ec2a-4522-8fa1-2cf6788bd760"
)


def _apply(client, image, data, *, version=None):
    if version is None:
        version = image.version
    return client.post(
        reverse("image_apply_immich", args=[image.pk]),
        data=data,
        HTTP_IF_MATCH=str(version),
    )


@pytest.mark.django_db
def test_apply_sets_date_and_coords_and_clears_todos(auth_client, image, fake_asset):
    image.place_todo = True
    image.date_todo = True
    image.save(user=auth_client.user)
    old_version = image.version

    response = _apply(auth_client, image, {"immich_link": LINK})

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.latitude == Decimal("52.520007")
    assert image.longitude == Decimal("13.404954")
    assert image.date_earliest == datetime.date(1987, 6, 15)
    assert image.date_latest == datetime.date(1987, 6, 15)
    assert image.date_precision == "exact"
    assert image.date_display == "1987-06-15"
    assert image.place_todo is False
    assert image.date_todo is False
    assert image.version == old_version + 1
    # the asset id, not the album id, was requested
    assert fake_asset["asset_id"] == "1ab444d5-ec2a-4522-8fa1-2cf6788bd760"


@pytest.mark.django_db
def test_apply_stores_capture_datetime_with_timezone(auth_client, image, fake_asset):
    fake_asset["asset"] = {
        "exifInfo": {
            "dateTimeOriginal": "1987-06-15T12:30:00.000Z",
            "timeZone": "Europe/Berlin",
        }
    }

    _apply(auth_client, image, {"immich_link": LINK})

    image.refresh_from_db()
    assert image.date_earliest == datetime.date(1987, 6, 15)
    assert image.immich_capture_datetime == "1987-06-15T14:30:00+02:00"


@pytest.mark.django_db
def test_apply_clears_stale_capture_datetime_when_time_unusable(
    auth_client, image, fake_asset
):
    image.immich_capture_datetime = "1980-01-01T00:00:00+00:00"
    image.save(user=auth_client.user)
    # Valid day, but the time portion cannot be parsed: no exact time to keep.
    fake_asset["asset"] = {"exifInfo": {"dateTimeOriginal": "1987-06-15T25:99:99Z"}}

    _apply(auth_client, image, {"immich_link": LINK})

    image.refresh_from_db()
    assert image.date_earliest == datetime.date(1987, 6, 15)
    assert image.immich_capture_datetime == ""


@pytest.mark.django_db
def test_apply_writes_audit_log(auth_client, image, fake_asset):
    _apply(auth_client, image, {"immich_link": LINK})

    entry = AuditLog.objects.filter(action_type="image.change").latest("timestamp")
    assert entry.user == auth_client.user
    assert entry.box == image.box
    assert entry.data["after"]["latitude"] == "52.520007"


@pytest.mark.django_db
def test_apply_only_date_leaves_place_todo_untouched(auth_client, image, fake_asset):
    fake_asset["asset"] = {"exifInfo": {"dateTimeOriginal": "1990-01-02T00:00:00Z"}}
    image.place_todo = True
    image.save(user=auth_client.user)

    _apply(auth_client, image, {"immich_link": LINK})

    image.refresh_from_db()
    assert image.date_earliest == datetime.date(1990, 1, 2)
    assert image.has_coords is False
    assert image.place_todo is True  # no location pulled → flag stays


@pytest.mark.django_db
def test_apply_only_coords_leaves_date_untouched(auth_client, image, fake_asset):
    fake_asset["asset"] = {"exifInfo": {"latitude": 1.5, "longitude": 2.5}}

    _apply(auth_client, image, {"immich_link": LINK})

    image.refresh_from_db()
    assert image.latitude == Decimal("1.500000")
    assert image.date_earliest is None


@pytest.mark.django_db
def test_apply_empty_asset_returns_error_fragment(auth_client, image, fake_asset):
    fake_asset["asset"] = {"exifInfo": {}}

    response = _apply(auth_client, image, {"immich_link": LINK})

    assert response.status_code == 400
    assert response["HX-Retarget"] == f"#image-form-{image.pk}"
    assert "weder Datum noch Standort" in response.content.decode()
    image.refresh_from_db()
    assert image.has_coords is False


@pytest.mark.django_db
def test_apply_unparseable_date_returns_error(auth_client, image, fake_asset):
    # Passes the YYYY-MM-DD shape check but is not a real calendar date.
    fake_asset["asset"] = {"exifInfo": {"dateTimeOriginal": "1987-13-45T00:00:00Z"}}

    response = _apply(auth_client, image, {"immich_link": LINK})

    assert response.status_code == 400
    image.refresh_from_db()
    assert image.date_earliest is None


@pytest.mark.django_db
def test_apply_invalid_link_returns_error(auth_client, image, fake_asset):
    response = _apply(auth_client, image, {"immich_link": "https://example.com/foo"})

    assert response.status_code == 400
    assert "Kein gültiger Immich-Link" in response.content.decode()


@pytest.mark.django_db
def test_apply_immich_error_returns_error(auth_client, image, fake_asset):
    fake_asset["error"] = True

    response = _apply(auth_client, image, {"immich_link": LINK})

    assert response.status_code == 400
    assert "konnte nicht geladen werden" in response.content.decode()


@pytest.mark.django_db
def test_apply_without_api_key_returns_error(client, image, fake_asset):
    user = UserFactory(immich_api_key="")
    client.force_login(user)

    response = _apply(client, image, {"immich_link": LINK})

    assert response.status_code == 400
    assert "API-Schlüssel" in response.content.decode()


@pytest.mark.django_db
def test_apply_without_server_configured_returns_error(
    auth_client, image, fake_asset, settings
):
    settings.IMMICH_BASE_URL = ""

    response = _apply(auth_client, image, {"immich_link": LINK})

    assert response.status_code == 400
    assert "Server ist nicht konfiguriert" in response.content.decode()


@pytest.mark.django_db
def test_clear_removes_coords(auth_client, image):
    image.latitude = Decimal("52.5")
    image.longitude = Decimal("13.4")
    image.save(user=auth_client.user)
    old_version = image.version

    response = _apply(auth_client, image, {"clear": "true"})

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.has_coords is False
    assert image.version == old_version + 1


@pytest.mark.django_db
def test_clear_without_coords_is_noop(auth_client, image):
    old_version = image.version

    response = _apply(auth_client, image, {"clear": "true"})

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.version == old_version  # nothing changed → no version bump


@pytest.mark.django_db
def test_apply_requires_if_match_header(auth_client, image, fake_asset):
    response = auth_client.post(
        reverse("image_apply_immich", args=[image.pk]), data={"immich_link": LINK}
    )

    assert response.status_code == 428


@pytest.mark.django_db
def test_apply_invalid_if_match_header(auth_client, image, fake_asset):
    response = auth_client.post(
        reverse("image_apply_immich", args=[image.pk]),
        data={"immich_link": LINK},
        HTTP_IF_MATCH="nope",
    )

    assert response.status_code == 428


@pytest.mark.django_db
def test_apply_version_conflict_returns_409(auth_client, image, fake_asset):
    response = _apply(auth_client, image, {"immich_link": LINK}, version=999)

    assert response.status_code == 409
    assert response["X-Version-Conflict"] == "true"
    image.refresh_from_db()
    assert image.has_coords is False


@pytest.mark.django_db
def test_apply_rejects_archived_box(auth_client, image, fake_asset):
    image.box.archived = True
    image.box.save(user=auth_client.user)

    response = _apply(auth_client, image, {"immich_link": LINK})

    assert response.status_code == 403
    image.refresh_from_db()
    assert image.has_coords is False


@pytest.mark.django_db
def test_apply_returns_404_for_missing_image(auth_client, fake_asset):
    response = auth_client.post(
        reverse("image_apply_immich", args=[999999]),
        data={"immich_link": LINK},
        HTTP_IF_MATCH="1",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_apply_handles_image_deleted_mid_request(auth_client, image, mocker):
    """Cover the race where the row vanishes between validation and locking."""

    class RacingClient:
        def __init__(self, base_url, api_key):
            pass

        def get_asset(self, asset_id):
            Image.objects.filter(pk=image.pk).delete()
            return ASSET_WITH_BOTH

    mocker.patch("diathek.core.views.ImmichClient", RacingClient)

    response = _apply(auth_client, image, {"immich_link": LINK})

    assert response.status_code == 404


@pytest.mark.django_db
def test_apply_requires_login(client, image):
    response = client.post(
        reverse("image_apply_immich", args=[image.pk]),
        data={"immich_link": LINK},
        HTTP_IF_MATCH="1",
    )

    assert response.status_code == 302


@pytest.mark.django_db
def test_apply_rejects_get(auth_client, image):
    response = auth_client.get(reverse("image_apply_immich", args=[image.pk]))

    assert response.status_code == 405


@pytest.mark.django_db
def test_control_rendered_only_with_immich_configured(client, image):
    detail_url = reverse("image_detail", args=[image.box.uuid, image.pk])

    with_key = UserFactory(immich_api_key="api-key-123")
    client.force_login(with_key)
    assert "Aus Immich übernehmen" in client.get(detail_url).content.decode()

    without_key = UserFactory(immich_api_key="")
    client.force_login(without_key)
    assert "Aus Immich übernehmen" not in client.get(detail_url).content.decode()
