import datetime

import pytest
from django.urls import reverse
from freezegun import freeze_time

from diathek.core.models import AuditLog, Place
from tests.factories import BoxFactory, ImageFactory, PlaceFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def auth_client(client):
    user = UserFactory(name="Karin")
    client.force_login(user)
    client.user = user
    return client


@pytest.fixture
def image(db):
    box = BoxFactory(name="Dachboden")
    return ImageFactory(box=box, filename="scan_001.jpg", sequence_in_box=1)


@pytest.mark.django_db
def test_image_detail_requires_login(client, image):
    response = client.get(reverse("image_detail", args=[image.box.uuid, image.pk]))

    assert response.status_code == 302


@pytest.mark.django_db
def test_image_detail_renders_form_with_current_values(auth_client, image):
    place = PlaceFactory(name="Garten")
    image.place = place
    image.description = "erste Notiz"
    image.save(user=auth_client.user)

    response = auth_client.get(reverse("image_detail", args=[image.box.uuid, image.pk]))

    assert response.status_code == 200
    assert response.context["image"] == image
    assert response.context["box"] == image.box
    assert response.context["position"] == 1
    assert response.context["total"] == 1
    content = response.content.decode()
    assert "erste Notiz" in content
    assert 'value="scan_001.jpg"' not in content  # filename isn't an editable field
    assert "Garten" in content


