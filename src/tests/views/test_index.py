import pytest
from django.urls import reverse

from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_client(client):
    client.force_login(UserFactory())
    return client


@pytest.mark.django_db
def test_index_requires_login(client):
    response = client.get(reverse("index"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_index_lists_active_boxes_and_shows_unsorted_banner(auth_client):
    BoxFactory(name="Dachboden")
    BoxFactory(name="Altarchiv", archived=True)
    ImageFactory(box=None, sequence_in_box=None)

    response = auth_client.get(reverse("index"))

    content = response.content.decode("utf-8")
    assert "Dachboden" in content
    assert "Altarchiv" not in content
    assert "1 unsortierte" in content


@pytest.mark.django_db
def test_index_without_boxes_shows_empty_message(auth_client):
    response = auth_client.get(reverse("index"))

    assert b"Noch keine Boxen" in response.content
