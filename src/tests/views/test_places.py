import decimal

import pytest
from django.urls import reverse

from diathek.core.models import Place
from tests.factories import ImageFactory, PlaceFactory, UserFactory

pytestmark = pytest.mark.integration

GOOGLE_URL = (
    "https://www.google.com/maps/place/"
    "49%C2%B032'47.3%22N+8%C2%B038'26.9%22E/"
    "@49.5464765,8.6382401,17z/"
    "data=!3m1!4b1!4m4!3m3!8m2!3d49.546473!4d8.640815"
    "?entry=ttu&g_ep=EgoyMDI2MDQxNS4wIKXMDSoASAFQAw%3D%3D"
)


@pytest.fixture
def auth_client(client):
    user = UserFactory()
    client.force_login(user)
    client.user = user
    return client


@pytest.mark.django_db
def test_place_list_requires_login(client):
    response = client.get(reverse("place_list"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_place_list_empty_state(auth_client):
    response = auth_client.get(reverse("place_list"))

    assert response.status_code == 200
    assert b"Noch keine Orte" in response.content


@pytest.mark.django_db
def test_place_list_shows_places_with_and_without_coords(auth_client):
    PlaceFactory(
        name="Weinheim",
        latitude=decimal.Decimal("49.546473"),
        longitude=decimal.Decimal("8.640815"),
    )
    PlaceFactory(name="Unbekannt")

    response = auth_client.get(reverse("place_list"))

    content = response.content.decode()
    assert "Weinheim" in content
    assert "Unbekannt" in content
    assert "49.546473" in content
    assert "Keine Koordinaten" in content


@pytest.mark.django_db
def test_place_list_sorts_missing_coords_first(auth_client):
    PlaceFactory(
        name="Aachen",
        latitude=decimal.Decimal("50.0"),
        longitude=decimal.Decimal("6.0"),
    )
    PlaceFactory(name="Zwickau")

    response = auth_client.get(reverse("place_list"))

    content = response.content.decode()
    assert content.index("Zwickau") < content.index("Aachen")


@pytest.mark.django_db
def test_place_list_shows_image_count(auth_client):
    place = PlaceFactory(name="Hof")
    ImageFactory(place=place)
    ImageFactory(place=place)

    response = auth_client.get(reverse("place_list"))

    assert b"2 Bilder" in response.content


@pytest.mark.django_db
def test_place_list_shows_nav_link(auth_client):
    response = auth_client.get(reverse("index"))

    assert reverse("place_list").encode() in response.content


@pytest.mark.django_db
def test_set_coords_extracts_from_google_url(auth_client):
    place = PlaceFactory(name="Weinheim")

    response = auth_client.post(
        reverse("place_set_coords", args=[place.pk]),
        {"raw": GOOGLE_URL},
    )

    assert response.status_code == 200
    place.refresh_from_db()
    assert place.latitude == decimal.Decimal("49.546473")
    assert place.longitude == decimal.Decimal("8.640815")


@pytest.mark.django_db
def test_set_coords_accepts_plain_pair(auth_client):
    place = PlaceFactory(name="Hof")

    response = auth_client.post(
        reverse("place_set_coords", args=[place.pk]),
        {"raw": "48.123456, 11.654321"},
    )

    place.refresh_from_db()
    assert response.status_code == 200
    assert place.latitude == decimal.Decimal("48.123456")
    assert place.longitude == decimal.Decimal("11.654321")


@pytest.mark.django_db
def test_set_coords_returns_row_fragment(auth_client):
    place = PlaceFactory(name="Weinheim")

    response = auth_client.post(
        reverse("place_set_coords", args=[place.pk]),
        {"raw": "48.0, 11.0"},
    )

    content = response.content.decode()
    assert content.lstrip().startswith("<li")
    assert f'id="place-{place.pk}"' in content
    assert "48.000000" in content


@pytest.mark.django_db
def test_set_coords_rejects_unparseable_input(auth_client):
    place = PlaceFactory(name="Weinheim")

    response = auth_client.post(
        reverse("place_set_coords", args=[place.pk]),
        {"raw": "nonsense"},
    )

    place.refresh_from_db()
    assert response.status_code == 200
    assert place.latitude is None
    assert b"Konnte keine Koordinaten erkennen" in response.content


@pytest.mark.django_db
def test_set_coords_rejects_empty_input(auth_client):
    place = PlaceFactory(name="Weinheim")

    response = auth_client.post(
        reverse("place_set_coords", args=[place.pk]),
        {"raw": "   "},
    )

    assert response.status_code == 200
    assert b"Bitte einen Link" in response.content


@pytest.mark.django_db
def test_set_coords_requires_login(client):
    place = PlaceFactory(name="Weinheim")

    response = client.post(
        reverse("place_set_coords", args=[place.pk]),
        {"raw": "48.0, 11.0"},
    )

    assert response.status_code == 302
    place.refresh_from_db()
    assert place.latitude is None


@pytest.mark.django_db
def test_set_coords_requires_post(auth_client):
    place = PlaceFactory(name="Weinheim")

    response = auth_client.get(reverse("place_set_coords", args=[place.pk]))

    assert response.status_code == 405


@pytest.mark.django_db
def test_set_coords_is_noop_when_values_unchanged(auth_client):
    place = PlaceFactory(
        name="Weinheim",
        latitude=decimal.Decimal("48.000000"),
        longitude=decimal.Decimal("11.000000"),
    )
    original_version = place.updated_at

    response = auth_client.post(
        reverse("place_set_coords", args=[place.pk]),
        {"raw": "48.0, 11.0"},
    )

    place.refresh_from_db()
    assert response.status_code == 200
    assert place.updated_at == original_version


@pytest.mark.django_db
def test_set_coords_writes_audit_log_on_change(auth_client):
    from diathek.core.models import AuditLog

    place = PlaceFactory(name="Weinheim")

    auth_client.post(
        reverse("place_set_coords", args=[place.pk]),
        {"raw": "48.0, 11.0"},
    )

    entries = AuditLog.objects.filter(action_type="place.change")
    assert entries.count() == 1
    entry = entries.get()
    assert entry.user_id == auth_client.user.pk
    assert entry.data["after"]["latitude"] == "48"
    assert entry.data["after"]["longitude"] == "11"


@pytest.mark.django_db
def test_set_coords_404_for_unknown_place(auth_client):
    response = auth_client.post(
        reverse("place_set_coords", args=[9999]),
        {"raw": "48.0, 11.0"},
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_place_list_shows_map_link_when_coords_present(auth_client):
    PlaceFactory(
        name="Weinheim",
        latitude=decimal.Decimal("49.5"),
        longitude=decimal.Decimal("8.6"),
    )

    response = auth_client.get(reverse("place_list"))

    assert b"google.com/maps" in response.content


@pytest.mark.django_db
def test_place_object_reflects_saved_coords(auth_client):
    place = PlaceFactory(name="Weinheim")

    auth_client.post(
        reverse("place_set_coords", args=[place.pk]),
        {"raw": GOOGLE_URL},
    )

    assert Place.objects.get(pk=place.pk).has_coords
