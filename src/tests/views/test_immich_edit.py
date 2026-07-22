import uuid

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from diathek.core.immich import ImmichError
from diathek.core.models import ImmichEditSession
from diathek.core.views import _immich_edit_recent_key, _remember_immich_edit_link
from tests.factories import ImmichEditSessionFactory, UserFactory

pytestmark = pytest.mark.integration

ALBUM_ID = "fb8973c9-6389-4874-807d-3a02173378eb"
ALBUM_LINK = f"https://photos.rixx.de/albums/{ALBUM_ID}"
ASSET_ID = "1ab444d5-ec2a-4522-8fa1-2cf6788bd760"
PHOTO_LINK = f"https://photos.rixx.de/photos/{ASSET_ID}"
OTHER_ASSET_ID = "2cb444d5-ec2a-4522-8fa1-2cf6788bd761"

LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


def asset_payload(asset_id, filename, *, date="1987-06-15T12:00:00.000Z"):
    return {
        "id": asset_id,
        "originalFileName": filename,
        "isFavorite": False,
        "visibility": "timeline",
        "exifInfo": {"dateTimeOriginal": date, "description": "Oma"},
    }


class FakeImmich:
    def __init__(self):
        self.assets = {}
        self.albums = {}
        self.album_assets = {}
        self.thumbnails = {}
        self.upload_results = {}
        self.upload_error = None
        self.copy_error = None
        self.update_error = None
        self.delete_error = None
        self.on_delete = None
        self.calls = []
        self.api_keys = []


@pytest.fixture
def immich(mocker):
    fake = FakeImmich()

    class Client:
        def __init__(self, base_url, api_key):
            fake.api_keys.append(api_key)

        def get_asset(self, asset_id):
            fake.calls.append(("get_asset", asset_id))
            payload = fake.assets.get(asset_id)
            if payload is None:
                raise ImmichError("missing", status=404)
            return payload

        def get_album(self, album_id):
            fake.calls.append(("get_album", album_id))
            payload = fake.albums.get(album_id)
            if payload is None:
                raise ImmichError("missing", status=404)
            return payload

        def get_album_assets(self, album_id):
            fake.calls.append(("get_album_assets", album_id))
            return fake.album_assets.get(album_id, [])

        def get_thumbnail(self, asset_id):
            fake.calls.append(("get_thumbnail", asset_id))
            payload = fake.thumbnails.get(asset_id)
            if payload is None:
                raise ImmichError("missing", status=404)
            return payload

        def upload_asset(self, **kwargs):
            fake.calls.append(("upload_asset", kwargs["filename"]))
            if fake.upload_error is not None:
                raise fake.upload_error
            return fake.upload_results.get(
                kwargs["filename"],
                {"id": "new-" + kwargs["filename"], "status": "created"},
            )

        def copy_asset(self, source_id, target_id):
            fake.calls.append(("copy_asset", source_id, target_id))
            if fake.copy_error is not None:
                raise fake.copy_error

        def update_asset(self, asset_id, **fields):
            fake.calls.append(("update_asset", asset_id, fields))
            if fake.update_error is not None:
                raise fake.update_error

        def delete_assets(self, asset_ids):
            fake.calls.append(("delete_assets", list(asset_ids)))
            if fake.on_delete is not None:
                fake.on_delete()
            if fake.delete_error is not None:
                raise fake.delete_error

    mocker.patch("diathek.core.views.ImmichClient", Client)
    return fake


@pytest.fixture
def auth_client(client):
    user = UserFactory(name="Karin", immich_api_key="api-key-123")
    client.force_login(user)
    client.user = user
    return client


@pytest.fixture
def no_key_client(client):
    user = UserFactory(name="Ohne Key")
    client.force_login(user)
    client.user = user
    return client


def make_session(user, items):
    return ImmichEditSessionFactory(user=user, data=items)


def item_payload(filename, source_id, *, metadata=None, state="pending"):
    return {
        "filename": filename,
        "source_asset_id": source_id,
        "source_filename": filename,
        "metadata": {"description": "Oma"} if metadata is None else metadata,
        "item_state": state,
        "new_asset_id": None,
        "error": "",
    }


