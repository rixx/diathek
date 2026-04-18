import dataclasses
import datetime

import pytest

from diathek.metadata import dateparse
from diathek.metadata.dateparse import ParseError, parse

pytestmark = pytest.mark.unit


D = datetime.date


def _triple(result):
    return (result.earliest, result.latest, result.precision)


# ---------------------------------------------------------------------------
# Exact dates
# ---------------------------------------------------------------------------


def test_exact_iso_date():
    result = parse("1987-07-15")

    assert _triple(result) == (D(1987, 7, 15), D(1987, 7, 15), "exact")
    assert result.display == "1987-07-15"


def test_exact_german_date_day_dot_month_dot_year():
    result = parse("15.07.1987")

    assert _triple(result) == (D(1987, 7, 15), D(1987, 7, 15), "exact")


def test_exact_iso_with_single_digit_month_and_day():
    assert _triple(parse("1987-7-5")) == (D(1987, 7, 5), D(1987, 7, 5), "exact")


def test_exact_iso_invalid_calendar_date_raises():
    with pytest.raises(ParseError, match="Ungültiges Datum"):
        parse("1987-02-30")


def test_exact_german_invalid_calendar_date_raises():
    with pytest.raises(ParseError, match="Ungültiges Datum"):
        parse("32.13.1987")


# ---------------------------------------------------------------------------
# Plain year
# ---------------------------------------------------------------------------


def test_plain_four_digit_year():
    result = parse("1987")

    assert _triple(result) == (D(1987, 1, 1), D(1987, 12, 31), "year")
    assert result.display == "1987"


@pytest.mark.parametrize(
    ("text", "expected_year"), (("00", 1900), ("89", 1989), ("99", 1999))
)
def test_two_digit_year_always_resolves_to_19xx(text, expected_year):
    result = parse(text)

    assert result.earliest == D(expected_year, 1, 1)
    assert result.latest == D(expected_year, 12, 31)
    assert result.precision == "year"


def test_boundary_year_1900():
    assert _triple(parse("1900")) == (D(1900, 1, 1), D(1900, 12, 31), "year")


def test_boundary_year_2000():
    assert _triple(parse("2000")) == (D(2000, 1, 1), D(2000, 12, 31), "year")


def test_boundary_year_current():
    assert _triple(parse("2026")) == (D(2026, 1, 1), D(2026, 12, 31), "year")


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    (
        "jun 1987",
        "june 1987",
        "juni 1987",
        "Jun 1987",
        "JUN 1987",
        "1987-06",
        "06/1987",
        "06.1987",
        "6/1987",
        "6/87",
        "jun/1987",
        "jun-1987",
        "jun.1987",
    ),
)
def test_month_precision_forms_resolve_to_june_1987(text):
    result = parse(text)

    assert _triple(result) == (D(1987, 6, 1), D(1987, 6, 30), "month")


def test_month_name_with_short_german_mar():
    assert _triple(parse("mär 1987")) == (D(1987, 3, 1), D(1987, 3, 31), "month")


def test_month_name_with_long_german_march():
    assert _triple(parse("märz 1987")) == (D(1987, 3, 1), D(1987, 3, 31), "month")


def test_month_name_with_sept_short_form():
    assert _triple(parse("sept 1987")) == (D(1987, 9, 1), D(1987, 9, 30), "month")


def test_month_iso_february_has_correct_last_day():
    assert _triple(parse("1987-02")) == (D(1987, 2, 1), D(1987, 2, 28), "month")


def test_month_iso_december_hits_year_end():
    assert _triple(parse("1987-12")) == (D(1987, 12, 1), D(1987, 12, 31), "month")


def test_month_num_rejects_month_out_of_range():
    with pytest.raises(ParseError, match="Monat"):
        parse("13/1987")


