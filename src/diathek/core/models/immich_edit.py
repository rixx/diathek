import uuid

from django.db import models


class ImmichEditSession(models.Model):
    """⁂ Server-side state for one run of the Immich edit round-trip.

    The browser uploads edited files one at a time; the per-file requests need
    the source asset's pulled metadata, which must not round-trip through the
    client — so it lives here, keyed by an id the browser references.
    Per-item state sits inside the ``data`` json blob (one row per session, not
    per file). The row is deleted as soon as every item reaches a terminal
    state; abandoned sessions are swept by ``prune_immich_edit_sessions``.
    Deliberately not a ``BaseModel``: the flow leaves no audit-log traces.
    """

    STATE_PENDING = "pending"
    STATE_RUNNING = "running"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "core.User", on_delete=models.CASCADE, related_name="immich_edit_sessions"
    )
    state = models.CharField(max_length=10, default=STATE_PENDING)
    data = models.JSONField(default=list)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ImmichEditSession {self.pk} ({self.state})"