def post_file(client, session_id, filename="scan_001.jpg", content=b"edited"):
    return client.post(
        reverse("immich_edit_file", args=[session_id]),
        {"file": SimpleUploadedFile(filename, content, "image/jpeg")},
    )


# --- page ---


@pytest.mark.django_db
def test_page_requires_login(client):
    response = client.get(reverse("immich_edit"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_page_shows_blocker_without_api_key(no_key_client):
    response = no_key_client.get(reverse("immich_edit"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "Immich-API-Schlüssel" in body
    assert "immich-edit-form" not in body


@override_settings(IMMICH_BASE_URL="")
@pytest.mark.django_db
def test_page_shows_blocker_without_base_url(auth_client):
    response = auth_client.get(reverse("immich_edit"))

    body = response.content.decode()
    assert "Immich-Server ist nicht konfiguriert" in body
    assert "immich-edit-form" not in body


@pytest.mark.django_db
def test_page_renders_form_when_ready(auth_client):
    response = auth_client.get(reverse("immich_edit"))

    body = response.content.decode()
    assert "immich-edit-form" in body
    assert response.context["blocker"] is None
    assert response.context["recent_links"] == []


@override_settings(CACHES=LOCMEM_CACHE)
@pytest.mark.django_db
def test_page_offers_recent_links_prefilled(auth_client):
    cache.clear()
    _remember_immich_edit_link(auth_client.user, ALBUM_LINK, "Bearbeiten")

    response = auth_client.get(reverse("immich_edit"))

    body = response.content.decode()
    assert response.context["recent_links"] == [
        {"link": ALBUM_LINK, "label": "Bearbeiten"}
    ]
    # the newest link prefills the textarea, the pill carries the album name
    assert f">{ALBUM_LINK}</textarea>" in body
    assert f'data-recent-link="{ALBUM_LINK}"' in body


@override_settings(CACHES=LOCMEM_CACHE)
@pytest.mark.django_db
def test_recent_links_are_user_specific(auth_client):
    cache.clear()
    other = UserFactory(immich_api_key="other-key")
    _remember_immich_edit_link(other, ALBUM_LINK, "Fremdes Album")

    response = auth_client.get(reverse("immich_edit"))

    assert response.context["recent_links"] == []


@override_settings(CACHES=LOCMEM_CACHE)
@pytest.mark.django_db
def test_remember_link_dedupes_and_caps_at_five():
    cache.clear()
    user = UserFactory()
    for n in range(6):
        _remember_immich_edit_link(user, f"link-{n}", f"Album {n}")
    _remember_immich_edit_link(user, "link-3", "Album 3 neu")

    entries = cache.get(_immich_edit_recent_key(user))
    assert [entry["link"] for entry in entries] == [
        "link-3",
        "link-5",
        "link-4",
        "link-2",
        "link-1",
    ]
    assert entries[0]["label"] == "Album 3 neu"


# --- prepare ---


@pytest.mark.django_db
def test_prepare_requires_login(client):
    response = client.post(reverse("immich_edit_prepare"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_prepare_requires_post(auth_client):
    response = auth_client.get(reverse("immich_edit_prepare"))

    assert response.status_code == 405


@pytest.mark.django_db
def test_prepare_rejects_user_without_key(no_key_client):
    response = no_key_client.post(
        reverse("immich_edit_prepare"),
        {"links": ALBUM_LINK, "filenames": ["scan_001.jpg"]},
    )

    assert response.status_code == 403
    assert "Immich-API-Schlüssel" in response.json()["error"]


@pytest.mark.django_db
def test_prepare_rejects_missing_links(auth_client):
    response = auth_client.post(
        reverse("immich_edit_prepare"), {"links": "  \n ", "filenames": ["a.jpg"]}
    )

    assert response.status_code == 400
    assert "Link" in response.json()["error"]


@pytest.mark.django_db
def test_prepare_rejects_missing_filenames(auth_client):
    response = auth_client.post(reverse("immich_edit_prepare"), {"links": ALBUM_LINK})

    assert response.status_code == 400
    assert "Dateinamen" in response.json()["error"]


@pytest.mark.django_db
def test_prepare_rejects_duplicate_filenames(auth_client):
    response = auth_client.post(
        reverse("immich_edit_prepare"),
        {"links": ALBUM_LINK, "filenames": ["a.jpg", "a.jpg", "b.jpg"]},
    )

    assert response.status_code == 400
    assert "Doppelte Dateinamen" in response.json()["error"]
    assert "a.jpg" in response.json()["error"]


@pytest.mark.django_db
def test_prepare_rejects_unparseable_link_line(auth_client, immich):
    response = auth_client.post(
        reverse("immich_edit_prepare"),
        {"links": "https://example.com/kein-link", "filenames": ["a.jpg"]},
    )

    assert response.status_code == 400
    assert "https://example.com/kein-link" in response.json()["error"]
    assert not ImmichEditSession.objects.exists()


@pytest.mark.django_db
def test_prepare_reports_failed_immich_request(auth_client, immich):
    # no assets configured in the fake: the fetch raises ImmichError
    response = auth_client.post(
        reverse("immich_edit_prepare"),
        {"links": PHOTO_LINK, "filenames": ["scan_001.jpg"]},
    )

    assert response.status_code == 400
    assert "Immich" in response.json()["error"]
    assert not ImmichEditSession.objects.exists()


@pytest.mark.django_db
def test_prepare_reports_unknown_album(auth_client, immich):
    response = auth_client.post(
        reverse("immich_edit_prepare"),
        {"links": ALBUM_LINK, "filenames": ["scan_001.jpg"]},
    )

    assert response.status_code == 400
    assert "Immich" in response.json()["error"]
    assert immich.calls == [("get_album", ALBUM_ID)]
    assert not ImmichEditSession.objects.exists()


@pytest.mark.django_db
def test_prepare_matches_album_assets_and_creates_session(auth_client, immich):
    immich.albums[ALBUM_ID] = {"id": ALBUM_ID, "albumName": "Bearbeiten"}
    immich.album_assets[ALBUM_ID] = [
        asset_payload(ASSET_ID, "scan_001.CR2"),
        asset_payload(OTHER_ASSET_ID, "scan_002.jpg"),
    ]

    response = auth_client.post(
        reverse("immich_edit_prepare"),
        {"links": ALBUM_LINK, "filenames": ["scan_001.jpg", "unbekannt.jpg"]},
    )

    assert response.status_code == 200
    payload = response.json()
    session = ImmichEditSession.objects.get()
    assert payload["session_id"] == str(session.pk)
    assert payload["items"] == [
        {
            "filename": "scan_001.jpg",
            "source_filename": "scan_001.CR2",
            "source_date": "1987-06-15",
            "thumbnail_url": reverse("immich_edit_thumbnail", args=[ASSET_ID]),
        }
    ]
    assert payload["unmatched"] == ["unbekannt.jpg"]
    assert payload["ambiguous"] == []

    assert session.user == auth_client.user
    assert session.state == "pending"
    assert session.data == [
        {
            "filename": "scan_001.jpg",
            "source_asset_id": ASSET_ID,
            "source_filename": "scan_001.CR2",
            "metadata": {
                "dateTimeOriginal": "1987-06-15T12:00:00.000Z",
                "description": "Oma",
                "isFavorite": False,
                "visibility": "timeline",
            },
            "item_state": "pending",
            "new_asset_id": None,
            "error": "",
        }
    ]


@pytest.mark.django_db
def test_prepare_accepts_multiple_photo_links(auth_client, immich):
    immich.assets[ASSET_ID] = asset_payload(ASSET_ID, "scan_001.jpg")
    immich.assets[OTHER_ASSET_ID] = asset_payload(OTHER_ASSET_ID, "scan_002.jpg")
    other_link = f"https://photos.rixx.de/photos/{OTHER_ASSET_ID}"

    response = auth_client.post(
        reverse("immich_edit_prepare"),
        {
            "links": f"{PHOTO_LINK}\n{other_link}",
            "filenames": ["scan_001.jpg", "scan_002.jpg"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["filename"] for item in payload["items"]] == [
        "scan_001.jpg",
        "scan_002.jpg",
    ]
    session = ImmichEditSession.objects.get()
    assert [item["source_asset_id"] for item in session.data] == [
        ASSET_ID,
        OTHER_ASSET_ID,
    ]


@pytest.mark.django_db
def test_prepare_reports_ambiguous_matches(auth_client, immich):
    immich.albums[ALBUM_ID] = {"id": ALBUM_ID, "albumName": "Bearbeiten"}
    immich.album_assets[ALBUM_ID] = [
        asset_payload(ASSET_ID, "scan_001.CR2"),
        asset_payload(OTHER_ASSET_ID, "scan_001.jpg"),
        asset_payload("3cb444d5-ec2a-4522-8fa1-2cf6788bd762", "scan_002.jpg"),
    ]

    response = auth_client.post(
        reverse("immich_edit_prepare"),
        {"links": ALBUM_LINK, "filenames": ["scan_001.jpg", "scan_002.jpg"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["filename"] for item in payload["items"]] == ["scan_002.jpg"]
    assert payload["ambiguous"] == ["scan_001.jpg"]


@pytest.mark.django_db
def test_prepare_with_no_matches_creates_no_session(auth_client, immich):
    immich.albums[ALBUM_ID] = {"id": ALBUM_ID, "albumName": "Bearbeiten"}
    immich.album_assets[ALBUM_ID] = [
        asset_payload(ASSET_ID, "scan_002.jpg"),
        asset_payload(OTHER_ASSET_ID, "scan_001.jpg"),
        {"id": "no-name", "originalFileName": ""},
    ]

    response = auth_client.post(
        reverse("immich_edit_prepare"),
        {"links": ALBUM_LINK, "filenames": ["anders.jpg"]},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["unmatched"] == ["anders.jpg"]
    # debug context: the source filenames Immich reported, so a naming
    # mismatch is diagnosable from the error alone
    assert payload["sources"] == ["scan_001.jpg", "scan_002.jpg"]
    assert not ImmichEditSession.objects.exists()


@override_settings(CACHES=LOCMEM_CACHE)
@pytest.mark.django_db
def test_prepare_remembers_album_link_with_name(auth_client, immich):
    cache.clear()
    immich.albums[ALBUM_ID] = {"id": ALBUM_ID, "albumName": "Bearbeiten"}
    immich.album_assets[ALBUM_ID] = [asset_payload(ASSET_ID, "scan_001.jpg")]

    auth_client.post(
        reverse("immich_edit_prepare"),
        {"links": ALBUM_LINK, "filenames": ["scan_001.jpg"]},
    )

    response = auth_client.get(reverse("immich_edit"))
    assert response.context["recent_links"] == [
        {"link": ALBUM_LINK, "label": "Bearbeiten"}
    ]


@override_settings(CACHES=LOCMEM_CACHE)
@pytest.mark.django_db
def test_prepare_does_not_remember_photo_links(auth_client, immich):
    cache.clear()
    immich.assets[ASSET_ID] = asset_payload(ASSET_ID, "scan_001.jpg")

    auth_client.post(
        reverse("immich_edit_prepare"),
        {"links": PHOTO_LINK, "filenames": ["scan_001.jpg"]},
    )

    response = auth_client.get(reverse("immich_edit"))
    assert response.context["recent_links"] == []


# --- thumbnail proxy ---


@pytest.mark.django_db
def test_thumbnail_requires_login(client):
    response = client.get(reverse("immich_edit_thumbnail", args=[ASSET_ID]))

    assert response.status_code == 302


@pytest.mark.django_db
def test_thumbnail_rejects_user_without_key(no_key_client):
    response = no_key_client.get(reverse("immich_edit_thumbnail", args=[ASSET_ID]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_thumbnail_streams_immich_bytes(auth_client, immich):
    immich.thumbnails[ASSET_ID] = (b"webp-bytes", "image/webp")

    response = auth_client.get(reverse("immich_edit_thumbnail", args=[ASSET_ID]))

    assert response.status_code == 200
    assert response.content == b"webp-bytes"
    assert response["Content-Type"] == "image/webp"
    assert immich.api_keys == ["api-key-123"]


@pytest.mark.django_db
def test_thumbnail_returns_502_on_immich_error(auth_client, immich):
    response = auth_client.get(reverse("immich_edit_thumbnail", args=[ASSET_ID]))

    assert response.status_code == 502


# --- per-file processing ---


@pytest.mark.django_db
def test_file_requires_login(client):
    response = client.post(reverse("immich_edit_file", args=[uuid.uuid4()]))

    assert response.status_code == 302


@pytest.mark.django_db
def test_file_rejects_user_without_key(no_key_client):
    response = post_file(no_key_client, uuid.uuid4())

    assert response.status_code == 403


@pytest.mark.django_db
def test_file_rejects_missing_file(auth_client):
    session = make_session(auth_client.user, [item_payload("scan_001.jpg", ASSET_ID)])

    response = auth_client.post(reverse("immich_edit_file", args=[session.pk]), {})

    assert response.status_code == 400


@pytest.mark.django_db
def test_file_rejects_unknown_session(auth_client):
    response = post_file(auth_client, uuid.uuid4())

    assert response.status_code == 404


@pytest.mark.django_db
def test_file_rejects_other_users_session(auth_client):
    other = UserFactory(immich_api_key="other-key")
    session = make_session(other, [item_payload("scan_001.jpg", ASSET_ID)])

    response = post_file(auth_client, session.pk)

    assert response.status_code == 404
    assert ImmichEditSession.objects.filter(pk=session.pk).exists()


@pytest.mark.django_db
def test_file_rejects_filename_not_in_session(auth_client, immich):
    session = make_session(auth_client.user, [item_payload("scan_001.jpg", ASSET_ID)])

    response = post_file(auth_client, session.pk, filename="fremd.jpg")

    assert response.status_code == 400
    assert immich.calls == []


@pytest.mark.django_db
def test_file_runs_replace_pipeline_and_keeps_session_open(auth_client, immich):
    session = make_session(
        auth_client.user,
        [
            item_payload("scan_001.jpg", ASSET_ID),
            item_payload("scan_002.jpg", OTHER_ASSET_ID),
        ],
    )

    response = post_file(auth_client, session.pk)

    assert response.status_code == 200
    assert response.json() == {
        "filename": "scan_001.jpg",
        "state": "done",
        "error": "",
        "completed": False,
        "summary": None,
    }
    # upload → copy relations → re-apply metadata → trash the source
    assert immich.calls == [
        ("upload_asset", "scan_001.jpg"),
        ("copy_asset", ASSET_ID, "new-scan_001.jpg"),
        ("update_asset", "new-scan_001.jpg", {"description": "Oma"}),
        ("delete_assets", [ASSET_ID]),
    ]
    session.refresh_from_db()
    assert session.state == "running"
    assert session.data[0]["item_state"] == "done"
    assert session.data[0]["new_asset_id"] == "new-scan_001.jpg"
    assert session.data[1]["item_state"] == "pending"


@pytest.mark.django_db
def test_file_completion_deletes_session_and_returns_summary(auth_client, immich):
    session = make_session(
        auth_client.user,
        [
            item_payload("scan_001.jpg", ASSET_ID, state="done"),
            item_payload("scan_002.jpg", OTHER_ASSET_ID),
        ],
    )

    response = post_file(auth_client, session.pk, filename="scan_002.jpg")

    assert response.status_code == 200
    assert response.json() == {
        "filename": "scan_002.jpg",
        "state": "done",
        "error": "",
        "completed": True,
        "summary": {"done": 2, "error": 0},
    }
    assert not ImmichEditSession.objects.exists()


@pytest.mark.django_db
def test_file_byte_identical_duplicate_skips_copy_and_trash(auth_client, immich):
    immich.upload_results["scan_001.jpg"] = {"id": ASSET_ID, "status": "duplicate"}
    session = make_session(auth_client.user, [item_payload("scan_001.jpg", ASSET_ID)])

    response = post_file(auth_client, session.pk)

    assert response.json()["state"] == "done"
    assert response.json()["completed"] is True
    assert immich.calls == [("upload_asset", "scan_001.jpg")]


@pytest.mark.django_db
def test_file_skips_metadata_update_when_snapshot_empty(auth_client, immich):
    session = make_session(
        auth_client.user, [item_payload("scan_001.jpg", ASSET_ID, metadata={})]
    )

    response = post_file(auth_client, session.pk)

    assert response.json()["state"] == "done"
    assert immich.calls == [
        ("upload_asset", "scan_001.jpg"),
        ("copy_asset", ASSET_ID, "new-scan_001.jpg"),
        ("delete_assets", [ASSET_ID]),
    ]


@pytest.mark.django_db
def test_file_error_keeps_source_and_continues(auth_client, immich):
    immich.copy_error = ImmichError("copy kaputt", status=500)
    session = make_session(
        auth_client.user,
        [
            item_payload("scan_001.jpg", ASSET_ID),
            item_payload("scan_002.jpg", OTHER_ASSET_ID),
        ],
    )

    response = post_file(auth_client, session.pk)

    payload = response.json()
    assert payload["state"] == "error"
    assert "copy kaputt" in payload["error"]
    assert payload["completed"] is False
    # the source was never trashed
    assert ("delete_assets", [ASSET_ID]) not in immich.calls
    session.refresh_from_db()
    assert session.data[0]["item_state"] == "error"

    # the second file still goes through, and the summary counts the failure
    immich.copy_error = None
    response = post_file(auth_client, session.pk, filename="scan_002.jpg")

    assert response.json()["completed"] is True
    assert response.json()["summary"] == {"done": 1, "error": 1}
    assert not ImmichEditSession.objects.exists()


@pytest.mark.django_db
def test_file_upload_failure_marks_item_and_touches_nothing(auth_client, immich):
    immich.upload_error = ImmichError("upload kaputt", status=500)
    session = make_session(auth_client.user, [item_payload("scan_001.jpg", ASSET_ID)])

    response = post_file(auth_client, session.pk)

    payload = response.json()
    assert payload["state"] == "error"
    assert "upload kaputt" in payload["error"]
    assert immich.calls == [("upload_asset", "scan_001.jpg")]


@pytest.mark.django_db
def test_file_metadata_update_failure_keeps_source(auth_client, immich):
    immich.update_error = ImmichError("update kaputt", status=500)
    session = make_session(auth_client.user, [item_payload("scan_001.jpg", ASSET_ID)])

    response = post_file(auth_client, session.pk)

    assert response.json()["state"] == "error"
    # copy happened, but the source was never trashed
    assert immich.calls == [
        ("upload_asset", "scan_001.jpg"),
        ("copy_asset", ASSET_ID, "new-scan_001.jpg"),
        ("update_asset", "new-scan_001.jpg", {"description": "Oma"}),
    ]


@pytest.mark.django_db
def test_file_trash_failure_is_reported_as_error(auth_client, immich):
    immich.delete_error = ImmichError("trash kaputt", status=500)
    session = make_session(auth_client.user, [item_payload("scan_001.jpg", ASSET_ID)])

    response = post_file(auth_client, session.pk)

    payload = response.json()
    assert payload["state"] == "error"
    assert "trash kaputt" in payload["error"]


@pytest.mark.django_db
def test_file_already_done_item_is_not_reprocessed(auth_client, immich):
    session = make_session(
        auth_client.user,
        [
            item_payload("scan_001.jpg", ASSET_ID, state="done"),
            item_payload("scan_002.jpg", OTHER_ASSET_ID),
        ],
    )

    response = post_file(auth_client, session.pk)

    assert response.json()["state"] == "done"
    assert response.json()["completed"] is False
    assert immich.calls == []
    assert ImmichEditSession.objects.filter(pk=session.pk).exists()


@pytest.mark.django_db
def test_file_session_vanishing_mid_flight_still_reports_result(auth_client, immich):
    session = make_session(auth_client.user, [item_payload("scan_001.jpg", ASSET_ID)])
    # simulate a concurrent completion/prune deleting the row while the
    # Immich requests are in flight
    immich.on_delete = lambda: ImmichEditSession.objects.all().delete()

    response = post_file(auth_client, session.pk)

    assert response.json() == {
        "filename": "scan_001.jpg",
        "state": "done",
        "error": "",
        "completed": True,
        "summary": None,
    }
    assert not ImmichEditSession.objects.exists()
