import datetime as dt

import pytest
from django.utils import timezone

from diathek.core.models import InviteCode
from tests.factories import InviteCodeFactory, UserFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_invite_code_auto_generates_code():
    invite = InviteCodeFactory()

    assert invite.code
    assert len(invite.code) >= 16


@pytest.mark.django_db
def test_invite_codes_are_unique():
    codes = {InviteCodeFactory().code for _ in range(5)}

    assert len(codes) == 5


@pytest.mark.django_db
def test_invite_str_includes_username_and_code():
    invite = InviteCodeFactory(username="km")

    assert str(invite) == f"km ({invite.code})"


@pytest.mark.django_db
def test_invite_is_valid_for_fresh_invite():
    invite = InviteCodeFactory()

    assert invite.is_valid is True
    assert invite.is_used is False
    assert invite.is_expired is False


@pytest.mark.django_db
def test_invite_expired_in_past_is_not_valid():
    invite = InviteCodeFactory(expires_at=timezone.now() - dt.timedelta(days=1))

    assert invite.is_expired is True
    assert invite.is_valid is False


@pytest.mark.django_db
def test_invite_expiry_in_future_is_valid():
    invite = InviteCodeFactory(expires_at=timezone.now() + dt.timedelta(days=1))

    assert invite.is_expired is False
    assert invite.is_valid is True


@pytest.mark.django_db
def test_invite_without_expiry_never_expires():
    invite = InviteCodeFactory(expires_at=None)

    assert invite.is_expired is False


@pytest.mark.django_db
def test_invite_mark_used_sets_user_and_timestamp():
    invite = InviteCodeFactory()
    user = UserFactory()

    invite.mark_used(user)

    invite.refresh_from_db()
    assert invite.used_by == user
    assert invite.used_at is not None
    assert invite.is_used is True
    assert invite.is_valid is False


@pytest.mark.django_db
def test_invite_get_absolute_url_points_to_register():
    invite = InviteCodeFactory(code="abc-123")

    assert invite.get_absolute_url() == "/register/abc-123/"


@pytest.mark.django_db
def test_invite_created_at_autoset():
    before = timezone.now()
    invite = InviteCode.objects.create(username="km", name="Karin")
    after = timezone.now()

    assert before <= invite.created_at <= after
