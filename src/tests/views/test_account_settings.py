import pytest
from django.urls import reverse

from diathek.core.immich import ImmichError
from tests.factories import UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_client(client):
    user = UserFactory()
    client.force_login(user)
    client.user = user
    return client


@pytest.mark.django_db
def test_account_settings_requires_login(client):
    response = client.get(reverse("account_settings"))

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_get_renders_form_with_server_url_and_prefilled_key(auth_client, settings):
    settings.IMMICH_BASE_URL = "https://immich.example"
    auth_client.user.immich_api_key = "stored-key"
    auth_client.user.save()

    response = auth_client.get(reverse("account_settings"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Immich-API-Schlüssel" in content
    assert "https://immich.example" in content
    assert 'value="stored-key"' in content


@pytest.mark.django_db
def test_post_valid_key_saves_and_reports_account(auth_client, settings, mocker):
    settings.IMMICH_BASE_URL = "https://immich.example"
    verify = mocker.patch(
        "diathek.core.views.ImmichClient.verify",
        return_value={"email": "user@example.com"},
    )

    response = auth_client.post(
        reverse("account_settings"), {"immich_api_key": "good-key"}
    )

    assert response.status_code == 302
    assert response.url == reverse("account_settings")
    auth_client.user.refresh_from_db()
    assert auth_client.user.immich_api_key == "good-key"
    verify.assert_called_once()
    messages = list(response.wsgi_request._messages)
    assert any("user@example.com" in str(m) for m in messages)


@pytest.mark.django_db
def test_post_valid_key_falls_back_to_name(auth_client, settings, mocker):
    settings.IMMICH_BASE_URL = "https://immich.example"
    mocker.patch("diathek.core.views.ImmichClient.verify", return_value={"name": "Oma"})

    response = auth_client.post(
        reverse("account_settings"), {"immich_api_key": "good-key"}
    )

    assert response.status_code == 302
    messages = list(response.wsgi_request._messages)
    assert any("Oma" in str(m) for m in messages)


@pytest.mark.django_db
def test_post_valid_key_falls_back_to_default_label(auth_client, settings, mocker):
    settings.IMMICH_BASE_URL = "https://immich.example"
    mocker.patch("diathek.core.views.ImmichClient.verify", return_value={})

    response = auth_client.post(
        reverse("account_settings"), {"immich_api_key": "good-key"}
    )

    assert response.status_code == 302
    messages = list(response.wsgi_request._messages)
    assert any("Immich" in str(m) for m in messages)


@pytest.mark.django_db
def test_post_invalid_key_not_saved_and_form_rerendered(auth_client, settings, mocker):
    settings.IMMICH_BASE_URL = "https://immich.example"
    auth_client.user.immich_api_key = "old-key"
    auth_client.user.save()
    mocker.patch(
        "diathek.core.views.ImmichClient.verify",
        side_effect=ImmichError("rejected", status=401),
    )

    response = auth_client.post(
        reverse("account_settings"), {"immich_api_key": "bad-key"}
    )

    assert response.status_code == 200
    auth_client.user.refresh_from_db()
    assert auth_client.user.immich_api_key == "old-key"
    content = response.content.decode()
    assert "abgelehnt" in content
    assert 'value="bad-key"' in content


@pytest.mark.django_db
def test_post_empty_key_clears_existing(auth_client, settings, mocker):
    settings.IMMICH_BASE_URL = "https://immich.example"
    auth_client.user.immich_api_key = "old-key"
    auth_client.user.save()
    verify = mocker.patch("diathek.core.views.ImmichClient.verify")

    response = auth_client.post(reverse("account_settings"), {"immich_api_key": "  "})

    assert response.status_code == 302
    assert response.url == reverse("account_settings")
    auth_client.user.refresh_from_db()
    assert auth_client.user.immich_api_key == ""
    verify.assert_not_called()
    messages = list(response.wsgi_request._messages)
    assert any("entfernt" in str(m) for m in messages)


@pytest.mark.django_db
def test_post_key_without_configured_server_saves_unverified(
    auth_client, settings, mocker
):
    settings.IMMICH_BASE_URL = ""
    verify = mocker.patch("diathek.core.views.ImmichClient.verify")

    response = auth_client.post(
        reverse("account_settings"), {"immich_api_key": "unchecked-key"}
    )

    assert response.status_code == 302
    assert response.url == reverse("account_settings")
    auth_client.user.refresh_from_db()
    assert auth_client.user.immich_api_key == "unchecked-key"
    verify.assert_not_called()
    messages = list(response.wsgi_request._messages)
    assert any("nicht überprüft" in str(m) for m in messages)


@pytest.mark.django_db
def test_post_too_long_key_rerenders_form_without_saving(auth_client, settings, mocker):
    settings.IMMICH_BASE_URL = "https://immich.example"
    auth_client.user.immich_api_key = "old-key"
    auth_client.user.save()
    verify = mocker.patch("diathek.core.views.ImmichClient.verify")

    response = auth_client.post(
        reverse("account_settings"), {"immich_api_key": "x" * 256}
    )

    assert response.status_code == 200
    auth_client.user.refresh_from_db()
    assert auth_client.user.immich_api_key == "old-key"
    verify.assert_not_called()
    assert b"field-error" in response.content


@pytest.mark.django_db
def test_konto_shows_generate_button_when_no_token(auth_client):
    response = auth_client.get(reverse("account_settings"))

    content = response.content.decode()
    assert "Es ist noch kein API-Token hinterlegt." in content
    assert 'name="generate_api_token"' in content


@pytest.mark.django_db
def test_generate_api_token(auth_client):
    response = auth_client.post(
        reverse("account_settings"), {"generate_api_token": "1"}
    )

    assert response.status_code == 302
    auth_client.user.refresh_from_db()
    assert auth_client.user.api_token
    messages = list(response.wsgi_request._messages)
    assert any("Neuer API-Token erzeugt" in str(m) for m in messages)


@pytest.mark.django_db
def test_generate_api_token_replaces_existing(auth_client):
    old = auth_client.user.regenerate_api_token()

    auth_client.post(reverse("account_settings"), {"generate_api_token": "1"})

    auth_client.user.refresh_from_db()
    assert auth_client.user.api_token
    assert auth_client.user.api_token != old


@pytest.mark.django_db
def test_existing_token_is_displayed(auth_client):
    auth_client.user.regenerate_api_token()

    response = auth_client.get(reverse("account_settings"))

    assert auth_client.user.api_token in response.content.decode()


@pytest.mark.django_db
def test_clear_api_token(auth_client):
    auth_client.user.regenerate_api_token()

    response = auth_client.post(reverse("account_settings"), {"clear_api_token": "1"})

    assert response.status_code == 302
    auth_client.user.refresh_from_db()
    assert auth_client.user.api_token is None
    messages = list(response.wsgi_request._messages)
    assert any("entfernt" in str(m) for m in messages)


@pytest.mark.django_db
def test_nav_shows_account_link(auth_client):
    response = auth_client.get(reverse("index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert reverse("account_settings") in content
    assert ">Konto<" in content
