import pytest

from tests.factories import UserFactory


@pytest.fixture
def admin_user(db):
    return UserFactory(username="admin", name="Admin", is_staff=True, is_superuser=True)
