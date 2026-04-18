import pytest
from django.urls import reverse

from tests.factories import PlaceFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_client(client):
    client.force_login(UserFactory())
    return client


@pytest.mark.django_db
def test_autocomplete_requires_login(client):
    response = client.get(reverse("place_autocomplete"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_autocomplete_empty_query_lists_all_places_alphabetically(auth_client):
    PlaceFactory(name="Zebra")
    PlaceFactory(name="Anfang")

    response = auth_client.get(reverse("place_autocomplete"))

    assert response.status_code == 200
    names = [entry["name"] for entry in response.json()["results"]]
    assert names == ["Anfang", "Zebra"]


@pytest.mark.django_db
def test_autocomplete_filters_by_icontains(auth_client):
    PlaceFactory(name="Garten")
    PlaceFactory(name="Wohnzimmer")
    PlaceFactory(name="Hintergarten")

    response = auth_client.get(reverse("place_autocomplete") + "?q=garten")

    names = [entry["name"] for entry in response.json()["results"]]
    assert "Garten" in names
    assert "Hintergarten" in names
    assert "Wohnzimmer" not in names


@pytest.mark.django_db
def test_autocomplete_prefers_prefix_matches(auth_client):
    PlaceFactory(name="Hintergarten")
    PlaceFactory(name="Garten")

    response = auth_client.get(reverse("place_autocomplete") + "?q=gar")

    names = [entry["name"] for entry in response.json()["results"]]
    assert names[0] == "Garten"
    assert names[1] == "Hintergarten"


@pytest.mark.django_db
def test_autocomplete_reports_has_coords(auth_client):
    import decimal

    PlaceFactory(
        name="Mit", latitude=decimal.Decimal("49.0"), longitude=decimal.Decimal("8.0")
    )
    PlaceFactory(name="Ohne")

    response = auth_client.get(reverse("place_autocomplete"))

    by_name = {entry["name"]: entry for entry in response.json()["results"]}
    assert by_name["Mit"]["has_coords"] is True
    assert by_name["Ohne"]["has_coords"] is False


@pytest.mark.django_db
def test_autocomplete_limits_results_to_twenty(auth_client):
    for i in range(25):
        PlaceFactory(name=f"Ort {i:02d}")

    response = auth_client.get(reverse("place_autocomplete"))

    assert len(response.json()["results"]) == 20


@pytest.mark.django_db
def test_autocomplete_whitespace_only_query_returns_all(auth_client):
    PlaceFactory(name="Ort")

    response = auth_client.get(reverse("place_autocomplete") + "?q=%20%20")

    names = [entry["name"] for entry in response.json()["results"]]
    assert "Ort" in names
