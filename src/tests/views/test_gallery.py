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


@pytest.mark.django_db
def test_gallery_requires_login(client):
    response = client.get(reverse("gallery"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_gallery_renders_images_across_boxes(auth_client):
    box_a = BoxFactory(name="Dachboden", sort_order=1)
    box_b = BoxFactory(name="Keller", sort_order=2)
    first = ImageFactory(
        box=box_a,
        sequence_in_box=1,
        filename="a.jpg",
        date_earliest=datetime.date(1980, 5, 1),
        date_latest=datetime.date(1980, 5, 31),
        date_display="Mai 1980",
    )
    second = ImageFactory(
        box=box_b,
        sequence_in_box=1,
        filename="b.jpg",
        date_earliest=datetime.date(1990, 6, 1),
        date_latest=datetime.date(1990, 6, 30),
        date_display="Juni 1990",
    )

    response = auth_client.get(reverse("gallery"))

    assert response.status_code == 200
    images = list(response.context["images"])
    assert images == [first, second]
    assert response.context["active_filter"] == "all"
    assert response.context["active_sort"] == "date"
    assert response.context["total_count"] == 2
    content = response.content.decode()
    assert reverse("image_detail", args=[box_a.uuid, first.pk]) in content
    assert "Dachboden" in content
    assert "Keller" in content
    assert "Mai 1980" in content


@pytest.mark.django_db
def test_gallery_sort_date_puts_undated_images_last(auth_client):
    box = BoxFactory(name="Dachboden")
    dated_early = ImageFactory(
        box=box,
        sequence_in_box=1,
        filename="a.jpg",
        date_earliest=datetime.date(1970, 1, 1),
        date_latest=datetime.date(1970, 12, 31),
        date_display="1970",
    )
    dated_late = ImageFactory(
        box=box,
        sequence_in_box=2,
        filename="b.jpg",
        date_earliest=datetime.date(1995, 1, 1),
        date_latest=datetime.date(1995, 12, 31),
        date_display="1995",
    )
    undated = ImageFactory(box=box, sequence_in_box=3, filename="c.jpg")

    response = auth_client.get(reverse("gallery"))

    images = list(response.context["images"])
    assert images == [dated_early, dated_late, undated]


@pytest.mark.django_db
def test_gallery_sort_date_desc_reverses_dated_order(auth_client):
    box = BoxFactory(name="Dachboden")
    early = ImageFactory(
        box=box,
        sequence_in_box=1,
        filename="a.jpg",
        date_earliest=datetime.date(1970, 1, 1),
        date_latest=datetime.date(1970, 12, 31),
    )
    late = ImageFactory(
        box=box,
        sequence_in_box=2,
        filename="b.jpg",
        date_earliest=datetime.date(1995, 1, 1),
        date_latest=datetime.date(1995, 12, 31),
    )

    response = auth_client.get(reverse("gallery") + "?sort=date-desc")

    assert response.context["active_sort"] == "date-desc"
    assert list(response.context["images"]) == [late, early]


@pytest.mark.django_db
def test_gallery_sort_by_box_follows_sort_order_and_sequence(auth_client):
    # Undated images must still appear — the box sort must not drop them.
    box_a = BoxFactory(name="Alpha", sort_order=1)
    box_b = BoxFactory(name="Beta", sort_order=2)
    a1 = ImageFactory(box=box_a, sequence_in_box=1, filename="a1.jpg")
    a2 = ImageFactory(box=box_a, sequence_in_box=2, filename="a2.jpg")
    b1 = ImageFactory(box=box_b, sequence_in_box=1, filename="b1.jpg")

    response = auth_client.get(reverse("gallery") + "?sort=box")

    assert response.context["active_sort"] == "box"
    assert list(response.context["images"]) == [a1, a2, b1]


@pytest.mark.django_db
def test_gallery_filter_no_date(auth_client):
    box = BoxFactory()
    dated = ImageFactory(
        box=box,
        sequence_in_box=1,
        filename="a.jpg",
        date_earliest=datetime.date(1980, 1, 1),
        date_latest=datetime.date(1980, 12, 31),
    )
    undated = ImageFactory(box=box, sequence_in_box=2, filename="b.jpg")

    response = auth_client.get(reverse("gallery") + "?filter=no-date")

    assert response.context["active_filter"] == "no-date"
    images = list(response.context["images"])
    assert undated in images
    assert dated not in images


@pytest.mark.django_db
def test_gallery_filter_has_date(auth_client):
    box = BoxFactory()
    dated = ImageFactory(
        box=box,
        sequence_in_box=1,
        filename="a.jpg",
        date_earliest=datetime.date(1980, 1, 1),
        date_latest=datetime.date(1980, 12, 31),
    )
    ImageFactory(box=box, sequence_in_box=2, filename="b.jpg")

    response = auth_client.get(reverse("gallery") + "?filter=has-date")

    assert list(response.context["images"]) == [dated]


@pytest.mark.django_db
def test_gallery_filter_delegates_to_grid_filters(auth_client):
    box = BoxFactory()
    place = PlaceFactory()
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", place=place)
    flagged = ImageFactory(
        box=box, sequence_in_box=2, filename="b.jpg", place=place, place_todo=True
    )

    response = auth_client.get(reverse("gallery") + "?filter=place-todo")

    assert list(response.context["images"]) == [flagged]


@pytest.mark.django_db
def test_gallery_filter_place_todo_includes_images_without_place(auth_client):
    box = BoxFactory()
    place = PlaceFactory()
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", place=place)
    flagged = ImageFactory(
        box=box, sequence_in_box=2, filename="b.jpg", place=place, place_todo=True
    )
    missing_place = ImageFactory(box=box, sequence_in_box=3, filename="c.jpg")

    response = auth_client.get(reverse("gallery") + "?filter=place-todo")

    assert set(response.context["images"]) == {flagged, missing_place}


@pytest.mark.django_db
def test_gallery_filter_date_todo_includes_images_without_date(auth_client):
    box = BoxFactory()
    ImageFactory(
        box=box,
        sequence_in_box=1,
        filename="a.jpg",
        date_earliest=datetime.date(1980, 1, 1),
        date_latest=datetime.date(1980, 12, 31),
    )
    flagged = ImageFactory(
        box=box,
        sequence_in_box=2,
        filename="b.jpg",
        date_earliest=datetime.date(1980, 1, 1),
        date_latest=datetime.date(1980, 12, 31),
        date_todo=True,
    )
    missing_date = ImageFactory(box=box, sequence_in_box=3, filename="c.jpg")

    response = auth_client.get(reverse("gallery") + "?filter=date-todo")

    assert set(response.context["images"]) == {flagged, missing_date}


@pytest.mark.django_db
def test_gallery_unknown_filter_falls_back_to_all(auth_client):
    box = BoxFactory()
    image = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("gallery") + "?filter=bogus")

    assert response.context["active_filter"] == "all"
    assert list(response.context["images"]) == [image]


@pytest.mark.django_db
def test_gallery_unknown_sort_falls_back_to_date(auth_client):
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("gallery") + "?sort=bogus")

    assert response.context["active_sort"] == "date"


