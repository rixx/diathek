import pytest
from django.urls import reverse

from tests.factories import UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def staff_client(client):
    user = UserFactory(is_staff=True)
    client.force_login(user)
    client.user = user
    return client


@pytest.fixture
def auth_client(client):
    user = UserFactory()
    client.force_login(user)
    client.user = user
    return client


@pytest.mark.django_db
def test_deploy_requires_staff(auth_client):
    response = auth_client.post(reverse("deploy"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_deploy_writes_flag_file(staff_client, tmp_path, settings):
    flag = tmp_path / "deploy.flag"
    settings.DEPLOY_FLAG_FILE = str(flag)

    response = staff_client.post(reverse("deploy"), HTTP_REFERER="/somewhere/")

    assert response.status_code == 302
    assert response.url == "/somewhere/"
    assert flag.exists()
    assert staff_client.user.username in flag.read_text()


@pytest.mark.django_db
def test_deploy_without_configured_flag_file_shows_error(staff_client, settings):
    settings.DEPLOY_FLAG_FILE = ""

    response = staff_client.post(reverse("deploy"))

    assert response.status_code == 302
    assert response.url == reverse("index")


@pytest.mark.django_db
def test_deploy_falls_back_to_index_without_referer(staff_client, tmp_path, settings):
    flag = tmp_path / "nested" / "deploy.flag"
    settings.DEPLOY_FLAG_FILE = str(flag)

    response = staff_client.post(reverse("deploy"))

    assert response.status_code == 302
    assert response.url == reverse("index")
    assert flag.exists()


@pytest.mark.django_db
def test_deploy_button_visible_on_index_for_staff(staff_client, tmp_path, settings):
    settings.DEPLOY_FLAG_FILE = str(tmp_path / "deploy.flag")

    response = staff_client.get(reverse("index"))

    assert b"btn-deploy" in response.content


@pytest.mark.django_db
def test_deploy_button_hidden_for_non_staff(auth_client, tmp_path, settings):
    settings.DEPLOY_FLAG_FILE = str(tmp_path / "deploy.flag")

    response = auth_client.get(reverse("index"))

    assert b"btn-deploy" not in response.content


@pytest.mark.django_db
def test_deploy_button_hidden_when_not_configured(staff_client, settings):
    settings.DEPLOY_FLAG_FILE = ""

    response = staff_client.get(reverse("index"))

    assert b"btn-deploy" not in response.content
