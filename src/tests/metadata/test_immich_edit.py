import pytest

from diathek.metadata.immich_edit import extract_edit_metadata, match_edit_filenames

pytestmark = pytest.mark.unit


def source(asset_id, filename):
    return {"id": asset_id, "originalFileName": filename}


def test_match_pairs_by_exact_filename():
    matched, unmatched, ambiguous = match_edit_filenames(
        ["scan_001.jpg"], [source("a1", "scan_001.jpg")]
    )

    assert matched == {"scan_001.jpg": source("a1", "scan_001.jpg")}
    assert unmatched == []
    assert ambiguous == []


def test_match_ignores_extension_so_raw_finds_jpeg():
    matched, unmatched, ambiguous = match_edit_filenames(
        ["scan_001.jpg"], [source("a1", "scan_001.CR2")]
    )

    assert matched == {"scan_001.jpg": source("a1", "scan_001.CR2")}
    assert unmatched == []
    assert ambiguous == []


def test_match_is_case_insensitive():
    matched, _, _ = match_edit_filenames(
        ["SCAN_001.JPG"], [source("a1", "scan_001.jpg")]
    )

    assert matched == {"SCAN_001.JPG": source("a1", "scan_001.jpg")}


def test_unmatched_filename_is_reported():
    matched, unmatched, ambiguous = match_edit_filenames(
        ["other.jpg"], [source("a1", "scan_001.jpg")]
    )

    assert matched == {}
    assert unmatched == ["other.jpg"]
    assert ambiguous == []


def test_two_distinct_assets_with_same_stem_are_ambiguous():
    matched, unmatched, ambiguous = match_edit_filenames(
        ["scan_001.jpg"], [source("a1", "scan_001.CR2"), source("a2", "scan_001.jpg")]
    )

    assert matched == {}
    assert unmatched == []
    assert ambiguous == ["scan_001.jpg"]


def test_same_asset_listed_twice_is_not_ambiguous():
    # The same photo link pasted twice (or a photo link plus its album) must
    # not block the match.
    matched, unmatched, ambiguous = match_edit_filenames(
        ["scan_001.jpg"], [source("a1", "scan_001.jpg"), source("a1", "scan_001.jpg")]
    )

    assert matched == {"scan_001.jpg": source("a1", "scan_001.jpg")}
    assert unmatched == []
    assert ambiguous == []


def test_sources_without_filename_are_skipped():
    matched, unmatched, _ = match_edit_filenames(
        ["scan_001.jpg"], [{"id": "a1"}, {"id": "a2", "originalFileName": ""}]
    )

    assert matched == {}
    assert unmatched == ["scan_001.jpg"]


def test_extract_edit_metadata_pulls_all_carryover_fields():
    asset = {
        "isFavorite": True,
        "visibility": "timeline",
        "exifInfo": {
            "dateTimeOriginal": "1987-06-15T12:00:00.000Z",
            "description": "Oma im Garten",
            "latitude": 52.52,
            "longitude": 13.4,
            "rating": 4,
        },
    }

    assert extract_edit_metadata(asset) == {
        "dateTimeOriginal": "1987-06-15T12:00:00.000Z",
        "description": "Oma im Garten",
        "latitude": 52.52,
        "longitude": 13.4,
        "rating": 4,
        "isFavorite": True,
        "visibility": "timeline",
    }


def test_extract_edit_metadata_omits_absent_values():
    asset = {"isFavorite": False, "exifInfo": {"description": ""}}

    # False and "" are real values (they must override whatever EXIF the
    # edited file carries); only None/absent fields are dropped.
    assert extract_edit_metadata(asset) == {"description": "", "isFavorite": False}


def test_extract_edit_metadata_handles_missing_exif():
    assert extract_edit_metadata({"exifInfo": None}) == {}
    assert extract_edit_metadata({}) == {}
