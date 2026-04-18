import datetime

import pytest
from django.urls import reverse

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


@pytest.mark.django_db
def test_grid_requires_login(client, box):
    response = client.get(reverse("box_grid", args=[box.uuid]))

    assert response.status_code == 302


@pytest.mark.django_db
def test_grid_returns_404_for_missing_box(auth_client):
    response = auth_client.get(
        reverse("box_grid", args=["00000000-0000-0000-0000-000000000000"])
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_grid_renders_all_images_by_default(auth_client, box):
    first = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    second = ImageFactory(box=box, sequence_in_box=2, filename="b.jpg")

    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    assert response.status_code == 200
    images = list(response.context["images"])
    assert images == [first, second]
    assert response.context["active_filter"] == "all"
    assert response.context["total_count"] == 2
    content = response.content.decode()
    assert reverse("image_detail", args=[box.uuid, first.pk]) in content
    assert "Dachboden" in content


@pytest.mark.django_db
def test_grid_empty_box_shows_placeholder(auth_client, box):
    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    assert response.status_code == 200
    assert list(response.context["images"]) == []
    assert response.context["total_count"] == 0
    assert "Keine Bilder passen zu diesem Filter." in response.content.decode()


@pytest.mark.django_db
def test_grid_filter_untagged_excludes_tagged_images(auth_client, box):
    untagged = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    place = PlaceFactory(name="Garten")
    tagged = ImageFactory(box=box, sequence_in_box=2, filename="b.jpg", place=place)
    tagged_by_date = ImageFactory(
        box=box,
        sequence_in_box=3,
        filename="c.jpg",
        date_earliest=datetime.date(1987, 1, 1),
        date_latest=datetime.date(1987, 12, 31),
    )

    response = auth_client.get(
        reverse("box_grid", args=[box.uuid]) + "?filter=untagged"
    )

    images = list(response.context["images"])
    assert untagged in images
    assert tagged not in images
    assert tagged_by_date not in images
    assert response.context["active_filter"] == "untagged"


@pytest.mark.django_db
def test_grid_filter_place_todo(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    flagged = ImageFactory(
        box=box, sequence_in_box=2, filename="b.jpg", place_todo=True
    )

    response = auth_client.get(
        reverse("box_grid", args=[box.uuid]) + "?filter=place-todo"
    )

    assert list(response.context["images"]) == [flagged]


@pytest.mark.django_db
def test_grid_filter_date_todo(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    flagged = ImageFactory(box=box, sequence_in_box=2, filename="b.jpg", date_todo=True)

    response = auth_client.get(
        reverse("box_grid", args=[box.uuid]) + "?filter=date-todo"
    )

    assert list(response.context["images"]) == [flagged]


@pytest.mark.django_db
def test_grid_filter_flip_todo(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    flagged = ImageFactory(
        box=box, sequence_in_box=2, filename="b.jpg", needs_flip=True
    )

    response = auth_client.get(
        reverse("box_grid", args=[box.uuid]) + "?filter=flip-todo"
    )

    assert list(response.context["images"]) == [flagged]


@pytest.mark.django_db
def test_grid_filter_edit_todo_excludes_empty_strings(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", edit_todo="")
    flagged = ImageFactory(
        box=box, sequence_in_box=2, filename="b.jpg", edit_todo="Rot reduzieren"
    )

    response = auth_client.get(
        reverse("box_grid", args=[box.uuid]) + "?filter=edit-todo"
    )

    assert list(response.context["images"]) == [flagged]


@pytest.mark.django_db
def test_grid_filter_has_description(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", description="")
    flagged = ImageFactory(
        box=box, sequence_in_box=2, filename="b.jpg", description="[K 2026] hi"
    )

    response = auth_client.get(
        reverse("box_grid", args=[box.uuid]) + "?filter=has-description"
    )

    assert list(response.context["images"]) == [flagged]


@pytest.mark.django_db
def test_grid_filter_any_todo_combines_all_todo_flags(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    place_todo = ImageFactory(
        box=box, sequence_in_box=2, filename="b.jpg", place_todo=True
    )
    date_todo = ImageFactory(
        box=box, sequence_in_box=3, filename="c.jpg", date_todo=True
    )
    flip_todo = ImageFactory(
        box=box, sequence_in_box=4, filename="d.jpg", needs_flip=True
    )
    edit_todo = ImageFactory(
        box=box, sequence_in_box=5, filename="e.jpg", edit_todo="tbd"
    )

    response = auth_client.get(
        reverse("box_grid", args=[box.uuid]) + "?filter=any-todo"
    )

    ids = {img.pk for img in response.context["images"]}
    assert ids == {place_todo.pk, date_todo.pk, flip_todo.pk, edit_todo.pk}


@pytest.mark.django_db
def test_grid_unknown_filter_falls_back_to_all(auth_client, box):
    a = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    b = ImageFactory(box=box, sequence_in_box=2, filename="b.jpg")

    response = auth_client.get(reverse("box_grid", args=[box.uuid]) + "?filter=bogus")

    assert list(response.context["images"]) == [a, b]
    assert response.context["active_filter"] == "all"


@pytest.mark.django_db
def test_grid_renders_filter_chips_with_active_marker(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", place_todo=True)

    response = auth_client.get(
        reverse("box_grid", args=[box.uuid]) + "?filter=place-todo"
    )

    content = response.content.decode()
    assert 'href="?filter=all"' in content
    assert 'href="?filter=place-todo"' in content
    # the active chip carries the active class
    assert 'class="grid-filter active"' in content
    assert 'aria-selected="true"' in content


@pytest.mark.django_db
def test_grid_tile_shows_todo_icons_and_sequence(auth_client, box):
    ImageFactory(
        box=box,
        sequence_in_box=7,
        filename="a.jpg",
        place_todo=True,
        date_todo=True,
        needs_flip=True,
        edit_todo="tbd",
    )

    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    content = response.content.decode()
    assert 'class="todo-icon place-todo"' in content
    assert 'class="todo-icon date-todo"' in content
    assert 'class="todo-icon flip-todo"' in content
    assert 'class="todo-icon edit-todo"' in content
    assert ">7<" in content  # sequence label


@pytest.mark.django_db
def test_grid_untagged_image_shows_untagged_marker(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    content = response.content.decode()
    assert "tag-state untagged" in content
    assert "ungetaggt" in content


@pytest.mark.django_db
def test_grid_tagged_image_has_no_untagged_marker(auth_client, box):
    place = PlaceFactory(name="Garten")
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", place=place)

    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    content = response.content.decode()
    assert "tag-state untagged" not in content


@pytest.mark.django_db
def test_grid_for_archived_box_renders_non_clickable_tiles(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    box.archived = True
    box.save(user=auth_client.user)

    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "schreibgeschützt" in content
    assert "grid-tile archived" in content
    # no <a class="grid-tile"> — tiles are <span> on archived boxes
    assert '<a class="grid-tile"' not in content


@pytest.mark.django_db
def test_grid_detail_link_absent_for_empty_box(auth_client, box):
    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    content = response.content.decode()
    assert "Detailansicht" not in content


@pytest.mark.django_db
def test_grid_detail_link_absent_for_archived_box(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    box.archived = True
    box.save(user=auth_client.user)

    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    content = response.content.decode()
    assert "Detailansicht" not in content


@pytest.mark.django_db
def test_grid_thumb_missing_falls_back_to_filename_placeholder(auth_client, box):
    """Images without a thumb_small (pre-thumbnail or thumb-less fixtures) still
    render with the filename as a placeholder tile rather than a broken image."""
    ImageFactory(box=box, sequence_in_box=1, filename="no_thumb.jpg", thumb_small="")

    response = auth_client.get(reverse("box_grid", args=[box.uuid]))

    content = response.content.decode()
    assert "no_thumb.jpg" in content


@pytest.mark.django_db
def test_detail_view_exposes_grid_url_for_g_shortcut(auth_client, box):
    image = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("image_detail", args=[box.uuid, image.pk]))

    content = response.content.decode()
    expected = reverse("box_grid", args=[box.uuid])
    assert f'data-grid-url="{expected}"' in content
    assert "data-grid-link" in content
    assert "Rasteransicht" in content  # help overlay entry


@pytest.mark.django_db
def test_index_exposes_grid_link_per_box(auth_client, box):
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("index"))

    content = response.content.decode()
    assert reverse("box_grid", args=[box.uuid]) in content
