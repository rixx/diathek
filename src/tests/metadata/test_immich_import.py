from decimal import Decimal

import pytest

from diathek.metadata.immich_import import (
    ImmichMetadata,
    extract_immich_metadata,
    parse_immich_album_id,
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


def test_parse_album_id_from_album_link():
    link = "https://photos.rixx.de/albums/FB8973C9-6389-4874-807d-3a02173378eb"
    assert parse_immich_album_id(link) == "fb8973c9-6389-4874-807d-3a02173378eb"


def test_parse_album_id_also_matches_album_photo_link():
    # A photo-in-album link contains both ids; callers must check for an
    # asset reference first, since that is the more specific one.
    assert parse_immich_album_id(ALBUM_LINK) == "fb8973c9-6389-4874-807d-3a02173378eb"


def test_parse_album_id_rejects_bare_uuid():
    # A bare UUID is indistinguishable from an asset id and stays reserved
    # for parse_immich_asset_id.
    assert parse_immich_album_id("fb8973c9-6389-4874-807d-3a02173378eb") is None


def test_parse_album_id_rejects_empty_and_garbage():
    assert parse_immich_album_id("") is None
    assert parse_immich_album_id("https://photos.rixx.de/albums/not-a-uuid") is None


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
        date="1987-06-15",
        latitude=Decimal("52.520007"),
        longitude=Decimal("13.404954"),
        capture_datetime="1987-06-15T12:00:00+00:00",
    )
    assert not meta.is_empty


def test_extract_keeps_offset_embedded_in_timestamp():
    asset = {"exifInfo": {"dateTimeOriginal": "1987-06-15T14:30:00+02:00"}}

    meta = extract_immich_metadata(asset)

    assert meta.date == "1987-06-15"
    assert meta.capture_datetime == "1987-06-15T14:30:00+02:00"


def test_extract_applies_named_timezone_to_utc_instant():
    # Immich serialises the instant in UTC and keeps the zone separately; the
    # local wall clock is 14:30+02:00, so the local day is still the 15th.
    asset = {
        "exifInfo": {
            "dateTimeOriginal": "1987-06-15T12:30:00.000Z",
            "timeZone": "Europe/Berlin",
        }
    }

    meta = extract_immich_metadata(asset)

    assert meta.date == "1987-06-15"
    assert meta.capture_datetime == "1987-06-15T14:30:00+02:00"


def test_extract_timezone_can_shift_the_local_day():
    # 23:00Z in Berlin (+01:00 in January) is 00:00 the next local day.
    asset = {
        "exifInfo": {
            "dateTimeOriginal": "1990-01-02T23:00:00.000Z",
            "timeZone": "Europe/Berlin",
        }
    }

    meta = extract_immich_metadata(asset)

    assert meta.date == "1990-01-03"
    assert meta.capture_datetime == "1990-01-03T00:00:00+01:00"


def test_extract_accepts_offset_style_timezone():
    asset = {
        "exifInfo": {
            "dateTimeOriginal": "1987-06-15T12:30:00.000Z",
            "timeZone": "UTC+2",
        }
    }

    meta = extract_immich_metadata(asset)

    assert meta.capture_datetime == "1987-06-15T14:30:00+02:00"


def test_extract_accepts_padded_negative_offset_timezone():
    asset = {
        "exifInfo": {
            "dateTimeOriginal": "1987-06-15T12:30:00.000Z",
            "timeZone": "UTC-05:30",
        }
    }

    meta = extract_immich_metadata(asset)

    assert meta.capture_datetime == "1987-06-15T07:00:00-05:30"


def test_extract_plain_utc_timezone_keeps_offset_zero():
    asset = {
        "exifInfo": {"dateTimeOriginal": "1987-06-15T12:30:00.000Z", "timeZone": "UTC"}
    }

    meta = extract_immich_metadata(asset)

    assert meta.capture_datetime == "1987-06-15T12:30:00+00:00"


def test_extract_ignores_unusable_timezone_and_keeps_utc():
    asset = {
        "exifInfo": {
            "dateTimeOriginal": "1987-06-15T12:30:00.000Z",
            "timeZone": "Not/AZone",
        }
    }

    meta = extract_immich_metadata(asset)

    assert meta.capture_datetime == "1987-06-15T12:30:00+00:00"


def test_extract_naive_timestamp_is_treated_as_utc():
    asset = {"exifInfo": {"dateTimeOriginal": "1987-06-15T12:30:00"}}

    meta = extract_immich_metadata(asset)

    assert meta.capture_datetime == "1987-06-15T12:30:00+00:00"


def test_extract_shaped_but_invalid_date_yields_no_capture():
    asset = {"exifInfo": {"dateTimeOriginal": "1987-13-45T00:00:00Z"}}

    meta = extract_immich_metadata(asset)

    assert meta.date == "1987-13-45"
    assert meta.capture_datetime is None


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
