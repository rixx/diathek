import datetime

import pytest
from django.urls import reverse
from freezegun import freeze_time

from diathek.core.models import DriverState
from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_client(client):
    user = UserFactory(name="Karin", username="karin")
    client.force_login(user)
    client.user = user
    return client


@pytest.mark.django_db
def test_state_requires_login(client):
    response = client.get(reverse("state"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_state_returns_empty_driver_progress_versions_without_box(auth_client):
    response = auth_client.get(reverse("state"))

    payload = response.json()
    assert payload["driver"] is None
    assert payload["versions"] == {}
    assert payload["progress"] is None
    assert auth_client.user.name in payload["active_users"]


@pytest.mark.django_db
def test_state_reports_versions_and_progress_for_box(auth_client):
    box = BoxFactory(name="Dachboden")
    first = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    second = ImageFactory(box=box, sequence_in_box=2, filename="b.jpg")
    second.place_todo = True
    second.save(user=auth_client.user)

    response = auth_client.get(reverse("state") + f"?box={box.uuid}")

    payload = response.json()
    assert payload["versions"][str(first.pk)] == first.version
    assert payload["versions"][str(second.pk)] == second.version
    assert payload["progress"] == {"total": 2, "tagged": 0, "open_todos": 1}


@pytest.mark.django_db
def test_state_unknown_box_uuid_returns_empty_versions(auth_client):
    response = auth_client.get(
        reverse("state") + "?box=00000000-0000-0000-0000-000000000000"
    )

    payload = response.json()
    assert payload["versions"] == {}
    assert payload["progress"] is None


@pytest.mark.django_db
def test_state_bumps_last_poll_when_stale(auth_client):
    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        auth_client.get(reverse("state"))

    auth_client.user.refresh_from_db()
    initial = auth_client.user.last_poll
    assert initial is not None

    with freeze_time(datetime.datetime(2026, 4, 18, 10, 1, 0)):
        auth_client.get(reverse("state"))

    auth_client.user.refresh_from_db()
    assert auth_client.user.last_poll > initial


@pytest.mark.django_db
def test_state_skips_last_poll_update_within_throttle(auth_client):
    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        auth_client.get(reverse("state"))

    auth_client.user.refresh_from_db()
    initial = auth_client.user.last_poll

    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 10)):
        auth_client.get(reverse("state"))

    auth_client.user.refresh_from_db()
    assert auth_client.user.last_poll == initial


@pytest.mark.django_db
def test_state_reports_active_driver(auth_client):
    driver = UserFactory(name="Tobias", username="tobias")
    box = BoxFactory(name="Dachboden")
    image = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        driver.last_poll = datetime.datetime(2026, 4, 18, 10, 0, 0, tzinfo=datetime.UTC)
        driver.save()
        state_row = DriverState.get()
        state_row.driver = driver
        state_row.current_box = box
        state_row.current_image = image
        state_row.save()

        response = auth_client.get(reverse("state"))

    payload = response.json()
    assert payload["driver"] == {
        "user": "Tobias",
        "box_uuid": str(box.uuid),
        "image_id": image.pk,
    }


@pytest.mark.django_db
def test_state_reports_no_driver_when_driver_is_absent(auth_client):
    driver = UserFactory(name="Tobias", username="tobias", last_poll=None)
    state_row = DriverState.get()
    state_row.driver = driver
    state_row.save()

    response = auth_client.get(reverse("state"))

    payload = response.json()
    assert payload["driver"] is None


@pytest.mark.django_db
def test_state_active_users_only_includes_recently_polling_users(auth_client):
    recent = UserFactory(name="Recent", username="recent")
    old = UserFactory(name="Old", username="old")
    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        recent.last_poll = datetime.datetime(2026, 4, 18, 10, 0, 0, tzinfo=datetime.UTC)
        recent.save()
        old.last_poll = datetime.datetime(2026, 4, 18, 9, 0, 0, tzinfo=datetime.UTC)
        old.save()

        response = auth_client.get(reverse("state"))

    payload = response.json()
    assert "Recent" in payload["active_users"]
    assert "Old" not in payload["active_users"]


@pytest.mark.django_db
def test_state_driver_payload_handles_box_and_image_none(auth_client):
    driver = UserFactory(name="Tobias", username="tobias")
    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        driver.last_poll = datetime.datetime(2026, 4, 18, 10, 0, 0, tzinfo=datetime.UTC)
        driver.save()
        state_row = DriverState.get()
        state_row.driver = driver
        state_row.current_box = None
        state_row.current_image = None
        state_row.save()

        response = auth_client.get(reverse("state"))

    assert response.json()["driver"] == {
        "user": "Tobias",
        "box_uuid": None,
        "image_id": None,
    }


@pytest.mark.django_db
def test_state_driver_falls_back_to_username_when_name_blank(auth_client):
    driver = UserFactory(name="", username="tobias")
    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        driver.last_poll = datetime.datetime(2026, 4, 18, 10, 0, 0, tzinfo=datetime.UTC)
        driver.save()
        state_row = DriverState.get()
        state_row.driver = driver
        state_row.save()

        response = auth_client.get(reverse("state"))

    assert response.json()["driver"]["user"] == "tobias"


@pytest.mark.django_db
def test_state_blank_box_param_is_treated_as_no_box(auth_client):
    response = auth_client.get(reverse("state") + "?box=")

    payload = response.json()
    assert payload["versions"] == {}
    assert payload["progress"] is None
