import pytest

from diathek.core.models import User

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_user_str_prefers_name_over_username():
    user = User.objects.create_user(
        username="km", name="Karin Müller", password="pw12345678"
    )

    assert str(user) == "Karin Müller"


@pytest.mark.django_db
def test_user_str_falls_back_to_username_when_name_empty():
    user = User.objects.create_user(username="km", password="pw12345678")
    user.name = ""
    user.save()

    assert str(user) == "km"


@pytest.mark.django_db
def test_user_get_full_name_and_short_name_return_display_name():
    user = User.objects.create_user(
        username="km", name="Karin M.", password="pw12345678"
    )

    assert user.get_full_name() == "Karin M."
    assert user.get_short_name() == "Karin M."


@pytest.mark.django_db
def test_create_user_defaults_name_to_username():
    user = User.objects.create_user(username="km", password="pw12345678")

    assert user.name == "km"


@pytest.mark.django_db
def test_create_user_requires_username():
    with pytest.raises(ValueError, match="username is required"):
        User.objects.create_user(username="", password="pw12345678")


@pytest.mark.django_db
def test_create_user_without_password_sets_unusable_password():
    user = User.objects.create_user(username="km")

    assert not user.has_usable_password()


@pytest.mark.django_db
def test_create_superuser_sets_staff_and_superuser_flags():
    user = User.objects.create_superuser(
        username="root", password="pw12345678", name="Root"
    )

    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.check_password("pw12345678")


@pytest.mark.django_db
def test_user_last_poll_defaults_to_null():
    user = User.objects.create_user(username="km", password="pw12345678")

    assert user.last_poll is None
