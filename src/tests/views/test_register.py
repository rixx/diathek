import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from diathek.core.models import InviteCode
from tests.factories import InviteCodeFactory, UserFactory

pytestmark = pytest.mark.integration

User = get_user_model()


@pytest.mark.django_db
def test_register_get_renders_form_with_invite_details(client):
    invite = InviteCodeFactory(username="km", name="Karin Müller")

    response = client.get(reverse("register", kwargs={"code": invite.code}))

    assert response.status_code == 200
    assert b"km" in response.content
    assert "Karin M" in response.content.decode("utf-8")
    assert response.context["invite"] == invite


@pytest.mark.django_db
def test_register_unknown_code_returns_404(client):
    response = client.get(reverse("register", kwargs={"code": "does-not-exist"}))

    assert response.status_code == 404


@pytest.mark.django_db
def test_register_expired_invite_shows_invalid_page(client):
    invite = InviteCodeFactory(expires_at=timezone.now() - dt.timedelta(days=1))

    response = client.get(reverse("register", kwargs={"code": invite.code}))

    assert response.status_code == 410
    assert b"abgelaufen" in response.content


@pytest.mark.django_db
def test_register_used_invite_shows_invalid_page(client):
    existing = UserFactory()
    invite = InviteCodeFactory(used_by=existing, used_at=timezone.now())

    response = client.get(reverse("register", kwargs={"code": invite.code}))

    assert response.status_code == 410
    assert b"verwendet" in response.content


@pytest.mark.django_db
def test_register_post_creates_user_and_logs_in(client):
    invite = InviteCodeFactory(username="km", name="Karin Müller")

    response = client.post(
        reverse("register", kwargs={"code": invite.code}),
        {"password": "verysecurepw9", "password_repeat": "verysecurepw9"},
    )

    assert response.status_code == 302
    assert response.url == "/"
    user = User.objects.get(username="km")
    assert user.name == "Karin Müller"
    assert user.check_password("verysecurepw9")
    invite.refresh_from_db()
    assert invite.used_by == user
    assert invite.used_at is not None
    assert int(client.session["_auth_user_id"]) == user.pk


@pytest.mark.django_db
def test_register_post_password_mismatch_shows_error_and_creates_no_user(client):
    invite = InviteCodeFactory(username="km")

    response = client.post(
        reverse("register", kwargs={"code": invite.code}),
        {"password": "verysecurepw9", "password_repeat": "different-pw-here"},
    )

    assert response.status_code == 200
    assert not User.objects.filter(username="km").exists()
    form = response.context["form"]
    assert "password_repeat" in form.errors


@pytest.mark.django_db
def test_register_post_weak_password_rejected(client):
    invite = InviteCodeFactory(username="km")

    response = client.post(
        reverse("register", kwargs={"code": invite.code}),
        {"password": "123", "password_repeat": "123"},
    )

    assert response.status_code == 200
    assert not User.objects.filter(username="km").exists()
    form = response.context["form"]
    assert "password" in form.errors


@pytest.mark.django_db
def test_register_post_to_used_invite_rejects(client):
    existing = UserFactory()
    invite = InviteCodeFactory(used_by=existing, used_at=timezone.now())

    response = client.post(
        reverse("register", kwargs={"code": invite.code}),
        {"password": "verysecurepw9", "password_repeat": "verysecurepw9"},
    )

    assert response.status_code == 410
    assert User.objects.filter(username=invite.username).count() == 0


@pytest.mark.django_db
def test_login_page_renders(client):
    response = client.get(reverse("login"))

    assert response.status_code == 200
    assert b"Anmelden" in response.content


@pytest.mark.django_db
def test_login_posts_credentials_and_authenticates(client):
    UserFactory(username="km", password="verysecurepw9")

    response = client.post(
        reverse("login"), {"username": "km", "password": "verysecurepw9"}
    )

    assert response.status_code == 302
    assert response.url == "/"
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_invite_created_via_admin_is_usable_end_to_end(client, admin_user):
    client.force_login(admin_user)
    client.post(
        reverse("admin:core_invitecode_add"),
        {
            "username": "td",
            "name": "Tante Doris",
            "expires_at_0": "",
            "expires_at_1": "",
        },
    )
    invite = InviteCode.objects.get(username="td")
    client.logout()

    response = client.post(
        reverse("register", kwargs={"code": invite.code}),
        {"password": "verysecurepw9", "password_repeat": "verysecurepw9"},
    )

    assert response.status_code == 302
    user = User.objects.get(username="td")
    assert user.name == "Tante Doris"
    invite.refresh_from_db()
    assert invite.created_by == admin_user
    assert invite.used_by == user
