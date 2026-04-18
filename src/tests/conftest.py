import pytest

from tests.factories import UserFactory


@pytest.fixture
def admin_user(db):
    return UserFactory(username="admin", name="Admin", is_staff=True, is_superuser=True)


@pytest.fixture(autouse=True, scope="session")
def _driver_state_singleton(django_db_setup, django_db_blocker):
    """Provision the DriverState singleton once per test session.

    In production, a data migration creates it at install time. Tests disable
    migrations for speed, so we re-create the row here at session start; the
    data survives per-test transaction rollbacks.
    """
    from diathek.core.models import DriverState

    with django_db_blocker.unblock():
        DriverState.objects.get_or_create(pk=1)