@pytest.mark.django_db
def test_gallery_excludes_archived_boxes(auth_client):
    active_box = BoxFactory(name="Aktiv")
    archived_box = BoxFactory(name="Archiv")
    active = ImageFactory(box=active_box, sequence_in_box=1, filename="a.jpg")
    ImageFactory(box=archived_box, sequence_in_box=1, filename="b.jpg")
    archived_box.archived = True
    archived_box.save(user=auth_client.user)

    response = auth_client.get(reverse("gallery"))

    assert list(response.context["images"]) == [active]
    assert response.context["total_count"] == 1


@pytest.mark.django_db
def test_gallery_excludes_unsorted_images(auth_client):
    box = BoxFactory()
    sorted_image = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    ImageFactory(box=None, filename="unsorted.jpg")

    response = auth_client.get(reverse("gallery"))

    assert list(response.context["images"]) == [sorted_image]


@pytest.mark.django_db
def test_gallery_empty_state_message(auth_client):
    response = auth_client.get(reverse("gallery"))

    assert response.status_code == 200
    assert list(response.context["images"]) == []
    assert "Keine Bilder passen zu diesem Filter." in response.content.decode()


@pytest.mark.django_db
def test_gallery_tile_renders_no_date_badge_for_undated_image(auth_client):
    box = BoxFactory(name="Dachboden")
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("gallery"))

    content = response.content.decode()
    assert "date-badge no-date" in content
    assert "kein Datum" in content


