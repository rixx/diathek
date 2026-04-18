import datetime

import pytest
from django.urls import reverse
from freezegun import freeze_time

from diathek.core.models import DriverState
from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.integration

UTC = datetime.UTC


@pytest.fixture
def auth_client(client):
    user = UserFactory(name="Karin", username="karin")
    client.force_login(user)
    client.user = user
    return client


def _set_driver(user, *, polled_at, box=None, image=None):
    user.last_poll = polled_at
    user.save()
    state = DriverState.get()
    state.driver = user
    state.current_box = box
    state.current_image = image
    state.save()
    return state


@pytest.mark.django_db
def test_driver_requires_login(client):
    response = client.post(reverse("driver_state"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_driver_rejects_get(auth_client):
    response = auth_client.get(reverse("driver_state"))

    assert response.status_code == 405


@pytest.mark.django_db
def test_driver_claim_takes_free_seat(auth_client):
    box = BoxFactory(name="Dachboden")
    image = ImageFactory(box=box, filename="a.jpg", sequence_in_box=1)

    response = auth_client.post(
        reverse("driver_state"), {"box_uuid": str(box.uuid), "image_id": str(image.pk)}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["driver"]["user"] == "Karin"
    assert payload["driver"]["image_id"] == image.pk
    assert payload["driver"]["box_uuid"] == str(box.uuid)

    state = DriverState.get()
    assert state.driver_id == auth_client.user.pk
    assert state.current_image_id == image.pk
    assert state.current_box_id == box.pk


@pytest.mark.django_db
def test_driver_claim_reclaims_seat_from_absent_driver(auth_client):
    stale = UserFactory(name="Tobias", username="tobias")
    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        _set_driver(
            stale, polled_at=datetime.datetime(2026, 4, 18, 9, 55, 0, tzinfo=UTC)
        )

    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        response = auth_client.post(reverse("driver_state"))

    assert response.status_code == 200
    assert DriverState.get().driver_id == auth_client.user.pk


@pytest.mark.django_db
def test_driver_claim_rejects_when_present_driver_holds_seat(auth_client):
    other = UserFactory(name="Tobias", username="tobias")
    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        _set_driver(
            other, polled_at=datetime.datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
        )

        response = auth_client.post(reverse("driver_state"))

    assert response.status_code == 409
    payload = response.json()
    assert payload["driver"] == "Tobias"
    assert DriverState.get().driver_id == other.pk


@pytest.mark.django_db
def test_driver_advance_updates_current_image_when_driver(auth_client):
    box = BoxFactory()
    first = ImageFactory(box=box, filename="a.jpg", sequence_in_box=1)
    second = ImageFactory(box=box, filename="b.jpg", sequence_in_box=2)

    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        _set_driver(
            auth_client.user,
            box=box,
            image=first,
            polled_at=datetime.datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC),
        )
        response = auth_client.post(
            reverse("driver_state"),
            {"box_uuid": str(box.uuid), "image_id": str(second.pk)},
        )

    assert response.status_code == 200
    assert DriverState.get().current_image_id == second.pk


@pytest.mark.django_db
def test_driver_claim_without_box_or_image_leaves_those_fields(auth_client):
    box = BoxFactory()
    image = ImageFactory(box=box, filename="a.jpg", sequence_in_box=1)
    state = DriverState.get()
    state.current_box = box
    state.current_image = image
    state.save()

    response = auth_client.post(reverse("driver_state"))

    assert response.status_code == 200
    state.refresh_from_db()
    assert state.driver_id == auth_client.user.pk
    assert state.current_box_id == box.pk
    assert state.current_image_id == image.pk


@pytest.mark.django_db
def test_driver_claim_ignores_unknown_box_uuid(auth_client):
    response = auth_client.post(
        reverse("driver_state"), {"box_uuid": "00000000-0000-0000-0000-000000000000"}
    )

    assert response.status_code == 200
    state = DriverState.get()
    assert state.driver_id == auth_client.user.pk
    assert state.current_box_id is None


@pytest.mark.django_db
def test_driver_claim_ignores_unknown_image_id(auth_client):
    response = auth_client.post(reverse("driver_state"), {"image_id": "999999"})

    assert response.status_code == 200
    assert DriverState.get().current_image_id is None


@pytest.mark.django_db
def test_driver_claim_ignores_non_numeric_image_id(auth_client):
    response = auth_client.post(reverse("driver_state"), {"image_id": "abc"})

    assert response.status_code == 200
    assert DriverState.get().current_image_id is None


@pytest.mark.django_db
def test_driver_release_via_delete(auth_client):
    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        _set_driver(
            auth_client.user,
            polled_at=datetime.datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC),
        )

    response = auth_client.delete(reverse("driver_state"))

    assert response.status_code == 200
    assert response.json()["driver"] is None
    assert DriverState.get().driver_id is None


@pytest.mark.django_db
def test_driver_release_via_post_release_flag(auth_client):
    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        _set_driver(
            auth_client.user,
            polled_at=datetime.datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC),
        )

        response = auth_client.post(reverse("driver_state"), {"release": "true"})

    assert response.status_code == 200
    assert DriverState.get().driver_id is None


@pytest.mark.django_db
def test_driver_release_is_noop_when_not_driver(auth_client):
    other = UserFactory(name="Tobias", username="tobias")
    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        _set_driver(
            other, polled_at=datetime.datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
        )

        response = auth_client.delete(reverse("driver_state"))

    assert response.status_code == 200
    assert DriverState.get().driver_id == other.pk
    assert response.json()["driver"] == {
        "user": "Tobias",
        "box_uuid": None,
        "image_id": None,
    }


@pytest.mark.django_db
def test_driver_bumps_last_poll(auth_client):
    with freeze_time(datetime.datetime(2026, 4, 18, 10, 0, 0)):
        auth_client.post(reverse("driver_state"))

    auth_client.user.refresh_from_db()
    assert auth_client.user.last_poll is not None


@pytest.mark.django_db
def test_driver_rejects_advance_into_archived_box(auth_client):
    box = BoxFactory(archived=True)

    response = auth_client.post(reverse("driver_state"), {"box_uuid": str(box.uuid)})

    assert response.status_code == 403


@pytest.mark.django_db
def test_driver_rejects_advance_to_image_in_archived_box(auth_client):
    box = BoxFactory(archived=True)
    image = ImageFactory(box=box, sequence_in_box=1)

    response = auth_client.post(reverse("driver_state"), {"image_id": str(image.pk)})

    assert response.status_code == 403
