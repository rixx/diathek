import json

import pytest

from diathek.core.immich import ImmichClient, ImmichError

pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, status=200, data=b"", headers=None):
        self.status = status
        self.data = data
        self.headers = headers or {}


def json_response(payload, status=200):
    return FakeResponse(status=status, data=json.dumps(payload).encode())


@pytest.fixture
def request_mock(mocker):
    pool = mocker.patch("diathek.core.immich.urllib3.PoolManager").return_value
    return pool.request


@pytest.fixture
def client():
    return ImmichClient("https://immich.example.com", "secret-key")


def test_base_url_normalization_strips_trailing_slash():
    client = ImmichClient("https://immich.example.com/", "k")

    assert client.base_url == "https://immich.example.com"
    assert client.api_root == "https://immich.example.com/api"


def test_api_root_has_single_api_segment(client):
    assert client.api_root == "https://immich.example.com/api"


def test_album_web_url_uses_web_root_without_api(client):
    assert (
        client.album_web_url("abc-123") == "https://immich.example.com/albums/abc-123"
    )


def test_request_sends_api_key_header(request_mock, client):
    request_mock.return_value = json_response({"email": "a@b.de"})

    client.verify()

    _, kwargs = request_mock.call_args
    assert kwargs["headers"]["x-api-key"] == "secret-key"
    assert kwargs["headers"]["accept"] == "application/json"


def test_verify_returns_user_dict(request_mock, client):
    request_mock.return_value = json_response({"email": "a@b.de", "name": "Anna"})

    user = client.verify()

    assert user == {"email": "a@b.de", "name": "Anna"}
    args, _ = request_mock.call_args
    assert args == ("GET", "https://immich.example.com/api/users/me")


def test_verify_raises_immich_error_with_status_on_401(request_mock, client):
    request_mock.return_value = FakeResponse(status=401, data=b"unauthorized")

    with pytest.raises(ImmichError) as excinfo:
        client.verify()

    assert excinfo.value.status == 401


def test_error_message_includes_status_and_body(request_mock, client):
    request_mock.return_value = FakeResponse(status=500, data=b"boom details")

    with pytest.raises(ImmichError) as excinfo:
        client.verify()

    message = str(excinfo.value)
    assert "500" in message
    assert "boom details" in message
    assert excinfo.value.status == 500


def test_get_asset_fetches_by_id_and_returns_payload(request_mock, client):
    request_mock.return_value = json_response(
        {"id": "asset-7", "exifInfo": {"dateTimeOriginal": "1990-01-01T00:00:00Z"}}
    )

    asset = client.get_asset("asset-7")

    args, _ = request_mock.call_args
    assert args == ("GET", "https://immich.example.com/api/assets/asset-7")
    assert asset["exifInfo"]["dateTimeOriginal"] == "1990-01-01T00:00:00Z"


def test_bulk_check_posts_assets_body_and_returns_results(request_mock, client):
    request_mock.return_value = json_response(
        {
            "results": [
                {"id": "1", "action": "accept"},
                {"id": "2", "action": "reject", "assetId": "x"},
            ]
        }
    )

    results = client.bulk_check(
        [{"id": "1", "checksum": "aa"}, {"id": "2", "checksum": "bb"}]
    )

    args, kwargs = request_mock.call_args
    assert args == ("POST", "https://immich.example.com/api/assets/bulk-upload-check")
    assert kwargs["headers"]["content-type"] == "application/json"
    assert json.loads(kwargs["body"]) == {
        "assets": [{"id": "1", "checksum": "aa"}, {"id": "2", "checksum": "bb"}]
    }
    assert results == [
        {"id": "1", "action": "accept"},
        {"id": "2", "action": "reject", "assetId": "x"},
    ]


def test_upload_asset_builds_multipart_fields_and_returns_created(request_mock, client):
    request_mock.return_value = json_response({"id": "new-asset", "status": "created"})

    result = client.upload_asset(
        file_bytes=b"\xff\xd8jpeg-bytes",
        filename="slide.jpg",
        device_asset_id="dev-asset-1",
        device_id="diathek",
        file_created_at="2020-01-02T03:04:05.000Z",
        file_modified_at="2020-01-02T03:04:06.000Z",
    )

    args, kwargs = request_mock.call_args
    assert args == ("POST", "https://immich.example.com/api/assets")
    assert "content-type" not in kwargs["headers"]
    assert "x-immich-checksum" not in kwargs["headers"]
    fields = kwargs["fields"]
    assert fields["assetData"] == (
        "slide.jpg",
        b"\xff\xd8jpeg-bytes",
        "application/octet-stream",
    )
    assert fields["deviceAssetId"] == "dev-asset-1"
    assert fields["deviceId"] == "diathek"
    assert fields["fileCreatedAt"] == "2020-01-02T03:04:05.000Z"
    assert fields["fileModifiedAt"] == "2020-01-02T03:04:06.000Z"
    assert result == {"id": "new-asset", "status": "created"}


def test_upload_asset_returns_duplicate_status(request_mock, client):
    request_mock.return_value = json_response({"id": "existing", "status": "duplicate"})

    result = client.upload_asset(
        file_bytes=b"data",
        filename="slide.jpg",
        device_asset_id="dev-asset-1",
        device_id="diathek",
        file_created_at="2020-01-02T03:04:05.000Z",
        file_modified_at="2020-01-02T03:04:06.000Z",
    )

    assert result == {"id": "existing", "status": "duplicate"}