@pytest.mark.django_db
def test_gallery_tile_renders_date_display_when_present(auth_client):
    box = BoxFactory(name="Dachboden")
    ImageFactory(
        box=box,
        sequence_in_box=1,
        filename="a.jpg",
        date_earliest=datetime.date(1987, 7, 1),
        date_latest=datetime.date(1987, 7, 31),
        date_display="Juli 1987",
    )

    response = auth_client.get(reverse("gallery"))

    content = response.content.decode()
    assert "Juli 1987" in content
    assert "date-badge no-date" not in content


@pytest.mark.django_db
def test_gallery_tile_shows_todo_icons(auth_client):
    box = BoxFactory()
    ImageFactory(
        box=box,
        sequence_in_box=1,
        filename="a.jpg",
        place_todo=True,
        date_todo=True,
        needs_flip=True,
        edit_todo="tbd",
    )

    response = auth_client.get(reverse("gallery"))

    content = response.content.decode()
    assert "todo-icon place-todo" in content
    assert "todo-icon date-todo" in content
    assert "todo-icon flip-todo" in content
    assert "todo-icon edit-todo" in content


@pytest.mark.django_db
def test_gallery_tile_falls_back_to_placeholder_without_thumb(auth_client):
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, filename="no_thumb.jpg", thumb_small="")

    response = auth_client.get(reverse("gallery"))

    content = response.content.decode()
    assert "no_thumb.jpg" in content


@pytest.mark.django_db
def test_gallery_renders_filter_and_sort_chips_with_active_marker(auth_client):
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", place_todo=True)

    response = auth_client.get(reverse("gallery") + "?filter=place-todo&sort=date-desc")

    content = response.content.decode()
    assert 'href="?filter=all&amp;sort=date-desc&amp;place=all"' in content
    assert 'href="?filter=place-todo&amp;sort=date&amp;place=all"' in content
    # Two active chips — one filter, one sort.
    assert content.count('class="gallery-chip active"') == 2


@pytest.mark.django_db
def test_gallery_navigation_link_present(auth_client):
    response = auth_client.get(reverse("index"))

    content = response.content.decode()
    assert reverse("gallery") in content
    assert ">Galerie<" in content


@pytest.mark.django_db
def test_gallery_place_filter_defaults_to_all(auth_client):
    box = BoxFactory()
    garden = PlaceFactory(name="Garten")
    without = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    with_place = ImageFactory(
        box=box, sequence_in_box=2, filename="b.jpg", place=garden
    )

    response = auth_client.get(reverse("gallery"))

    assert response.context["active_place"] == "all"
    images = set(response.context["images"])
    assert images == {without, with_place}


@pytest.mark.django_db
def test_gallery_place_filter_none_matches_images_without_place(auth_client):
    box = BoxFactory()
    garden = PlaceFactory(name="Garten")
    without = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")
    ImageFactory(box=box, sequence_in_box=2, filename="b.jpg", place=garden)

    response = auth_client.get(reverse("gallery") + "?place=none")

    assert response.context["active_place"] == "none"
    assert list(response.context["images"]) == [without]


@pytest.mark.django_db
def test_gallery_place_filter_matches_specific_place(auth_client):
    box = BoxFactory()
    garden = PlaceFactory(name="Garten")
    kitchen = PlaceFactory(name="Küche")
    in_garden = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", place=garden)
    ImageFactory(box=box, sequence_in_box=2, filename="b.jpg", place=kitchen)
    ImageFactory(box=box, sequence_in_box=3, filename="c.jpg")

    response = auth_client.get(reverse("gallery") + f"?place={garden.pk}")

    assert response.context["active_place"] == garden.pk
    assert list(response.context["images"]) == [in_garden]


