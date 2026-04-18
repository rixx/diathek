import decimal

import pytest
from django.db import IntegrityError

from diathek.core.models import Place
from tests.factories import ImageFactory, PlaceFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_place_has_coords_true_when_both_set():
    place = PlaceFactory(
        name="Weinheim",
        latitude=decimal.Decimal("49.545"),
        longitude=decimal.Decimal("8.666"),
    )

    assert place.has_coords is True


@pytest.mark.django_db
def test_place_has_coords_false_when_either_missing():
    place = PlaceFactory(name="Nowhere")

    assert place.has_coords is False


@pytest.mark.django_db
def test_place_name_unique():
    PlaceFactory(name="Weinheim")

    with pytest.raises(IntegrityError):
        PlaceFactory(name="Weinheim")


@pytest.mark.django_db
def test_place_recent_orders_by_most_recently_edited_image():
    older = PlaceFactory(name="Alt")
    newer = PlaceFactory(name="Neu")
    unused = PlaceFactory(name="Leer")

    ImageFactory(place=older)
    ImageFactory(place=newer)

    ordered = list(Place.objects.recent())

    assert ordered[0] == newer
    assert ordered[1] == older
    assert ordered[2] == unused


@pytest.mark.django_db
def test_place_recent_respects_limit():
    for i in range(5):
        PlaceFactory(name=f"Place {i}")

    result = list(Place.objects.recent(limit=2))

    assert len(result) == 2
