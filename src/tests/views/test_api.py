import json

import pytest
from django.urls import reverse

from diathek.core.models import AuditLog, Place
from tests.factories import BoxFactory, ImageFactory, PlaceFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def api_user(db):
    user = UserFactory(name="Karin")
    user.regenerate_api_token()
    return user


@pytest.fixture
def token(api_user):
    return api_user.api_token


@pytest.fixture
def image(db):
    box = BoxFactory(name="Dachboden")
    return ImageFactory(box=box, filename="1985_strand.jpg", sequence_in_box=1)


def _auth(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _patch(client, image, payload, token):
    return client.patch(
        reverse("api:image-detail", args=[image.pk]),
        data=json.dumps(payload),
        content_type="application/json",
        **_auth(token),
    )


# --- authentication ---------------------------------------------------------


@pytest.mark.django_db
def test_list_requires_authentication(client):
    response = client.get(reverse("api:image-list"))

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Bearer"


@pytest.mark.django_db
def test_auth_via_bearer_header(client, image, token):
    response = client.get(reverse("api:image-list"), **_auth(token))

    assert response.status_code == 200
    assert response.json()["count"] == 1


@pytest.mark.django_db
def test_auth_via_query_parameter(client, image, token):
    response = client.get(reverse("api:image-list"), {"token": token})

    assert response.status_code == 200
    assert response.json()["count"] == 1


@pytest.mark.django_db
def test_invalid_token_is_rejected(client, image):
    response = client.get(reverse("api:image-list"), {"token": "nope"})

    assert response.status_code == 401


@pytest.mark.django_db
def test_token_of_inactive_user_is_rejected(client, image, api_user):
    api_user.is_active = False
    api_user.save()

    response = client.get(reverse("api:image-list"), **_auth(api_user.api_token))

    assert response.status_code == 401


@pytest.mark.django_db
def test_non_bearer_authorization_header_is_ignored(client, image, token):
    response = client.get(
        reverse("api:image-list"), HTTP_AUTHORIZATION=f"Token {token}"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_malformed_bearer_header_without_value_is_ignored(client, image):
    response = client.get(reverse("api:image-list"), HTTP_AUTHORIZATION="Bearer")

    assert response.status_code == 401


@pytest.mark.django_db
def test_non_utf8_authorization_header_is_ignored(client, image):
    response = client.get(reverse("api:image-list"), HTTP_AUTHORIZATION="Bearer \xff")

    assert response.status_code == 401


# --- list & retrieve --------------------------------------------------------


@pytest.mark.django_db
def test_list_exposes_original_filename(client, image, token):
    response = client.get(reverse("api:image-list"), **_auth(token))

    result = response.json()["results"][0]
    assert result["filename"] == "1985_strand.jpg"
    assert result["id"] == image.pk
    assert result["box"] == str(image.box.uuid)
    assert result["place"] is None


@pytest.mark.django_db
def test_list_filter_by_box(client, token):
    box_a = BoxFactory(name="A")
    box_b = BoxFactory(name="B")
    ImageFactory(box=box_a, sequence_in_box=1)
    ImageFactory(box=box_b, sequence_in_box=1)

    response = client.get(
        reverse("api:image-list"), {"box": str(box_a.uuid)}, **_auth(token)
    )

    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["box"] == str(box_a.uuid)


@pytest.mark.django_db
def test_list_filter_by_invalid_box_uuid(client, token):
    response = client.get(
        reverse("api:image-list"), {"box": "not-a-uuid"}, **_auth(token)
    )

    assert response.status_code == 400
    assert "box" in response.json()


@pytest.mark.django_db
def test_list_filter_by_filename(client, token):
    box = BoxFactory()
    ImageFactory(box=box, filename="1985_strand.jpg", sequence_in_box=1)
    ImageFactory(box=box, filename="1990_garten.jpg", sequence_in_box=2)

    response = client.get(
        reverse("api:image-list"), {"filename": "strand"}, **_auth(token)
    )

    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["filename"] == "1985_strand.jpg"


@pytest.mark.django_db
def test_list_page_size_override(client, token):
    box = BoxFactory()
    for n in range(3):
        ImageFactory(box=box, sequence_in_box=n + 1)

    response = client.get(reverse("api:image-list"), {"page_size": "2"}, **_auth(token))

    body = response.json()
    assert body["count"] == 3
    assert len(body["results"]) == 2


@pytest.mark.django_db
def test_retrieve_single_image(client, image, token):
    response = client.get(reverse("api:image-detail", args=[image.pk]), **_auth(token))

    assert response.status_code == 200
    assert response.json()["filename"] == "1985_strand.jpg"


# --- updates ----------------------------------------------------------------


@pytest.mark.django_db
def test_patch_sets_year_from_date_display(client, image, token):
    response = _patch(client, image, {"date_display": "1985"}, token)

    assert response.status_code == 200
    body = response.json()
    assert body["date_precision"] == "year"
    assert body["date_earliest"] == "1985-01-01"
    assert body["date_latest"] == "1985-12-31"
    assert body["date_display"] == "1985"

    image.refresh_from_db()
    assert image.date_earliest.year == 1985


@pytest.mark.django_db
def test_patch_bumps_version_and_writes_audit_log(client, image, token, api_user):
    old_version = image.version

    response = _patch(client, image, {"date_display": "1985"}, token)

    assert response.json()["version"] == old_version + 1
    entry = AuditLog.objects.filter(action_type="image.change").latest("timestamp")
    assert entry.user == api_user
    assert entry.box == image.box
    assert entry.data["after"]["date_display"] == "1985"


@pytest.mark.django_db
def test_patch_resolves_place_by_name_creating_it(client, image, token, api_user):
    response = _patch(client, image, {"place": "Nordsee"}, token)

    assert response.status_code == 200
    assert response.json()["place"] == "Nordsee"
    place = Place.objects.get(name="Nordsee")
    image.refresh_from_db()
    assert image.place == place
    # The new place is attributed to the token's user in the audit log.
    create_entry = AuditLog.objects.get(action_type="place.create")
    assert create_entry.user == api_user


@pytest.mark.django_db
def test_patch_reuses_existing_place_case_insensitively(client, image, token):
    existing = PlaceFactory(name="Nordsee")

    _patch(client, image, {"place": "nordsee"}, token)

    image.refresh_from_db()
    assert image.place == existing
    assert Place.objects.filter(name__iexact="nordsee").count() == 1


@pytest.mark.django_db
def test_patch_empty_place_clears_it(client, token):
    box = BoxFactory()
    place = PlaceFactory(name="Nordsee")
    image = ImageFactory(box=box, place=place, sequence_in_box=1)

    _patch(client, image, {"place": ""}, token)

    image.refresh_from_db()
    assert image.place is None


@pytest.mark.django_db
def test_patch_stamps_description_with_author(client, image, token):
    response = _patch(client, image, {"description": "Strand im Sommer"}, token)

    body = response.json()
    assert "Strand im Sommer" in body["description"]
    assert "Karin" in body["description"]


@pytest.mark.django_db
def test_patch_accepts_boolean_flags(client, image, token):
    response = _patch(client, image, {"needs_flip": True, "place_todo": True}, token)

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.needs_flip is True
    assert image.place_todo is True


@pytest.mark.django_db
def test_put_updates_like_patch(client, image, token):
    response = client.put(
        reverse("api:image-detail", args=[image.pk]),
        data=json.dumps({"date_display": "1985"}),
        content_type="application/json",
        **_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["date_display"] == "1985"


@pytest.mark.django_db
def test_patch_invalid_date_returns_400(client, image, token):
    response = _patch(client, image, {"date_display": "kein datum xyz"}, token)

    assert response.status_code == 400
    image.refresh_from_db()
    assert image.date_display == ""


@pytest.mark.django_db
def test_patch_unknown_image_returns_404(client, token):
    response = client.patch(
        reverse("api:image-detail", args=[9999]),
        data=json.dumps({"date_display": "1985"}),
        content_type="application/json",
        **_auth(token),
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_patch_archived_box_is_forbidden(client, token):
    box = BoxFactory(name="Alt", archived=True)
    image = ImageFactory(box=box, sequence_in_box=1)

    response = _patch(client, image, {"date_display": "1985"}, token)

    assert response.status_code == 403


@pytest.mark.django_db
def test_patch_with_matching_version_succeeds(client, image, token):
    response = _patch(
        client, image, {"date_display": "1985", "version": image.version}, token
    )

    assert response.status_code == 200


@pytest.mark.django_db
def test_patch_with_stale_version_conflicts(client, image, token):
    response = _patch(
        client, image, {"date_display": "1985", "version": image.version - 1}, token
    )

    assert response.status_code == 409
    image.refresh_from_db()
    assert image.date_display == ""


@pytest.mark.django_db
def test_patch_with_non_integer_version_returns_400(client, image, token):
    response = _patch(client, image, {"date_display": "1985", "version": "abc"}, token)

    assert response.status_code == 400
    assert "version" in response.json()


@pytest.mark.django_db
def test_patch_null_value_clears_field(client, token):
    box = BoxFactory()
    image = ImageFactory(box=box, edit_todo="Lightroom", sequence_in_box=1)

    _patch(client, image, {"edit_todo": None}, token)

    image.refresh_from_db()
    assert image.edit_todo == ""


# --- places -----------------------------------------------------------------


@pytest.mark.django_db
def test_places_list(client, token):
    PlaceFactory(name="Nordsee")
    PlaceFactory(name="Alpen")

    response = client.get(reverse("api:place-list"), **_auth(token))

    assert response.status_code == 200
    names = [p["name"] for p in response.json()["results"]]
    assert names == ["Alpen", "Nordsee"]
