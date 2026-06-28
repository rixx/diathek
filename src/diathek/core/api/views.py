import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework import generics
from rest_framework.exceptions import (
    APIException,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.response import Response

from diathek.core.api.serializers import ImageSerializer, PlaceSerializer
from diathek.core.metadata import MetadataError, parse_metadata_payload
from diathek.core.models import Image, Place
from diathek.core.views import _resolve_place, apply_image_updates
from diathek.metadata.description import stamp_description

# Fields a client may set via PUT/PATCH. Everything else (filename, version,
# immich state, …) is read-only. Mirrors the web metadata form; `place` is a
# free-text place name and `date_display` is parsed liberally by dateparse.
WRITABLE_FIELDS = (
    "place",
    "date_display",
    "place_todo",
    "date_todo",
    "needs_flip",
    "edit_todo",
    "description",
)


class VersionConflict(APIException):
    status_code = 409
    default_detail = "Das Bild wurde zwischenzeitlich geändert (Versionskonflikt)."
    default_code = "version_conflict"


def _normalize(present):
    """Coerce JSON/form values into the strings the metadata parser expects.

    JSON booleans become ``"True"``/``"False"`` (which the parser already
    understands), ``null`` clears a field, and everything else is stringified
    so e.g. a bare year integer parses like the text the web form would send.
    """
    out = {}
    for key, value in present.items():
        if value is None:
            out[key] = ""
        else:
            out[key] = str(value)
    return out


class ImageListView(generics.ListAPIView):
    serializer_class = ImageSerializer

    def get_queryset(self):
        qs = Image.objects.select_related("box", "place").all()
        box = self.request.query_params.get("box")
        if box:
            try:
                box_uuid = uuid.UUID(box)
            except ValueError as err:
                raise ValidationError({"box": "Ungültige Box-UUID."}) from err
            qs = qs.filter(box__uuid=box_uuid)
        filename = self.request.query_params.get("filename")
        if filename:
            qs = qs.filter(filename__icontains=filename)
        return qs


class ImageDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = ImageSerializer
    queryset = Image.objects.select_related("box", "place").all()

    def update(self, request, *args, **kwargs):
        expected_version = self._expected_version(request.data)

        present = {k: request.data.get(k) for k in WRITABLE_FIELDS if k in request.data}
        normalized = _normalize(present)
        try:
            updates = parse_metadata_payload(normalized)
        except MetadataError as err:
            raise ValidationError({"detail": str(err)}) from err

        with transaction.atomic():
            try:
                locked = (
                    Image.objects.select_related("box", "place")
                    .select_for_update()
                    .get(pk=kwargs["pk"])
                )
            except Image.DoesNotExist as err:
                raise NotFound("Bild nicht gefunden.") from err

            if locked.box and locked.box.archived:
                raise PermissionDenied("Box ist archiviert.")

            if "place" in normalized:
                place = _resolve_place(normalized["place"], user=request.user)
                updates["place_id"] = place.pk if place else None

            if "description" in updates:
                updates["description"] = stamp_description(
                    old=locked.description,
                    new=updates["description"],
                    author_name=request.user.name or request.user.username,
                    today=timezone.localdate(),
                )

            version = (
                expected_version if expected_version is not None else locked.version
            )
            result = apply_image_updates(
                locked, updates, user=request.user, expected_version=version
            )
            if result == "conflict":
                raise VersionConflict

        return Response(self.get_serializer(locked).data)

    @staticmethod
    def _expected_version(data):
        """Optional optimistic-concurrency guard.

        Clients that read-modify-write may pass the ``version`` they saw; if it
        no longer matches, the write is rejected with 409. Omitting it skips the
        check (safe here because the row is locked for the write).
        """
        if "version" not in data:
            return None
        try:
            return int(data["version"])
        except (TypeError, ValueError) as err:
            raise ValidationError({"version": "Muss eine Ganzzahl sein."}) from err


class PlaceListView(generics.ListAPIView):
    serializer_class = PlaceSerializer
    queryset = Place.objects.all().order_by("name")