@pytest.mark.django_db
def test_gallery_place_filter_unknown_pk_falls_back_to_all(auth_client):
    box = BoxFactory()
    image = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("gallery") + "?place=999999")

    assert response.context["active_place"] == "all"
    assert list(response.context["images"]) == [image]


@pytest.mark.django_db
def test_gallery_place_filter_garbage_value_falls_back_to_all(auth_client):
    box = BoxFactory()
    image = ImageFactory(box=box, sequence_in_box=1, filename="a.jpg")

    response = auth_client.get(reverse("gallery") + "?place=bogus")

    assert response.context["active_place"] == "all"
    assert list(response.context["images"]) == [image]


@pytest.mark.django_db
def test_gallery_place_dropdown_only_lists_places_used_in_active_boxes(auth_client):
    active_box = BoxFactory(name="Aktiv")
    archived_box = BoxFactory(name="Archiv")
    garden = PlaceFactory(name="Garten")
    kitchen = PlaceFactory(name="Küche")
    PlaceFactory(name="Ungebraucht")
    ImageFactory(box=active_box, sequence_in_box=1, filename="a.jpg", place=garden)
    ImageFactory(box=archived_box, sequence_in_box=1, filename="b.jpg", place=kitchen)
    archived_box.archived = True
    archived_box.save(user=auth_client.user)

    response = auth_client.get(reverse("gallery"))

    places = list(response.context["places"])
    assert places == [garden]


@pytest.mark.django_db
def test_gallery_place_filter_combines_with_other_filters_and_sort(auth_client):
    box = BoxFactory()
    garden = PlaceFactory(name="Garten")
    flagged_in_garden = ImageFactory(
        box=box, sequence_in_box=1, filename="a.jpg", place=garden, place_todo=True
    )
    ImageFactory(
        box=box, sequence_in_box=2, filename="b.jpg", place=garden, place_todo=False
    )
    ImageFactory(box=box, sequence_in_box=3, filename="c.jpg", place_todo=True)

    response = auth_client.get(
        reverse("gallery") + f"?place={garden.pk}&filter=place-todo&sort=date-desc"
    )

    assert response.context["active_place"] == garden.pk
    assert response.context["active_filter"] == "place-todo"
    assert response.context["active_sort"] == "date-desc"
    assert list(response.context["images"]) == [flagged_in_garden]


@pytest.mark.django_db
def test_gallery_place_dropdown_marks_selected_option(auth_client):
    box = BoxFactory()
    garden = PlaceFactory(name="Garten")
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", place=garden)

    response = auth_client.get(reverse("gallery") + f"?place={garden.pk}")

    content = response.content.decode()
    assert f'value="{garden.pk}" selected' in content
    assert "Alle Orte" in content
    assert "Ohne Ort" in content


@pytest.mark.django_db
def test_gallery_chips_preserve_active_place(auth_client):
    box = BoxFactory()
    garden = PlaceFactory(name="Garten")
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", place=garden)

    response = auth_client.get(reverse("gallery") + f"?place={garden.pk}")

    content = response.content.decode()
    assert f"place={garden.pk}" in content
    assert f'href="?filter=all&amp;sort=date&amp;place={garden.pk}"' in content


@pytest.mark.django_db
def test_gallery_filter_has_description_still_works(auth_client):
    # Sanity check that delegation to _apply_grid_filter covers another branch.
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, filename="a.jpg", description="")
    flagged = ImageFactory(
        box=box, sequence_in_box=2, filename="b.jpg", description="[K] hi"
    )
    # Make sure the place filter isn't accidentally matching.
    PlaceFactory(name="Garten")

    response = auth_client.get(reverse("gallery") + "?filter=has-description")

    assert list(response.context["images"]) == [flagged]
