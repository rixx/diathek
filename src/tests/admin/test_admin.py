import pytest
from django.urls import reverse

from diathek.core.models import InviteCode
from tests.factories import InviteCodeFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_invite_changelist_shows_absolute_invite_url(client, admin_user):
    invite = InviteCodeFactory(code="shareable-code")
    client.force_login(admin_user)

    response = client.get(reverse("admin:core_invitecode_changelist"))

    assert response.status_code == 200
    expected_url = f"http://testserver/register/{invite.code}/"
    assert expected_url.encode() in response.content


@pytest.mark.django_db
def test_invite_create_in_admin_sets_created_by(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:core_invitecode_add"),
        {"username": "fm", "name": "Frau M.", "expires_at_0": "", "expires_at_1": ""},
    )

    assert response.status_code == 302
    invite = InviteCode.objects.get(username="fm")
    assert invite.created_by == admin_user
    assert invite.code != ""


@pytest.mark.django_db
def test_invite_edit_in_admin_preserves_created_by(client, admin_user):
    original_creator = UserFactory()
    invite = InviteCodeFactory(created_by=original_creator, name="Old")
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:core_invitecode_change", args=[invite.pk]),
        {
            "username": invite.username,
            "name": "New Name",
            "expires_at_0": "",
            "expires_at_1": "",
        },
    )

    assert response.status_code == 302
    invite.refresh_from_db()
    assert invite.name == "New Name"
    assert invite.created_by == original_creator


@pytest.mark.django_db
def test_user_admin_add_form_accepts_username_and_name(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        reverse("admin:core_user_add"),
        {
            "username": "newbie",
            "name": "Newbie Noob",
            "password1": "verysecurepw9",
            "password2": "verysecurepw9",
        },
    )

    assert response.status_code == 302
    user = admin_user.__class__.objects.get(username="newbie")
    assert user.name == "Newbie Noob"
    assert user.check_password("verysecurepw9")


@pytest.mark.django_db
def test_user_admin_changelist_lists_users(client, admin_user):
    UserFactory(username="km", name="Karin M.")
    client.force_login(admin_user)

    response = client.get(reverse("admin:core_user_changelist"))

    assert response.status_code == 200
    assert b"km" in response.content
    assert "Karin M." in response.content.decode("utf-8")
