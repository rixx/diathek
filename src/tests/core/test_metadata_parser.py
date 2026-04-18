import datetime

import pytest
from django.http import QueryDict

from diathek.core.metadata import MetadataError, parse_metadata_payload

pytestmark = pytest.mark.unit


def _qd(**kwargs):
    q = QueryDict(mutable=True)
    for key, value in kwargs.items():
        q[key] = value
    return q


def test_absent_fields_are_omitted_from_updates():
    assert parse_metadata_payload(_qd()) == {}


def test_place_is_not_handled_by_payload_parser():
    # Place resolution requires the acting user for audit attribution and must
    # happen inside the view's transaction — the parser deliberately ignores it.
    assert parse_metadata_payload(_qd(place="Garten")) == {}


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("true", True),
        ("1", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("", False),
    ),
)
def test_bool_parsing_accepts_common_representations(value, expected):
    result = parse_metadata_payload(_qd(place_todo=value))

    assert result == {"place_todo": expected}


def test_bool_parsing_rejects_unknown_value():
    with pytest.raises(MetadataError):
        parse_metadata_payload(_qd(needs_flip="maybe"))


def test_all_boolean_flags_are_handled():
    result = parse_metadata_payload(
        _qd(place_todo="true", date_todo="false", needs_flip="true")
    )

    assert result == {"place_todo": True, "date_todo": False, "needs_flip": True}


def test_date_parses_iso_string():
    result = parse_metadata_payload(_qd(date_earliest="1987-06-01"))

    assert result == {"date_earliest": datetime.date(1987, 6, 1)}


def test_date_latest_also_supported():
    result = parse_metadata_payload(_qd(date_latest="1987-08-31"))

    assert result == {"date_latest": datetime.date(1987, 8, 31)}


def test_empty_date_becomes_none():
    assert parse_metadata_payload(_qd(date_earliest="")) == {"date_earliest": None}


def test_bad_date_raises():
    with pytest.raises(MetadataError):
        parse_metadata_payload(_qd(date_earliest="1987-13-40"))


def test_date_precision_valid_choice_is_passed_through():
    result = parse_metadata_payload(_qd(date_precision="year"))

    assert result == {"date_precision": "year"}


def test_date_precision_empty_is_accepted():
    assert parse_metadata_payload(_qd(date_precision="")) == {"date_precision": ""}


def test_date_precision_invalid_choice_raises():
    with pytest.raises(MetadataError):
        parse_metadata_payload(_qd(date_precision="millennium"))


def test_text_fields_passed_through_raw():
    result = parse_metadata_payload(
        _qd(date_display="summer 1987", edit_todo="Rot reduzieren", description="ok")
    )

    assert result == {
        "date_display": "summer 1987",
        "edit_todo": "Rot reduzieren",
        "description": "ok",
    }
