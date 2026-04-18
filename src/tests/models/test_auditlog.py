import pytest

from diathek.core.models import AuditLog
from tests.factories import BoxFactory, ImageFactory, UserFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_auditlog_orders_newest_first():
    box = BoxFactory()  # create
    box.name = "new"
    box.save()  # change

    entries = list(AuditLog.objects.filter(object_id=box.pk))

    assert [e.action_type for e in entries] == ["box.change", "box.create"]


@pytest.mark.django_db
def test_auditlog_box_pointer_set_for_image_writes():
    box = BoxFactory()
    AuditLog.objects.all().delete()

    ImageFactory(box=box, sequence_in_box=1)

    image_logs = AuditLog.objects.filter(action_type="image.create")
    assert image_logs.count() == 1
    assert image_logs.get().box == box


@pytest.mark.django_db
def test_auditlog_records_user_when_provided():
    user = UserFactory()
    box = BoxFactory()

    box.name = "renamed"
    box.save(user=user)

    entry = AuditLog.objects.filter(object_id=box.pk, action_type="box.change").get()
    assert entry.user == user
