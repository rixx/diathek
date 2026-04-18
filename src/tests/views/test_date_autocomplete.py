import pytest
from django.urls import reverse

from tests.factories import UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_client(client):
    client.force_login(UserFactory())
    return client


@pytest.mark.django_db
def test_autocomplete_requires_login(client):
    response = client.get(reverse("date_autocomplete"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_empty_query_returns_no_parse_and_no_suggestions(auth_client):
    response = auth_client.get(reverse("date_autocomplete"))

    payload = response.json()
    assert payload == {"parsed": None, "error": None, "suggestions": []}


@pytest.mark.django_db
def test_parseable_query_returns_interpretation(auth_client):
    response = auth_client.get(reverse("date_autocomplete") + "?q=Sommer+1987")

    payload = response.json()
    assert payload["error"] is None
    parsed = payload["parsed"]
    assert parsed["earliest"] == "1987-06-01"
    assert parsed["latest"] == "1987-08-31"
    assert parsed["precision"] == "season"
    assert parsed["precision_label"] == "Saison"
    assert parsed["display"] == "Sommer 1987"


@pytest.mark.django_db
def test_year_query_reports_full_four_digit_year_even_for_two_digit_input(auth_client):
    response = auth_client.get(reverse("date_autocomplete") + "?q=89")

    parsed = response.json()["parsed"]
    assert parsed["summary"] == "1989"
    assert parsed["precision"] == "year"


@pytest.mark.django_db
def test_unparseable_query_returns_error_message(auth_client):
    response = auth_client.get(reverse("date_autocomplete") + "?q=kein+datum")

    payload = response.json()
    assert payload["parsed"] is None
    assert "Datum" in payload["error"]


@pytest.mark.django_db
def test_word_suggestions_returned_for_prefix(auth_client):
    response = auth_client.get(reverse("date_autocomplete") + "?q=so")

    suggestions = response.json()["suggestions"]
    assert "Sommer" in suggestions


@pytest.mark.django_db
def test_exact_date_returns_iso_summary(auth_client):
    response = auth_client.get(reverse("date_autocomplete") + "?q=1987-07-15")

    parsed = response.json()["parsed"]
    assert parsed["summary"] == "1987-07-15"
    assert parsed["precision_label"] == "Tag"


@pytest.mark.django_db
def test_decade_query_reports_span_in_summary(auth_client):
    response = auth_client.get(reverse("date_autocomplete") + "?q=late+80s")

    parsed = response.json()["parsed"]
    assert parsed["summary"] == "1987–1989"
    assert parsed["precision_label"] == "Jahrzehnt"


@pytest.mark.django_db
def test_month_query_reports_month_year_summary(auth_client):
    response = auth_client.get(reverse("date_autocomplete") + "?q=jun+1987")

    parsed = response.json()["parsed"]
    assert parsed["summary"] == "06/1987"
    assert parsed["precision_label"] == "Monat"


@pytest.mark.django_db
def test_range_query_reports_year_span_summary(auth_client):
    response = auth_client.get(reverse("date_autocomplete") + "?q=1985-1988")

    parsed = response.json()["parsed"]
    assert parsed["summary"] == "1985–1988"
    assert parsed["precision_label"] == "Zeitraum"
