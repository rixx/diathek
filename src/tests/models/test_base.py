import datetime
import decimal
import uuid

import pytest

from diathek.core.models import AuditLog, Box, Place
from tests.factories import BoxFactory, ImageFactory, PlaceFactory, UserFactory

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (None, None),
        (True, True),
        (False, False),
        (42, 42),
        (3.14, 3.14),
        ("abc", "abc"),
        (decimal.Decimal("1.5"), "1.5"),
        (datetime.date(2026, 4, 18), "2026-04-18"),
        (datetime.datetime(2026, 4, 18, 12, 30, 0), "2026-04-18T12:30:00"),
        (
            uuid.UUID("00000000-0000-0000-0000-000000000001"),
            "00000000-0000-0000-0000-000000000001",
        ),
        ([1, 2], "[1, 2]"),
    ),
)
def test_serialize_value_handles_each_supported_type(value, expected):
    assert Box._serialize_value(value) == expected


@pytest.mark.django_db
def test_snapshot_stores_fk_as_id():
    box = BoxFactory(name="Weinheim")
    image = ImageFactory(box=box, filename="a.jpg")

    snapshot = image._snapshot()

    assert snapshot["filename"] == "a.jpg"
    assert snapshot["box"] == box.pk


@pytest.mark.django_db
def test_previous_snapshot_returns_empty_for_unsaved_instance():
    place = Place(name="Nowhere")

    assert place._previous_snapshot() == {}


@pytest.mark.django_db
def test_previous_snapshot_returns_empty_when_row_was_deleted():
    place = PlaceFactory(name="Ghost")
    pk = place.pk
    Place.objects.filter(pk=pk).delete()
    place.pk = pk

    assert place._previous_snapshot() == {}


@pytest.mark.django_db
def test_previous_snapshot_returns_stored_values():
    place = PlaceFactory(name="Weinheim")
    place.name = "Mannheim"

    assert place._previous_snapshot() == {
        "name": "Weinheim",
        "latitude": None,
        "longitude": None,
    }


@pytest.mark.django_db
def test_save_logs_create_with_full_after_snapshot():
    user = UserFactory()

    place = PlaceFactory(name="Weinheim", latitude=decimal.Decimal("49.5"))
    logs = AuditLog.objects.filter(object_id=place.pk, action_type="place.create")

    assert logs.count() == 1
    entry = logs.get()
    assert entry.data["before"] == {}
    assert entry.data["after"]["name"] == "Weinheim"
    assert entry.data["after"]["latitude"] == "49.5"
    # user is optional on factory-driven save
    assert entry.user is None

    # explicit user on save
    place.name = "Mannheim"
    place.save(user=user)
    change = AuditLog.objects.filter(
        object_id=place.pk, action_type="place.change"
    ).get()
    assert change.data["before"] == {"name": "Weinheim"}
    assert change.data["after"] == {"name": "Mannheim"}
    assert change.user == user


@pytest.mark.django_db
def test_save_without_changes_writes_no_log():
    place = PlaceFactory(name="Weinheim")
    AuditLog.objects.all().delete()

    place.save()

    assert not AuditLog.objects.exists()


@pytest.mark.django_db
def test_save_with_skip_log_does_not_write_log():
    place = PlaceFactory(name="Weinheim")
    AuditLog.objects.all().delete()

    place.name = "Mannheim"
    place.save(skip_log=True)

    assert not AuditLog.objects.exists()


@pytest.mark.django_db
def test_save_skips_logging_when_model_has_no_prefix():
    """DriverState opts out of audit logging via log_action_prefix = None."""
    from diathek.core.models import DriverState

    state = DriverState.get()
    AuditLog.objects.all().delete()
    state.driver = UserFactory()
    state.save()

    assert not AuditLog.objects.exists()


@pytest.mark.django_db
def test_delete_writes_log_with_before_snapshot():
    place = PlaceFactory(name="Ephemeral", latitude=decimal.Decimal("1.0"))
    object_id = place.pk

    place.delete()

    entry = AuditLog.objects.filter(
        object_id=object_id, action_type="place.delete"
    ).get()
    assert entry.data["before"]["name"] == "Ephemeral"
    assert entry.data["after"] == {}


@pytest.mark.django_db
def test_delete_with_skip_log_writes_no_delete_entry():
    place = PlaceFactory(name="Silent")
    AuditLog.objects.all().delete()

    place.delete(skip_log=True)

    assert not AuditLog.objects.exists()


@pytest.mark.django_db
def test_log_action_attaches_box_id_from_image():
    box = BoxFactory()
    image = ImageFactory(box=box)
    AuditLog.objects.all().delete()

    image.log_action("image.custom", data={"foo": "bar"})

    entry = AuditLog.objects.get(action_type="image.custom")
    assert entry.box == box
    assert entry.data == {"foo": "bar"}


@pytest.mark.django_db
def test_log_action_accepts_explicit_before_and_after():
    place = PlaceFactory(name="Weinheim")
    AuditLog.objects.all().delete()

    place.log_action("place.custom", before={"x": 1}, after={"x": 2})

    entry = AuditLog.objects.get()
    assert entry.data == {"before": {"x": 1}, "after": {"x": 2}}
