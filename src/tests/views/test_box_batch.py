import datetime

import pytest
from django.urls import reverse

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
def box(db):
    return BoxFactory(name="Dachboden")


def _post(client, box, data):
    return client.post(reverse("box_batch", args=[box.uuid]), data=data)


@pytest.mark.django_db
def test_batch_requires_login(client, box):
    response = client.post(reverse("box_batch", args=[box.uuid]))

    assert response.status_code == 302


@pytest.mark.django_db
def test_batch_returns_404_for_unknown_box(auth_client):
    response = auth_client.post(
        reverse("box_batch", args=["00000000-0000-0000-0000-000000000000"])
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_batch_rejects_archived_box(auth_client, box):
    box.archived = True
    box.save(user=auth_client.user)
    image = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = _post(
        auth_client,
        box,
        {"action": "place_todo", "value": "true", "image_ids": [image.pk]},
    )

    assert response.status_code == 403
    image.refresh_from_db()
    assert image.place_todo is False


@pytest.mark.django_db
def test_batch_requires_at_least_one_image_id(auth_client, box):
    response = _post(auth_client, box, {"action": "place_todo", "value": "true"})

    assert response.status_code == 400
    assert "Bild" in response.json()["error"]


@pytest.mark.django_db
def test_batch_rejects_non_integer_image_id(auth_client, box):
    response = _post(
        auth_client,
        box,
        {"action": "place_todo", "value": "true", "image_ids": "not-a-number"},
    )

    assert response.status_code == 400
    assert "Bild-ID" in response.json()["error"]


@pytest.mark.django_db
def test_batch_rejects_image_from_different_box(auth_client, box):
    other_box = BoxFactory(name="Andere")
    image = ImageFactory(box=other_box, sequence_in_box=1, filename="a.jpg")

    response = _post(
        auth_client,
        box,
        {"action": "place_todo", "value": "true", "image_ids": [image.pk]},
    )

    assert response.status_code == 400
    assert "gehören nicht" in response.json()["error"]


@pytest.mark.django_db
def test_batch_rejects_unknown_action(auth_client, box):
    image = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = _post(auth_client, box, {"action": "nope", "image_ids": [image.pk]})

    assert response.status_code == 400
    assert "Aktion" in response.json()["error"]


@pytest.mark.django_db
def test_batch_set_place_todo_writes_each_image_and_logs(auth_client, box):
    a = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    b = ImageFactory(box=box, sequence_in_box=2, filename="b.jpg")
    AuditLog.objects.all().delete()

    response = _post(
        auth_client,
        box,
        {"action": "place_todo", "value": "true", "image_ids": [a.pk, b.pk]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"updated": 2, "action": "place_todo"}
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.place_todo is True
    assert b.place_todo is True
    entries = AuditLog.objects.filter(action_type="image.change")
    assert entries.count() == 2
    assert {e.object_id for e in entries} == {a.pk, b.pk}


@pytest.mark.django_db
def test_batch_skips_images_already_at_target_value(auth_client, box):
    a = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", place_todo=True)
    b = ImageFactory(box=box, sequence_in_box=2, filename="b.jpg")
    AuditLog.objects.all().delete()
    a_version = a.version

    response = _post(
        auth_client,
        box,
        {"action": "place_todo", "value": "true", "image_ids": [a.pk, b.pk]},
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 1
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.version == a_version  # untouched, no version bump
    assert b.place_todo is True
    assert AuditLog.objects.filter(object_id=a.pk).count() == 0


@pytest.mark.django_db
def test_batch_apply_place_resolves_or_creates_place(auth_client, box):
    a = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    b = ImageFactory(box=box, sequence_in_box=2, filename="b.jpg")

    response = _post(
        auth_client,
        box,
        {"action": "place", "place": "Neuer Ort", "image_ids": [a.pk, b.pk]},
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 2
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.place is not None
    assert a.place.name == "Neuer Ort"
    assert a.place == b.place
    assert Place.objects.filter(name="Neuer Ort").count() == 1


@pytest.mark.django_db
def test_batch_apply_place_with_existing_name_reuses_row(auth_client, box):
    place = PlaceFactory(name="Garten")
    a = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = _post(
        auth_client, box, {"action": "place", "place": "Garten", "image_ids": [a.pk]}
    )

    assert response.status_code == 200
    a.refresh_from_db()
    assert a.place == place
    assert Place.objects.count() == 1


@pytest.mark.django_db
def test_batch_apply_place_empty_clears_place(auth_client, box):
    place = PlaceFactory(name="Garten")
    a = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", place=place)

    response = _post(
        auth_client, box, {"action": "place", "place": "", "image_ids": [a.pk]}
    )

    assert response.status_code == 200
    a.refresh_from_db()
    assert a.place is None


@pytest.mark.django_db
def test_batch_apply_date_writes_parsed_fields(auth_client, box):
    a = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = _post(
        auth_client,
        box,
        {"action": "date_display", "date_display": "summer 1987", "image_ids": [a.pk]},
    )

    assert response.status_code == 200
    a.refresh_from_db()
    assert a.date_display == "summer 1987"
    assert a.date_earliest == datetime.date(1987, 6, 1)
    assert a.date_latest == datetime.date(1987, 8, 31)
    assert a.date_precision == "season"


@pytest.mark.django_db
def test_batch_apply_date_invalid_returns_400(auth_client, box):
    a = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = _post(
        auth_client,
        box,
        {"action": "date_display", "date_display": "asdfqwer", "image_ids": [a.pk]},
    )

    assert response.status_code == 400
    assert "Datum" in response.json()["error"]
    a.refresh_from_db()
    assert a.date_display == ""


@pytest.mark.django_db
def test_batch_clear_todos_resets_all_four_fields(auth_client, box):
    a = ImageFactory(
        box=box,
        sequence_in_box=1,
        filename="a.jpg",
        place_todo=True,
        date_todo=True,
        needs_flip=True,
        edit_todo="Rot",
    )

    response = _post(auth_client, box, {"action": "clear_todos", "image_ids": [a.pk]})

    assert response.status_code == 200
    a.refresh_from_db()
    assert a.place_todo is False
    assert a.date_todo is False
    assert a.needs_flip is False
    assert a.edit_todo == ""


@pytest.mark.django_db
def test_batch_set_edit_todo_writes_text_value(auth_client, box):
    a = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = _post(
        auth_client,
        box,
        {"action": "edit_todo", "value": "Rot reduzieren", "image_ids": [a.pk]},
    )

    assert response.status_code == 200
    a.refresh_from_db()
    assert a.edit_todo == "Rot reduzieren"


@pytest.mark.django_db
def test_batch_rejects_get_method(auth_client, box):
    response = auth_client.get(reverse("box_batch", args=[box.uuid]))

    assert response.status_code == 405


@pytest.mark.django_db
def test_grid_renders_batch_bar_and_todo_modal_for_active_box(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    content = response.content.decode()
    assert "data-batch-bar" in content
    assert "data-todo-modal" in content
    assert reverse("box_batch", args=[box.uuid]) in content


@pytest.mark.django_db
def test_grid_omits_batch_bar_for_archived_box(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    box.archived = True
    box.save(user=auth_client.user)

    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    content = response.content.decode()
    assert 'class="batch-bar"' not in content
    assert 'class="todo-modal"' not in content
    assert reverse("box_batch", args=[box.uuid]) not in content


@pytest.mark.django_db
def test_detail_renders_todo_modal(auth_client):
    box = BoxFactory(name="Dachboden")
    image = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("image_detail", args=[box.uuid, image.pk]))

    content = response.content.decode()
    assert "data-todo-modal" in content
    assert "Todo-Menü öffnen" in content
