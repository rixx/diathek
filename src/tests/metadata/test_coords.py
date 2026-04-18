from decimal import Decimal

import pytest

from diathek.metadata.coords import parse_coordinates


GOOGLE_URL = (
    "https://www.google.com/maps/place/"
    "49%C2%B032'47.3%22N+8%C2%B038'26.9%22E/"
    "@49.5464765,8.6382401,17z/"
    "data=!3m1!4b1!4m4!3m3!8m2!3d49.546473!4d8.640815"
    "?entry=ttu&g_ep=EgoyMDI2MDQxNS4wIKXMDSoASAFQAw%3D%3D"
)


def test_returns_none_for_empty_string():
    assert parse_coordinates("") is None


def test_returns_none_for_garbage():
    assert parse_coordinates("nope") is None


def test_prefers_pin_coordinates_over_map_centre():
    assert parse_coordinates(GOOGLE_URL) == (
        Decimal("49.546473"),
        Decimal("8.640815"),
    )


def test_falls_back_to_at_centre_when_no_pin():
    url = "https://www.google.com/maps/@49.546478,8.6382401,17z/"

    assert parse_coordinates(url) == (
        Decimal("49.546478"),
        Decimal("8.638240"),
    )


def test_accepts_plain_comma_pair():
    assert parse_coordinates("49.546473, 8.640815") == (
        Decimal("49.546473"),
        Decimal("8.640815"),
    )


def test_accepts_plain_semicolon_pair():
    assert parse_coordinates("49.546473; 8.640815") == (
        Decimal("49.546473"),
        Decimal("8.640815"),
    )


def test_accepts_plain_space_pair():
    assert parse_coordinates("49.546473  8.640815") == (
        Decimal("49.546473"),
        Decimal("8.640815"),
    )


def test_accepts_negative_coordinates():
    assert parse_coordinates("-34.603722, -58.381592") == (
        Decimal("-34.603722"),
        Decimal("-58.381592"),
    )


def test_accepts_integer_coordinates():
    assert parse_coordinates("@10,20,17z") == (
        Decimal("10.000000"),
        Decimal("20.000000"),
    )


def test_rejects_out_of_range_latitude():
    assert parse_coordinates("91.0, 8.0") is None


def test_rejects_out_of_range_longitude():
    assert parse_coordinates("49.0, 181.0") is None


def test_quantizes_to_six_decimal_places():
    lat, lng = parse_coordinates("49.1234567, 8.7654321")

    assert lat.as_tuple().exponent == -6
    assert lng.as_tuple().exponent == -6
    assert (lat, lng) == (Decimal("49.123457"), Decimal("8.765432"))


@pytest.mark.parametrize(
    "text",
    [
        "lat=49,lng=8",
        "49 degrees north",
        "not/coords/!3dabc!4def",
    ],
)
def test_returns_none_for_unparseable_inputs(text):
    assert parse_coordinates(text) is None


def test_at_centre_rejected_when_out_of_range():
    url = "https://www.google.com/maps/@200,8.0,17z/"

    assert parse_coordinates(url) is None
