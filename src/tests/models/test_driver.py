from datetime import timedelta

import pytest
from django.utils import timezone

from diathek.core.models import DriverState
from tests.factories import UserFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_driver_state_singleton_is_created_by_data_migration():
    assert DriverState.objects.count() == 1
    assert DriverState.get().pk == 1


@pytest.mark.django_db
def test_active_driver_none_when_unset():
    state = DriverState.get()
    state.driver = None
    state.save()

    assert state.active_driver is None


@pytest.mark.django_db
def test_active_driver_none_when_driver_has_never_polled():
    user = UserFactory()
    state = DriverState.get()
    state.driver = user
    state.save()

    assert state.active_driver is None


@pytest.mark.django_db
def test_active_driver_none_when_driver_last_poll_is_stale():
    user = UserFactory(last_poll=timezone.now() - timedelta(seconds=120))
    state = DriverState.get()
    state.driver = user
    state.save()

    assert state.active_driver is None


@pytest.mark.django_db
def test_active_driver_returns_user_when_recently_polled():
    user = UserFactory(last_poll=timezone.now())
    state = DriverState.get()
    state.driver = user
    state.save()

    assert state.active_driver == user