@pytest.mark.django_db
def test_image_detail_returns_404_for_wrong_box_uuid(auth_client, image):
    other_box = BoxFactory(name="Andere")

    response = auth_client.get(reverse("image_detail", args=[other_box.uuid, image.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_image_detail_redirects_for_archived_box(auth_client, image):
    image.box.archived = True
    image.box.save(user=auth_client.user)

    response = auth_client.get(reverse("image_detail", args=[image.box.uuid, image.pk]))

    assert response.status_code == 302
    assert response.url == reverse("index")


@pytest.mark.django_db
def test_image_detail_shows_prev_and_next_neighbours(auth_client):
    box = BoxFactory()
    first = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    second = ImageFactory(box=box, sequence_in_box=2, filename="b.jpg")
    third = ImageFactory(box=box, sequence_in_box=3, filename="c.jpg")

    response = auth_client.get(reverse("image_detail", args=[box.uuid, second.pk]))

    assert response.context["prev_id"] == first.pk
    assert response.context["next_id"] == third.pk
    assert response.context["position"] == 2
    assert response.context["total"] == 3


@pytest.mark.django_db
def test_image_detail_first_image_has_no_prev(auth_client):
    box = BoxFactory()
    first = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    ImageFactory(box=box, sequence_in_box=2, filename="b.jpg")

    response = auth_client.get(reverse("image_detail", args=[box.uuid, first.pk]))

    assert response.context["prev_id"] is None


def _patch(client, image, data, *, version=None):
    if version is None:
        version = image.version
    return client.generic(
        "PATCH",
        reverse("image_save", args=[image.pk]),
        data="&".join(f"{k}={v}" for k, v in data.items()),
        content_type="application/x-www-form-urlencoded",
        HTTP_IF_MATCH=str(version),
    )


@pytest.mark.django_db
def test_save_updates_simple_field_and_bumps_version(auth_client, image):
    place = PlaceFactory(name="Garten")
    old_version = image.version

    response = _patch(auth_client, image, {"place": place.name})

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.place == place
    assert image.version == old_version + 1


@pytest.mark.django_db
def test_save_writes_audit_log_with_diff(auth_client, image):
    place = PlaceFactory(name="Garten")

    _patch(auth_client, image, {"place": place.name})

    entry = AuditLog.objects.filter(action_type="image.change").latest("timestamp")
    assert entry.user == auth_client.user
    assert entry.box == image.box
    assert entry.data["before"] == {"place": None}
    assert entry.data["after"] == {"place": place.pk}


@pytest.mark.django_db
def test_save_returns_409_on_version_mismatch(auth_client, image):
    response = _patch(auth_client, image, {"place_todo": "true"}, version=999)

    assert response.status_code == 409
    assert response["X-Version-Conflict"] == "true"
    assert response["HX-Reswap"] == "outerHTML"
    image.refresh_from_db()
    assert image.place_todo is False


@pytest.mark.django_db
def test_save_returns_403_for_archived_box(auth_client, image):
    image.box.archived = True
    image.box.save(user=auth_client.user)

    response = _patch(auth_client, image, {"place_todo": "true"})

    assert response.status_code == 403
    image.refresh_from_db()
    assert image.place_todo is False


@pytest.mark.django_db
def test_save_missing_if_match_header_returns_428(auth_client, image):
    response = auth_client.generic(
        "PATCH",
        reverse("image_save", args=[image.pk]),
        data="place_todo=true",
        content_type="application/x-www-form-urlencoded",
    )

    assert response.status_code == 428


@pytest.mark.django_db
def test_save_invalid_if_match_returns_428(auth_client, image):
    response = auth_client.generic(
        "PATCH",
        reverse("image_save", args=[image.pk]),
        data="place_todo=true",
        content_type="application/x-www-form-urlencoded",
        HTTP_IF_MATCH="not-a-number",
    )

    assert response.status_code == 428


@pytest.mark.django_db
def test_save_invalid_payload_returns_400_with_error_fragment(auth_client, image):
    response = _patch(auth_client, image, {"date_display": "nicht lesbar"})

    assert response.status_code == 400
    assert b"Datum" in response.content
    image.refresh_from_db()
    assert image.version == 1


@pytest.mark.django_db
def test_save_noop_when_value_matches_stored(auth_client, image):
    image.place_todo = True
    image.save(user=auth_client.user)
    version_after_true = image.version

    response = _patch(
        auth_client, image, {"place_todo": "true"}, version=version_after_true
    )

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.version == version_after_true


@pytest.mark.django_db
def test_save_description_stamps_new_text(auth_client, image):
    with freeze_time(datetime.datetime(2026, 4, 18, 12, 0, 0)):
        response = auth_client.post(
            reverse("image_save", args=[image.pk]),
            {"description": "Karin hier"},
            HTTP_IF_MATCH=str(image.version),
        )

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.description == "[Karin 2026-04-18] Karin hier"


@pytest.mark.django_db
def test_save_description_appends_with_new_author_stamp(auth_client, image):
    image.description = "[Karin 2026-04-18] erster Eintrag"
    image.save(user=auth_client.user)
    tobias = UserFactory(name="Tobias", username="tobias2")
    auth_client.force_login(tobias)

    with freeze_time(datetime.datetime(2026, 4, 19, 12, 0, 0)):
        response = auth_client.post(
            reverse("image_save", args=[image.pk]),
            {"description": "[Karin 2026-04-18] erster Eintragzweiter Eintrag"},
            HTTP_IF_MATCH=str(image.version),
        )

    assert response.status_code == 200
    image.refresh_from_db()
    assert (
        image.description
        == "[Karin 2026-04-18] erster Eintrag\n[Tobias 2026-04-19] zweiter Eintrag"
    )


@pytest.mark.django_db
def test_save_returns_404_for_missing_image(auth_client):
    response = auth_client.generic(
        "PATCH",
        reverse("image_save", args=[99999]),
        data="place_todo=true",
        content_type="application/x-www-form-urlencoded",
        HTTP_IF_MATCH="1",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_save_rejects_get_and_other_methods(auth_client, image):
    response = auth_client.get(reverse("image_save", args=[image.pk]))

    assert response.status_code == 405


@pytest.mark.django_db
def test_save_accepts_post_for_clients_without_patch(auth_client, image):
    response = auth_client.post(
        reverse("image_save", args=[image.pk]),
        {"place_todo": "true"},
        HTTP_IF_MATCH=str(image.version),
    )

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.place_todo is True


@pytest.mark.django_db
def test_save_creates_new_place_when_name_is_unknown(auth_client, image):
    response = _patch(auth_client, image, {"place": "Neuer Ort"})

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.place is not None
    assert image.place.name == "Neuer Ort"
    assert image.place.latitude is None
    assert image.place.longitude is None
    assert AuditLog.objects.filter(
        action_type="place.create", user=auth_client.user
    ).exists()


@pytest.mark.django_db
def test_save_matches_existing_place_case_insensitively(auth_client, image):
    place = PlaceFactory(name="Garten")

    response = _patch(auth_client, image, {"place": "garten"})

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.place == place
    assert Place.objects.filter(name__iexact="garten").count() == 1


@pytest.mark.django_db
def test_save_empty_place_clears_foreign_key(auth_client, image):
    place = PlaceFactory(name="Garten")
    image.place = place
    image.save(user=auth_client.user)

    response = _patch(auth_client, image, {"place": ""})

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.place is None


@pytest.mark.django_db
def test_save_whitespace_place_is_treated_as_empty(auth_client, image):
    response = _patch(auth_client, image, {"place": "   "})

    assert response.status_code == 200
    image.refresh_from_db()
    assert image.place is None
    assert Place.objects.count() == 0


@pytest.mark.django_db
def test_image_detail_renders_recent_place_pills(auth_client, image):
    recent = PlaceFactory(name="Küche")
    ImageFactory(place=recent)

    response = auth_client.get(reverse("image_detail", args=[image.box.uuid, image.pk]))

    assert response.status_code == 200
    assert recent in response.context["recent_places"]
    content = response.content.decode()
    assert "place-pill" in content
    assert "Küche" in content


@pytest.mark.django_db
def test_image_detail_pill_warns_for_place_without_coords(auth_client, image):
    no_coords = PlaceFactory(name="Ohne Koordinaten")
    ImageFactory(place=no_coords)

    response = auth_client.get(reverse("image_detail", args=[image.box.uuid, image.pk]))

    content = response.content.decode()
    assert "place-pill--no-coords" in content
    assert "Ohne Koordinaten ⚠" in content


@pytest.mark.django_db
def test_fragment_endpoint_renders_current_state(auth_client, image):
    response = auth_client.get(reverse("image_fragment", args=[image.pk]))

    assert response.status_code == 200
    assert response.context["image"] == image
    assert f'data-version="{image.version}"'.encode() in response.content


@pytest.mark.django_db
def test_fragment_endpoint_requires_login(client, image):
    response = client.get(reverse("image_fragment", args=[image.pk]))

    assert response.status_code == 302