def test_month_iso_with_invalid_month_falls_through_to_error():
    with pytest.raises(ParseError):
        parse("1987-13")


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ("summer 1987", "sommer 1987", "Sommer 1987"))
def test_summer_1987_resolves_to_june_through_august(text):
    assert _triple(parse(text)) == (D(1987, 6, 1), D(1987, 8, 31), "season")


@pytest.mark.parametrize("text", ("spring 1987", "frühling 1987", "Frühling 1987"))
def test_spring_1987_resolves_to_march_through_may(text):
    assert _triple(parse(text)) == (D(1987, 3, 1), D(1987, 5, 31), "season")


@pytest.mark.parametrize("text", ("autumn 1987", "fall 1987", "herbst 1987"))
def test_autumn_1987_resolves_to_september_through_november(text):
    assert _triple(parse(text)) == (D(1987, 9, 1), D(1987, 11, 30), "season")


def test_winter_1987_spans_into_next_year():
    assert _triple(parse("winter 1987")) == (D(1987, 12, 1), D(1988, 2, 29), "season")


def test_winter_with_two_digit_year_expands_correctly():
    assert _triple(parse("winter 87")) == (D(1987, 12, 1), D(1988, 2, 29), "season")


# ---------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    (
        "1985-1988",
        "1985–1988",
        "1985—1988",
        "1985-88",
        "1985–88",
        "85-88",
        "1985 bis 1988",
        "1985 to 1988",
    ),
)
def test_range_forms_resolve_to_1985_through_1988(text):
    assert _triple(parse(text)) == (D(1985, 1, 1), D(1988, 12, 31), "range")


def test_reversed_range_raises():
    with pytest.raises(ParseError, match="rückwärts"):
        parse("1988-1985")


def test_equal_start_and_end_is_allowed_as_range():
    assert _triple(parse("1987-1987")) == (D(1987, 1, 1), D(1987, 12, 31), "range")


def test_range_second_year_takes_century_from_first():
    # "bis" forces range dispatch; second year (two-digit) inherits first year's century.
    assert _triple(parse("2001 bis 05")) == (D(2001, 1, 1), D(2005, 12, 31), "range")


def test_range_with_four_digit_second_year_in_2000s():
    assert _triple(parse("2001-2005")) == (D(2001, 1, 1), D(2005, 12, 31), "range")


def test_year_hyphen_two_digit_month_resolves_to_month_not_range():
    # "2001-05" is ambiguous; we prefer the month reading (May 2001).
    assert _triple(parse("2001-05")) == (D(2001, 5, 1), D(2001, 5, 31), "month")


# ---------------------------------------------------------------------------
# Fuzzy year
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    (
        "~1987",
        "~ 1987",
        "ca 1987",
        "ca. 1987",
        "circa 1987",
        "etwa 1987",
        "around 1987",
        "approximately 1987",
    ),
)
def test_fuzzy_year_forms_resolve_to_year_1987(text):
    assert _triple(parse(text)) == (D(1987, 1, 1), D(1987, 12, 31), "year")


# ---------------------------------------------------------------------------
# Decades
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ("80s", "1980s", "80er", "1980er"))
def test_plain_decade_spans_whole_decade(text):
    assert _triple(parse(text)) == (D(1980, 1, 1), D(1989, 12, 31), "decade")


@pytest.mark.parametrize(
    "text", ("late 80s", "late 1980s", "spät 80er", "späte 80er", "ende 80er")
)
def test_late_decade_narrows_to_last_three_years(text):
    assert _triple(parse(text)) == (D(1987, 1, 1), D(1989, 12, 31), "decade")


@pytest.mark.parametrize(
    "text", ("early 80s", "früh 80er", "frühe 80er", "anfang 80er")
)
def test_early_decade_narrows_to_first_four_years(text):
    assert _triple(parse(text)) == (D(1980, 1, 1), D(1983, 12, 31), "decade")


@pytest.mark.parametrize("text", ("mid 80s", "mitte 80er"))
def test_mid_decade_narrows_to_middle_years(text):
    assert _triple(parse(text)) == (D(1984, 1, 1), D(1986, 12, 31), "decade")


