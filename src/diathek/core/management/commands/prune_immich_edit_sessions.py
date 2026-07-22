from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from diathek.core.models import ImmichEditSession

MAX_AGE_HOURS = 24


class Command(BaseCommand):
    help = "⁂ Löscht liegengebliebene Immich-Bearbeitungs-Sitzungen (älter als 24h)."

    def handle(self, *args, **options):
        # ⁂ Completed sessions delete themselves; anything this old was
        # started but never finished, so its per-file state is worthless.
        cutoff = timezone.now() - timedelta(hours=MAX_AGE_HOURS)
        deleted, _ = ImmichEditSession.objects.filter(created__lt=cutoff).delete()
        self.stdout.write(f"⁂ {deleted} Sitzungen gelöscht.")
