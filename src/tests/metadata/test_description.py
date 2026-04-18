import datetime

import pytest

from diathek.metadata.description import stamp_description

pytestmark = pytest.mark.unit

TODAY = datetime.date(2026, 4, 18)
STAMP = "[Karin 2026-04-18]"


def test_unchanged_value_returns_as_is():
    assert stamp_description("hello", "hello", "Karin", TODAY) == "hello"


def test_empty_to_empty_returns_empty():
    assert stamp_description("", "", "Karin", TODAY) == ""


def test_first_save_stamps_full_content():
    assert (
        stamp_description("", "Karin am Tisch.", "Karin", TODAY)
        == f"{STAMP} Karin am Tisch."
    )


def test_first_save_strips_leading_whitespace_on_new_content():
    assert stamp_description("", "  \n  Karin.", "Karin", TODAY) == f"{STAMP} Karin."


def test_first_save_with_only_whitespace_returns_raw_value():
    assert stamp_description("", "   ", "Karin", TODAY) == "   "


def test_pure_append_stamps_only_new_portion():
    old = f"{STAMP} Karin am Tisch."
    new = old + "\nHelmut dahinter."
    expected = f"{old}\n[Tobias 2026-04-18] Helmut dahinter."

    assert stamp_description(old, new, "Tobias", TODAY) == expected


def test_pure_append_without_trailing_newline_adds_newline_before_stamp():
    old = "first line"
    new = "first linesecond"
    expected = "first line\n[Tobias 2026-04-18] second"

    assert stamp_description(old, new, "Tobias", TODAY) == expected


def test_append_of_only_whitespace_returns_new_verbatim():
    old = "hello"
    new = "hello   \n"

    assert stamp_description(old, new, "Tobias", TODAY) == "hello   \n"


def test_edit_in_middle_stamps_full_new_value():
    old = "[Karin 2026-04-18] Karin am Tisch."
    new = "[Karin 2026-04-18] Karin am großen Tisch."

    assert (
        stamp_description(new=new, old=old, author_name="Tobias", today=TODAY)
        == f"[Tobias 2026-04-18] {new.lstrip()}"
    )


def test_complete_rewrite_stamps_as_fresh_content():
    old = "old content"
    new = "entirely different"

    assert stamp_description(old, new, "Karin", TODAY) == f"{STAMP} entirely different"
