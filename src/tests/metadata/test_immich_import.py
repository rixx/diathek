from decimal import Decimal

import pytest

from diathek.metadata.immich_import import (
    ImmichMetadata,
    extract_immich_metadata,
    parse_immich_asset_id,
)

pytestmark = pytest.mark.unit

ALBUM_LINK = (
    "https://photos.rixx.de/albums/fb8973c9-6389-4874-807d-3a02173378eb"
    "/photos/1ab444d5-ec2a-4522-8fa1-2cf6788bd760"
)
DIRECT_LINK = "https://photos.rixx.de/photos/fb87fdc9-e374-4f7c-9e65-3d599024329e"


def test_parse_album_link_returns_asset_not_album_id():
    assert parse_immich_asset_id(ALBUM_LINK) == "1ab444d5-ec2a-4522-8fa1-2cf6788bd760"


def test_parse_direct_photo_link():
    assert parse_immich_asset_id(DIRECT_LINK) == "fb87fdc9-e374-4f7c-9e65-3d599024329e"


def test_parse_link_with_trailing_query_string():
    link = DIRECT_LINK + "?foo=bar"
    assert parse_immich_asset_id(link) == "fb87fdc9-e374-4f7c-9e65-3d599024329e"


def test_parse_bare_uuid_is_accepted_and_lowercased():
    assert (
        parse_immich_asset_id("  FB87FDC9-E374-4F7C-9E65-3D599024329E  ")
        == "fb87fdc9-e374-4f7c-9e65-3d599024329e"
    )


def test_parse_empty_string_returns_none():
    assert parse_immich_asset_id("") is None


def test_parse_garbage_returns_none():
    assert parse_immich_asset_id("https://photos.rixx.de/albums/not-a-uuid") is None


def test_extract_pulls_date_and_coords():
    asset = {
        "exifInfo": {
            "dateTimeOriginal": "1987-06-15T12:00:00.000Z",
            "latitude": 52.5200066,
            "longitude": 13.404954,
        }
    }

    meta = extract_immich_metadata(asset)

    assert meta == ImmichMetadata(
        date="1987-06-15", latitude=Decimal("52.520007"), longitude=Decimal("13.404954")
    )
    assert not meta.is_empty


def test_extract_handles_missing_exif_block():
    meta = extract_immich_metadata({})

    assert meta == ImmichMetadata(date=None, latitude=None, longitude=None)
    assert meta.is_empty


def test_extract_handles_none_asset():
    assert extract_immich_metadata(None).is_empty


def test_extract_ignores_malformed_date():
    meta = extract_immich_metadata({"exifInfo": {"dateTimeOriginal": "irgendwann"}})

    assert meta.date is None


def test_extract_ignores_non_string_date():
    meta = extract_immich_metadata({"exifInfo": {"dateTimeOriginal": 1987}})

    assert meta.date is None


def test_extract_requires_both_coordinates():
    meta = extract_immich_metadata({"exifInfo": {"latitude": 52.5, "longitude": None}})

    assert meta.latitude is None
    assert meta.longitude is None