def test_upload_asset_sends_checksum_header_when_provided(request_mock, client):
    request_mock.return_value = json_response({"id": "x", "status": "created"})

    client.upload_asset(
        file_bytes=b"data",
        filename="slide.jpg",
        device_asset_id="dev-asset-1",
        device_id="diathek",
        file_created_at="2020-01-02T03:04:05.000Z",
        file_modified_at="2020-01-02T03:04:06.000Z",
        checksum="abc123",
    )

    _, kwargs = request_mock.call_args
    assert kwargs["headers"]["x-immich-checksum"] == "abc123"


def test_get_or_create_album_returns_existing_without_post(request_mock, client):
    request_mock.return_value = json_response(
        [{"id": "a1", "albumName": "Other"}, {"id": "a2", "albumName": "Urlaub 1990"}]
    )

    album = client.get_or_create_album("Urlaub 1990")

    assert album == {"id": "a2", "albumName": "Urlaub 1990"}
    assert request_mock.call_count == 1
    args, _ = request_mock.call_args
    assert args == ("GET", "https://immich.example.com/api/albums")


def test_get_or_create_album_creates_when_missing(request_mock, client):
    request_mock.side_effect = [
        json_response([{"id": "a1", "albumName": "Other"}]),
        json_response({"id": "new", "albumName": "Urlaub 1990"}),
    ]

    album = client.get_or_create_album("Urlaub 1990")

    assert album == {"id": "new", "albumName": "Urlaub 1990"}
    assert request_mock.call_count == 2
    create_args, create_kwargs = request_mock.call_args_list[1]
    assert create_args == ("POST", "https://immich.example.com/api/albums")
    assert json.loads(create_kwargs["body"]) == {"albumName": "Urlaub 1990"}


def test_add_to_album_posts_ids_and_returns_per_asset_list(request_mock, client):
    request_mock.return_value = json_response(
        [
            {"id": "1", "success": True},
            {"id": "2", "success": False, "error": "duplicate"},
        ]
    )

    result = client.add_to_album("album-9", ["1", "2"])

    args, kwargs = request_mock.call_args
    assert args == ("PUT", "https://immich.example.com/api/albums/album-9/assets")
    assert json.loads(kwargs["body"]) == {"ids": ["1", "2"]}
    assert result == [
        {"id": "1", "success": True},
        {"id": "2", "success": False, "error": "duplicate"},
    ]


def test_request_returns_none_on_empty_body(request_mock, client):
    request_mock.return_value = FakeResponse(status=200, data=b"")

    assert client._request("GET", "/anything") is None


def test_get_album_fetches_by_id_and_returns_payload(request_mock, client):
    request_mock.return_value = json_response(
        {"id": "album-1", "albumName": "Bearbeiten", "assets": [{"id": "a1"}]}
    )

    album = client.get_album("album-1")

    args, _ = request_mock.call_args
    assert args == ("GET", "https://immich.example.com/api/albums/album-1")
    assert album["albumName"] == "Bearbeiten"
    assert album["assets"] == [{"id": "a1"}]


def test_copy_asset_puts_relationship_flags(request_mock, client):
    request_mock.return_value = json_response({"sourceId": "old", "targetId": "new"})

    result = client.copy_asset("old", "new")

    args, kwargs = request_mock.call_args
    assert args == ("PUT", "https://immich.example.com/api/assets/copy")
    assert json.loads(kwargs["body"]) == {
        "sourceId": "old",
        "targetId": "new",
        "albums": True,
        "sharedLinks": True,
        "stack": True,
        "favorite": True,
        "sidecar": True,
    }
    assert result == {"sourceId": "old", "targetId": "new"}


def test_update_asset_puts_given_fields_only(request_mock, client):
    request_mock.return_value = json_response({"id": "new"})

    client.update_asset(
        "new", dateTimeOriginal="1987-06-15T12:00:00.000Z", description="Oma"
    )

    args, kwargs = request_mock.call_args
    assert args == ("PUT", "https://immich.example.com/api/assets/new")
    assert json.loads(kwargs["body"]) == {
        "dateTimeOriginal": "1987-06-15T12:00:00.000Z",
        "description": "Oma",
    }


def test_delete_assets_soft_deletes_without_force(request_mock, client):
    request_mock.return_value = FakeResponse(status=204, data=b"")

    result = client.delete_assets(["old-1", "old-2"])

    args, kwargs = request_mock.call_args
    assert args == ("DELETE", "https://immich.example.com/api/assets")
    assert json.loads(kwargs["body"]) == {"ids": ["old-1", "old-2"], "force": False}
    assert result is None


def test_get_thumbnail_returns_bytes_and_content_type(request_mock, client):
    request_mock.return_value = FakeResponse(
        status=200, data=b"webp-bytes", headers={"content-type": "image/webp"}
    )

    data, content_type = client.get_thumbnail("asset-1")

    args, kwargs = request_mock.call_args
    assert args == ("GET", "https://immich.example.com/api/assets/asset-1/thumbnail")
    assert kwargs["headers"] == {"x-api-key": "secret-key"}
    assert data == b"webp-bytes"
    assert content_type == "image/webp"


def test_get_thumbnail_defaults_content_type(request_mock, client):
    request_mock.return_value = FakeResponse(status=200, data=b"jpeg-bytes")

    data, content_type = client.get_thumbnail("asset-1")

    assert data == b"jpeg-bytes"
    assert content_type == "image/jpeg"


def test_get_thumbnail_raises_immich_error_on_failure(request_mock, client):
    request_mock.return_value = FakeResponse(status=404, data=b"not found")

    with pytest.raises(ImmichError) as excinfo:
        client.get_thumbnail("asset-1")

    assert excinfo.value.status == 404
