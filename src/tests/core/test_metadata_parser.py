import datetime

import pytest
from django.http import QueryDict

from diathek.core.metadata import (
    MetadataError,
    parse_batch_payload,
    parse_metadata_payload,
)

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


def test_date_display_derives_earliest_latest_and_precision():
    result = parse_metadata_payload(_qd(date_display="summer 1987"))

    assert result == {
        "date_display": "summer 1987",
        "date_earliest": datetime.date(1987, 6, 1),
        "date_latest": datetime.date(1987, 8, 31),
        "date_precision": "season",
    }


def test_date_display_empty_clears_all_date_fields():
    assert parse_metadata_payload(_qd(date_display="")) == {
        "date_display": "",
        "date_earliest": None,
        "date_latest": None,
        "date_precision": "",
    }


def test_date_display_whitespace_only_clears_fields():
    assert parse_metadata_payload(_qd(date_display="   ")) == {
        "date_display": "",
        "date_earliest": None,
        "date_latest": None,
        "date_precision": "",
    }


def test_date_display_unparseable_raises():
    with pytest.raises(MetadataError, match="Datum"):
        parse_metadata_payload(_qd(date_display="asdfqwer"))


def test_date_display_preserves_verbatim_display_in_result():
    result = parse_metadata_payload(_qd(date_display="Sommer 1987"))

    assert result["date_display"] == "Sommer 1987"


def test_edit_todo_and_description_passed_through_raw():
    result = parse_metadata_payload(_qd(edit_todo="Rot reduzieren", description="ok"))

    assert result == {"edit_todo": "Rot reduzieren", "description": "ok"}


def test_batch_unknown_action_raises():
    with pytest.raises(MetadataError, match="Aktion"):
        parse_batch_payload(_qd(action="nope"))


def test_batch_missing_action_raises():
    with pytest.raises(MetadataError, match="Aktion"):
        parse_batch_payload(_qd())


def test_batch_place_returns_stripped_raw_text():
    action, updates = parse_batch_payload(_qd(action="place", place="  Garten  "))

    assert action == "place"
    assert updates == {"place": "Garten"}


def test_batch_place_missing_field_returns_empty_string():
    # Missing field is treated as an explicit clear, mirroring the single-image
    # save path.
    action, updates = parse_batch_payload(_qd(action="place"))

    assert action == "place"
    assert updates == {"place": ""}


def test_batch_date_display_parses_to_date_fields():
    action, updates = parse_batch_payload(
        _qd(action="date_display", date_display="summer 1987")
    )

    assert action == "date_display"
    assert updates == {
        "date_display": "summer 1987",
        "date_earliest": datetime.date(1987, 6, 1),
        "date_latest": datetime.date(1987, 8, 31),
        "date_precision": "season",
    }


def test_batch_date_display_empty_clears_date_fields():
    action, updates = parse_batch_payload(_qd(action="date_display"))

    assert action == "date_display"
    assert updates == {
        "date_display": "",
        "date_earliest": None,
        "date_latest": None,
        "date_precision": "",
    }


def test_batch_date_display_invalid_raises():
    with pytest.raises(MetadataError, match="Datum"):
        parse_batch_payload(_qd(action="date_display", date_display="asdfqwer"))


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("place_todo", "true", True),
        ("place_todo", "false", False),
        ("date_todo", "1", True),
        ("needs_flip", "0", False),
        ("needs_flip", "", False),
    ),
)
def test_batch_bool_fields(field, value, expected):
    action, updates = parse_batch_payload(_qd(action=field, value=value))

    assert action == field
    assert updates == {field: expected}


def test_batch_bool_invalid_value_raises():
    with pytest.raises(MetadataError, match="Wahrheitswert"):
        parse_batch_payload(_qd(action="place_todo", value="maybe"))


def test_batch_edit_todo_passes_through_text():
    action, updates = parse_batch_payload(
        _qd(action="edit_todo", value="Rot reduzieren")
    )

    assert action == "edit_todo"
    assert updates == {"edit_todo": "Rot reduzieren"}


def test_batch_clear_todos_returns_default_clears():
    action, updates = parse_batch_payload(_qd(action="clear_todos"))

    assert action == "clear_todos"
    assert updates == {
        "place_todo": False,
        "date_todo": False,
        "needs_flip": False,
        "edit_todo": "",
    }
