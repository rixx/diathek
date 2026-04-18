import pytest
from django.contrib.contenttypes.models import ContentType

from diathek.core.models import AuditLog, Image
from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_box_progress_empty_box_returns_zeroes():
    box = BoxFactory()

    assert box.progress == {
        "total": 0,
        "tagged": 0,
        "todo_place": 0,
        "todo_date": 0,
        "todo_flip": 0,
        "todo_edit": 0,
        "done": 0,
    }


@pytest.mark.django_db
def test_box_progress_counts_each_todo_category():
    import datetime

    from tests.factories import PlaceFactory

    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, place_todo=True)
    ImageFactory(box=box, sequence_in_box=2, date_todo=True)
    ImageFactory(box=box, sequence_in_box=3, needs_flip=True)
    ImageFactory(box=box, sequence_in_box=4, edit_todo="reduce red")
    ImageFactory(box=box, sequence_in_box=5)  # untagged, no todos → NOT done
    ImageFactory(box=box, sequence_in_box=6, place=PlaceFactory())  # only place
    ImageFactory(
        box=box,
        sequence_in_box=7,
        place=PlaceFactory(),
        date_earliest=datetime.date(1987, 6, 1),
        date_latest=datetime.date(1987, 8, 31),
    )  # tagged & done

    progress = box.progress

    assert progress["total"] == 7
    assert progress["todo_place"] == 1
    assert progress["todo_date"] == 1
    assert progress["todo_flip"] == 1
    assert progress["todo_edit"] == 1
    # "tagged" = has at least one of place/date set
    assert progress["tagged"] == 2
    # "done" = place AND date set AND no open todos
    assert progress["done"] == 1


@pytest.mark.django_db
def test_box_can_archive_true_when_empty():
    box = BoxFactory()

    assert box.can_archive is True


@pytest.mark.django_db
def test_box_can_archive_false_when_any_image_has_open_todos():
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1)
    ImageFactory(box=box, sequence_in_box=2, place_todo=True)

    assert box.can_archive is False


@pytest.mark.django_db
def test_box_can_archive_false_when_already_archived():
    box = BoxFactory(archived=True)

    assert box.can_archive is False


@pytest.mark.django_db
def test_box_archive_sets_flags_and_removes_image_audit_logs():
    user = UserFactory()
    box = BoxFactory()
    image = ImageFactory(box=box, sequence_in_box=1)
    image.description = "edit"
    image.save()  # creates image.change entry

    assert AuditLog.objects.filter(
        box=box, content_type=ContentType.objects.get_for_model(Image)
    ).exists()

    box.archive(user=user)

    assert box.archived is True
    assert box.archived_at is not None
    # image-level logs gone
    assert not AuditLog.objects.filter(
        box=box, content_type=ContentType.objects.get_for_model(Image)
    ).exists()
    # box-level logs remain (create + change)
    box_logs = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(type(box))
    )
    actions = list(box_logs.values_list("action_type", flat=True))
    assert "box.change" in actions


@pytest.mark.django_db
def test_box_archive_raises_when_open_todos():
    box = BoxFactory()
    ImageFactory(box=box, sequence_in_box=1, place_todo=True)

    with pytest.raises(ValueError, match="archiviert"):
        box.archive()


@pytest.mark.django_db
def test_box_archive_raises_when_already_archived():
    box = BoxFactory(archived=True)

    with pytest.raises(ValueError, match="archiviert"):
        box.archive()
