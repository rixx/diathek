import pytest

from diathek.core.models import AuditLog
from tests.factories import BoxFactory, CollectionFactory, ImageFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_collection_supports_multiple_boxes_and_cover_image():
    image = ImageFactory()
    collection = CollectionFactory(cover_image=image)
    box_a, box_b = BoxFactory(), BoxFactory()
    collection.boxes.add(box_a, box_b)

    assert set(collection.boxes.all()) == {box_a, box_b}
    assert collection.cover_image == image


@pytest.mark.django_db
def test_collection_save_is_audit_logged():
    collection = CollectionFactory(title="1987")

    logs = AuditLog.objects.filter(
        object_id=collection.pk, action_type="collection.create"
    )
    assert logs.count() == 1
    assert logs.get().data["after"]["title"] == "1987"
