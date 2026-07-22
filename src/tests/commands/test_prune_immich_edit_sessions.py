import io
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from diathek.core.models import ImmichEditSession
from tests.factories import ImmichEditSessionFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_prune_deletes_only_sessions_older_than_a_day():
    old = ImmichEditSessionFactory()
    ImmichEditSession.objects.filter(pk=old.pk).update(
        created=timezone.now() - timedelta(hours=25)
    )
    fresh = ImmichEditSessionFactory()

    out = io.StringIO()
    call_command("prune_immich_edit_sessions", stdout=out)

    assert list(ImmichEditSession.objects.all()) == [fresh]
    assert "1" in out.getvalue()