# ---------------------------------------------------------------------------
# Whitespace, case, determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text", ("Jun 1987", "jun 1987", "  jun 1987 ", "JUN 1987", "jun  1987")
)
def test_case_and_whitespace_variants_produce_identical_parse(text):
    result = parse(text)

    assert _triple(result) == (D(1987, 6, 1), D(1987, 6, 30), "month")


def test_display_standardises_whitespace_and_expands_two_digit_years():
    assert parse("  Jun  1987  ").display == "Jun 1987"
    assert parse("88").display == "1988"
    assert parse("sommer 87").display == "sommer 1987"
    assert parse("Sommer 87").display == "Sommer 1987"
    assert parse("späte 80er").display == "späte 1980er"
    assert parse("85-88").display == "1985-1988"
    assert parse("ca. 87").display == "ca. 1987"
    assert parse("jun 87").display == "jun 1987"
    assert parse("6/87").display == "6/1987"
    assert parse("2001 bis 05").display == "2001 bis 2005"


def test_deterministic_triple_across_equivalent_inputs():
    inputs = ("Jun 1987", "jun 1987", "  jun 1987 ", "JUN 1987", "jun/1987")

    triples = {_triple(parse(text)) for text in inputs}

    assert len(triples) == 1


# ---------------------------------------------------------------------------
# Malformed / empty
# ---------------------------------------------------------------------------


def test_empty_string_raises():
    with pytest.raises(ParseError, match="Leerer"):
        parse("")


def test_whitespace_only_raises():
    with pytest.raises(ParseError, match="Leerer"):
        parse("   \t  ")


def test_none_raises():
    with pytest.raises(ParseError, match="Leerer"):
        parse(None)


@pytest.mark.parametrize(
    "text", ("hello", "nonsense", "0", "1", "198", "abcd", "-", "1987-")
)
def test_unparseable_inputs_raise(text):
    with pytest.raises(ParseError):
        parse(text)


def test_two_digit_pair_hyphenated_is_accepted_as_range():
    assert _triple(parse("19-87")) == (D(1919, 1, 1), D(1987, 12, 31), "range")


# ---------------------------------------------------------------------------
# Word suggestions
# ---------------------------------------------------------------------------


def test_word_suggestions_require_minimum_prefix_length():
    assert dateparse.word_suggestions("j") == []


def test_word_suggestions_match_case_insensitively():
    assert "Juni" in dateparse.word_suggestions("ju")
    assert "Juli" in dateparse.word_suggestions("JU")


def test_word_suggestions_include_seasons():
    assert "Sommer" in dateparse.word_suggestions("so")


def test_word_suggestions_include_fuzzy_markers():
    suggestions = dateparse.word_suggestions("an")

    assert any(s.startswith("Anfang") for s in suggestions)


def test_word_suggestions_empty_prefix_returns_empty():
    assert dateparse.word_suggestions("") == []


def test_word_suggestions_unknown_prefix_returns_empty():
    assert dateparse.word_suggestions("xyz") == []


def test_word_suggestions_respect_limit():
    assert len(dateparse.word_suggestions("j", limit=2)) == 0  # below min length
    assert len(dateparse.word_suggestions("ju", limit=1)) == 1


# ---------------------------------------------------------------------------
# ParsedDate dataclass
# ---------------------------------------------------------------------------


def test_parsed_date_is_frozen():
    result = parse("1987")

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.display = "changed"


# ---------------------------------------------------------------------------
# Interaction: year+month ISO does not misread a year range
# ---------------------------------------------------------------------------


def test_1987_06_is_month_not_range():
    result = parse("1987-06")

    assert result.precision == "month"
    assert result.earliest == D(1987, 6, 1)


def test_1985_88_is_range_not_month():
    result = parse("1985-88")

    assert result.precision == "range"
    assert result.earliest == D(1985, 1, 1)
    assert result.latest == D(1988, 12, 31)
