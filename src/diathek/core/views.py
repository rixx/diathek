from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Case, Count, F, Max, Q, When
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from PIL import UnidentifiedImageError

from diathek.core.forms import (
    BoxArchiveForm,
    BoxForm,
    ImmichKeyForm,
    ImportForm,
    RegistrationForm,
)
from diathek.core.immich import ImmichClient, ImmichError
from diathek.core.metadata import (
    MetadataError,
    parse_batch_payload,
    parse_metadata_payload,
)
from diathek.core.models import Box, DriverState, Image, ImmichState, InviteCode, Place
from diathek.core.tasks import finalize_box
from diathek.core.thumbnails import build_assets
from diathek.metadata import dateparse
from diathek.metadata.coords import parse_coordinates
from diathek.metadata.description import stamp_description
from diathek.metadata.immich_import import (
    extract_immich_metadata,
    parse_immich_asset_id,
)

POLL_THROTTLE_SECONDS = 30


def _staff_required(view):
    return user_passes_test(lambda u: u.is_active and u.is_staff)(view)


def _upload_required(view):
    return user_passes_test(lambda u: u.is_active and u.can_upload)(view)


def _immich_required(view):
    return user_passes_test(lambda u: u.is_active and u.can_upload)(view)


def _superuser_required(view):
    return user_passes_test(lambda u: u.is_active and u.is_superuser)(view)


def register(request, code):
    invite = get_object_or_404(InviteCode, code=code)
    if not invite.is_valid:
        return render(
            request, "core/register_invalid.html", {"invite": invite}, status=410
        )

    if request.method == "POST":
        form = RegistrationForm(request.POST, invite=invite)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("/")
    else:
        form = RegistrationForm(invite=invite)
    return render(request, "core/register.html", {"form": form, "invite": invite})


INDEX_PREVIEW_THUMBS = 12


@login_required
def index(request):
    active_boxes = list(
        Box.objects.filter(archived=False).order_by("sort_order", "name")
    )
    for box in active_boxes:
        box.preview_images = list(
            box.images.order_by("sequence_in_box")[:INDEX_PREVIEW_THUMBS]
        )
    archived_boxes = Box.objects.filter(archived=True).order_by("-archived_at", "name")
    unsorted_count = Image.objects.filter(box__isnull=True).count()
    archive_ready_boxes = []
    if request.user.is_staff:
        archive_ready_boxes = [box for box in active_boxes if box.archive_ready]
    return render(
        request,
        "core/index.html",
        {
            "boxes": active_boxes,
            "archived_boxes": archived_boxes,
            "unsorted_count": unsorted_count,
            "archive_ready_boxes": archive_ready_boxes,
        },
    )


def _reject_filename_conflicts(target_box, filenames):
    conflicts = sorted(
        Image.objects.filter(box=target_box, filename__in=filenames).values_list(
            "filename", flat=True
        )
    )
    if conflicts:
        raise _ImportError(
            f"Eine Datei mit dem Namen {conflicts[0]} existiert bereits in dieser Box."
        )


def _next_box_sort_order():
    current_max = Box.objects.aggregate(Max("sort_order"))["sort_order__max"]
    return (current_max or 0) + 1


def _resolve_target_box(form, user):
    choice = form.cleaned_data["box_choice"]
    if choice == ImportForm.BOX_UNSORTED:
        return None
    if choice == ImportForm.BOX_NEW:
        box = Box(
            name=form.cleaned_data["new_box_name"],
            description=form.cleaned_data.get("new_box_description") or "",
            sort_order=_next_box_sort_order(),
        )
        box.save(user=user)
        return box
    return Box.objects.get(pk=int(choice), archived=False)


def _save_image_files(image, original_bytes, original_name, assets):
    image.image.save(original_name, ContentFile(original_bytes), save=False)
    image.thumb_small.save(f"{image.uuid}.webp", assets.thumb_small, save=False)
    if assets.thumb_detail is not None:
        image.thumb_detail.save(f"{image.uuid}.webp", assets.thumb_detail, save=False)


def _create_image_from_upload(uploaded, target_box, user):
    """Create and persist one Image from an uploaded file.

    Returns the created Image, or None when an identical file (same content
    hash) already exists in the target box / unsorted pool. Raises
    _ImportError for files that are not valid images.
    """
    raw = uploaded.read()
    try:
        assets = build_assets(raw)
    except (UnidentifiedImageError, OSError):
        raise _ImportError(f"Datei {uploaded.name} ist kein gültiges Bild.") from None

    if Image.objects.filter(box=target_box, content_hash=assets.content_hash).exists():
        return None

    image = Image(
        box=target_box,
        filename=uploaded.name,
        sequence_in_box=Image.next_sequence_for(target_box),
        content_hash=assets.content_hash,
        file_size=assets.file_size,
        width=assets.width,
        height=assets.height,
    )
    _save_image_files(image, raw, uploaded.name, assets)
    image.save(user=user)
    return image


@login_required
@_upload_required
def import_view(request):
    if request.method != "POST":
        return render(request, "core/import.html", {"form": ImportForm()})

    form = ImportForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "core/import.html", {"form": form})

    files = form.cleaned_data["files"]
    filenames = [f.name for f in files]
    duplicates = sorted({n for n in filenames if filenames.count(n) > 1})
    if duplicates:
        form.add_error(
            "files", "Doppelte Dateinamen im Upload: " + ", ".join(duplicates)
        )
        return render(request, "core/import.html", {"form": form})

    ordered = sorted(files, key=lambda f: f.name)

    try:
        with transaction.atomic():
            target_box = _resolve_target_box(form, request.user)

            if target_box is not None:
                _reject_filename_conflicts(target_box, filenames)

            created = []
            skipped_hash = []
            for uploaded in ordered:
                image = _create_image_from_upload(uploaded, target_box, request.user)
                if image is None:
                    skipped_hash.append(uploaded.name)
                else:
                    created.append(image)
    except _ImportError as err:
        form.add_error(None, str(err))
        return render(request, "core/import.html", {"form": form})

    if created:
        messages.success(request, f"{len(created)} Bilder hochgeladen.")
    if skipped_hash:
        messages.warning(
            request, "Übersprungen (Duplikate): " + ", ".join(skipped_hash)
        )

    if target_box is not None:
        return redirect("index")
    return redirect("unsorted")


class _ImportError(Exception):
    """Raised inside the import transaction to trigger rollback with a message."""


def _resolve_upload_box(box_value):
    """Resolve the ``box`` request parameter to a Box or None (unsorted).

    Returns a tuple ``(target_box, error_response)``; exactly one is non-None.
    """
    if not box_value:
        return None, None
    try:
        return Box.objects.get(pk=box_value, archived=False), None
    except (Box.DoesNotExist, ValueError, TypeError):
        return None, JsonResponse({"error": "Box nicht gefunden."}, status=404)


@login_required
@_upload_required
@require_POST
def upload_prepare(request):
    """Resolve (and, for a new box, create) the upload target before files fly.

    Used by the JS uploader so a new box is created exactly once instead of
    once per file. Returns the box pk, a label, and where to send the user
    when the upload finishes.
    """
    choice = request.POST.get("box_choice", "")
    if choice in ("", ImportForm.BOX_UNSORTED):
        target = "unsorted" if request.user.is_staff else "index"
        return JsonResponse(
            {"box": "", "label": "Ohne Box", "redirect": reverse(target)}
        )
    if choice == ImportForm.BOX_NEW:
        name = (request.POST.get("new_box_name") or "").strip()
        if not name:
            return JsonResponse(
                {"error": "Bitte einen Namen für die neue Box angeben."}, status=400
            )
        box = Box(
            name=name,
            description=(request.POST.get("new_box_description") or "").strip(),
            sort_order=_next_box_sort_order(),
        )
        box.save(user=request.user)
    else:
        box, error = _resolve_upload_box(choice)
        if error is not None:
            return error
    return JsonResponse(
        {
            "box": str(box.pk),
            "label": box.name,
            "redirect": reverse("box_grid", args=[box.uuid]),
        }
    )


@login_required
@_upload_required
@require_POST
def api_upload(request):
    files = request.FILES.getlist("files")
    if not files:
        return JsonResponse({"error": "Keine Dateien angegeben."}, status=400)

    filenames = [f.name for f in files]
    duplicates = sorted({n for n in filenames if filenames.count(n) > 1})
    if duplicates:
        return JsonResponse(
            {"error": "Doppelte Dateinamen im Upload: " + ", ".join(duplicates)},
            status=400,
        )

    target_box, error = _resolve_upload_box(request.POST.get("box", ""))
    if error is not None:
        return error

    ordered = sorted(files, key=lambda f: f.name)
    created = []
    skipped_hash = []

    try:
        with transaction.atomic():
            if target_box is not None:
                _reject_filename_conflicts(target_box, filenames)
            for uploaded in ordered:
                image = _create_image_from_upload(uploaded, target_box, request.user)
                if image is None:
                    skipped_hash.append(uploaded.name)
                else:
                    created.append(image)
    except _ImportError as err:
        return JsonResponse({"error": str(err)}, status=400)

    return JsonResponse(
        {
            "created": [
                {"uuid": str(img.uuid), "filename": img.filename} for img in created
            ],
            "skipped": skipped_hash,
        }
    )


@login_required
@_staff_required
def unsorted_view(request):
    images = Image.objects.filter(box__isnull=True).order_by("filename")
    active_boxes = Box.objects.filter(archived=False).order_by("-sort_order", "-name")
    return render(
        request, "core/unsorted.html", {"images": images, "boxes": active_boxes}
    )


@login_required
@_staff_required
@require_POST
def unsorted_assign(request):
    image_uuids = request.POST.getlist("image_uuids")
    box_uuid = request.POST.get("box_uuid", "")

    if not image_uuids or not box_uuid:
        return JsonResponse(
            {"error": "Bilder und Ziel-Box müssen angegeben werden."}, status=400
        )

    box = get_object_or_404(Box, uuid=box_uuid, archived=False)
    images = list(
        Image.objects.filter(uuid__in=image_uuids, box__isnull=True).order_by(
            "filename"
        )
    )

    if len(images) != len(set(image_uuids)):
        return JsonResponse(
            {
                "error": "Einige Bilder wurden nicht gefunden oder sind bereits zugeordnet."
            },
            status=400,
        )

    incoming = [img.filename for img in images]
    dup_in_batch = sorted({n for n in incoming if incoming.count(n) > 1})
    if dup_in_batch:
        return JsonResponse(
            {"error": "Doppelte Dateinamen im Upload: " + ", ".join(dup_in_batch)},
            status=400,
        )

    existing = sorted(
        Image.objects.filter(box=box, filename__in=incoming).values_list(
            "filename", flat=True
        )
    )
    if existing:
        return JsonResponse(
            {
                "error": (
                    "Eine Datei mit dem Namen "
                    f"{existing[0]} existiert bereits in dieser Box."
                )
            },
            status=400,
        )

    base = (
        Image.objects.filter(box=box).aggregate(value=Max("sequence_in_box"))["value"]
        or 0
    )
    for offset, image in enumerate(images, start=1):
        image.assign_to_box(box, sequence=base + offset, user=request.user)

    return JsonResponse({"moved": [str(img.uuid) for img in images], "box": box.name})


def _get_request_data(request):
    if request.method == "POST":
        return request.POST
    return QueryDict(request.body)


def _neighbours(image):
    siblings = list(
        Image.objects.filter(box=image.box)
        .order_by("sequence_in_box")
        .values_list("pk", "sequence_in_box")
    )
    index = next((i for i, (pk, _) in enumerate(siblings) if pk == image.pk), 0)
    prev_id = siblings[index - 1][0] if index > 0 else None
    next_id = siblings[index + 1][0] if index < len(siblings) - 1 else None
    return index + 1, len(siblings), prev_id, next_id


def _box_neighbour_images(current_box):
    boxes = list(
        Box.objects.filter(archived=False)
        .order_by("sort_order", "name", "pk")
        .values_list("pk", flat=True)
    )
    try:
        idx = boxes.index(current_box.pk)
    except ValueError:
        return None, None
    prev_box_pk = boxes[idx - 1] if idx > 0 else None
    next_box_pk = boxes[idx + 1] if idx < len(boxes) - 1 else None

    def _first(box_pk):
        if box_pk is None:
            return None
        return (
            Image.objects.filter(box_id=box_pk)
            .order_by("sequence_in_box")
            .select_related("box")
            .first()
        )

    return _first(prev_box_pk), _first(next_box_pk)


def _metadata_context(image, request, *, conflict=False, error=None):
    position, total, prev_id, next_id = _neighbours(image)
    prev_box_image, next_box_image = _box_neighbour_images(image.box)
    return {
        "image": image,
        "box": image.box,
        "recent_places": list(Place.objects.recent()),
        "recent_dates": Image.recent_date_displays(),
        "position": position,
        "total": total,
        "prev_id": prev_id,
        "next_id": next_id,
        "prev_box_image": prev_box_image,
        "next_box_image": next_box_image,
        "conflict": conflict,
        "error": error,
        "precisions": Image._meta.get_field("date_precision").choices,
        "request": request,
    }


def _resolve_place(value, *, user):
    raw = value.strip()
    if raw == "":
        return None
    existing = Place.objects.filter(name__iexact=raw).first()
    if existing is not None:
        return existing
    place = Place(name=raw)
    place.save(user=user)
    return place


def _render_fragment(request, image, *, status=200, conflict=False, error=None):
    response = render(
        request,
        "core/_image_metadata.html",
        _metadata_context(image, request, conflict=conflict, error=error),
        status=status,
    )
    if status >= 400:
        response["HX-Reswap"] = "outerHTML"
        response["HX-Retarget"] = f"#image-form-{image.pk}"
    if conflict:
        response["X-Version-Conflict"] = "true"
    return response


@login_required
def image_detail(request, box_uuid, image_id):
    image = get_object_or_404(
        Image.objects.select_related("box", "place"), pk=image_id, box__uuid=box_uuid
    )
    if image.box.archived:
        return redirect("box_grid", box_uuid=image.box.uuid)
    context = _metadata_context(image, request)
    return render(request, "core/detail.html", context)


GRID_FILTERS = (
    ("all", "Alle"),
    ("untagged", "Ungetaggt"),
    ("place-todo", "Ort unklar"),
    ("date-todo", "Datum unklar"),
    ("flip-todo", "Spiegeln"),
    ("edit-todo", "Lightroom"),
    ("has-description", "Mit Beschreibung"),
    ("any-todo", "Offene Todos"),
)

GRID_FILTER_KEYS = {key for key, _ in GRID_FILTERS}


def _apply_grid_filter(qs, key):
    if key == "untagged":
        return qs.filter(
            place__isnull=True,
            latitude__isnull=True,
            date_earliest__isnull=True,
            date_latest__isnull=True,
        )
    if key == "place-todo":
        return qs.filter(
            Q(place_todo=True) | Q(place__isnull=True, latitude__isnull=True)
        )
    if key == "date-todo":
        return qs.filter(
            Q(date_todo=True) | Q(date_earliest__isnull=True, date_latest__isnull=True)
        )
    if key == "flip-todo":
        return qs.filter(needs_flip=True)
    if key == "edit-todo":
        return qs.exclude(edit_todo="")
    if key == "has-description":
        return qs.exclude(description="")
    if key == "any-todo":
        return qs.filter(
            Q(place_todo=True)
            | Q(place__isnull=True, latitude__isnull=True)
            | Q(date_todo=True)
            | Q(date_earliest__isnull=True, date_latest__isnull=True)
            | Q(needs_flip=True)
            | ~Q(edit_todo="")
        )
    return qs


GALLERY_FILTERS = (
    ("all", "Alle"),
    ("no-date", "Ohne Datum"),
    ("has-date", "Mit Datum"),
    ("untagged", "Ungetaggt"),
    ("place-todo", "Ort unklar"),
    ("date-todo", "Datum unklar"),
    ("flip-todo", "Spiegeln"),
    ("edit-todo", "Lightroom"),
    ("has-description", "Mit Beschreibung"),
    ("any-todo", "Offene Todos"),
)

GALLERY_FILTER_KEYS = {key for key, _ in GALLERY_FILTERS}

GALLERY_SORTS = (
    ("date", "Datum aufsteigend"),
    ("date-desc", "Datum absteigend"),
    ("box", "Box"),
)

GALLERY_SORT_KEYS = {key for key, _ in GALLERY_SORTS}


def _apply_gallery_filter(qs, key):
    if key == "no-date":
        return qs.filter(date_earliest__isnull=True, date_latest__isnull=True)
    if key == "has-date":
        return qs.exclude(date_earliest__isnull=True)
    return _apply_grid_filter(qs, key)


def _apply_gallery_sort(qs, key):
    box_tiebreak = ("box__sort_order", "box__name", "sequence_in_box")
    if key == "date-desc":
        return qs.order_by(F("date_earliest").desc(nulls_last=True), *box_tiebreak)
    if key == "box":
        return qs.order_by(*box_tiebreak)
    return qs.order_by(F("date_earliest").asc(nulls_last=True), *box_tiebreak)


def _gallery_places(base_qs):
    place_ids = set(
        base_qs.exclude(place__isnull=True).values_list("place_id", flat=True)
    )
    return list(Place.objects.filter(pk__in=place_ids).order_by("name"))


def _resolve_gallery_place(raw, places):
    if raw == "none":
        return "none"
    try:
        pk = int(raw)
    except (TypeError, ValueError):
        return "all"
    if any(place.pk == pk for place in places):
        return pk
    return "all"


def _apply_gallery_place(qs, active_place):
    if active_place == "none":
        return qs.filter(place__isnull=True)
    if isinstance(active_place, int):
        return qs.filter(place_id=active_place)
    return qs


@login_required
def gallery(request):
    raw_filter = request.GET.get("filter", "all")
    active_filter = raw_filter if raw_filter in GALLERY_FILTER_KEYS else "all"
    raw_sort = request.GET.get("sort", "date")
    active_sort = raw_sort if raw_sort in GALLERY_SORT_KEYS else "date"
    base_qs = Image.objects.select_related("box", "place").filter(box__archived=False)
    total_count = base_qs.count()
    places = _gallery_places(base_qs)
    active_place = _resolve_gallery_place(request.GET.get("place", "all"), places)
    filtered = _apply_gallery_place(
        _apply_gallery_filter(base_qs, active_filter), active_place
    )
    ordered = _apply_gallery_sort(filtered, active_sort)
    return render(
        request,
        "core/gallery.html",
        {
            "images": ordered,
            "filters": GALLERY_FILTERS,
            "sorts": GALLERY_SORTS,
            "places": places,
            "active_filter": active_filter,
            "active_sort": active_sort,
            "active_place": active_place,
            "total_count": total_count,
            "recent_places": list(Place.objects.recent()),
            "recent_dates": Image.recent_date_displays(),
        },
    )


@login_required
def box_grid(request, box_uuid):
    box = get_object_or_404(Box, uuid=box_uuid)
    raw_filter = request.GET.get("filter", "all")
    active_filter = raw_filter if raw_filter in GRID_FILTER_KEYS else "all"
    images = box.images.select_related("place").order_by("sequence_in_box")
    first_image = images.first()
    filtered_images = _apply_grid_filter(images, active_filter)
    return render(
        request,
        "core/grid.html",
        {
            "box": box,
            "images": filtered_images,
            "first_image": first_image,
            "filters": GRID_FILTERS,
            "active_filter": active_filter,
            "total_count": box.images.count(),
            "tile_clickable": not box.archived,
            "recent_places": list(Place.objects.recent()),
            "recent_dates": Image.recent_date_displays(),
        },
    )


@login_required
@require_http_methods(["PATCH", "POST"])
def image_save(request, image_id):
    data = _get_request_data(request)

    expected_version, version_error = _parse_if_match(request)
    if version_error is not None:
        return version_error

    try:
        updates = parse_metadata_payload(data)
    except MetadataError as err:
        image = get_object_or_404(
            Image.objects.select_related("box", "place"), pk=image_id
        )
        return _render_fragment(request, image, status=400, error=str(err))

    with transaction.atomic():
        try:
            locked = (
                Image.objects.select_related("box", "place")
                .select_for_update()
                .get(pk=image_id)
            )
        except Image.DoesNotExist:
            return HttpResponse("Bild nicht gefunden.", status=404)

        if locked.box and locked.box.archived:
            return HttpResponseForbidden("Box ist archiviert.")

        if "place" in data:
            place = _resolve_place(data["place"], user=request.user)
            updates["place_id"] = place.pk if place else None

        if "description" in updates:
            updates["description"] = stamp_description(
                old=locked.description,
                new=updates["description"],
                author_name=request.user.name or request.user.username,
                today=timezone.localdate(),
            )

        return _commit_image_updates(request, locked, expected_version, updates)


def _parse_if_match(request):
    """Return ``(expected_version, None)`` or ``(None, error_response)``.

    Drives optimistic-concurrency checks: every write to an image carries the
    version it is editing in the ``If-Match`` header.
    """
    raw = request.headers.get("If-Match")
    if raw is None:
        return None, HttpResponse("If-Match header fehlt.", status=428)
    try:
        return int(raw), None
    except ValueError:
        return None, HttpResponse("If-Match header ungültig.", status=428)


def _diff_updates(image, updates):
    changed = {}
    for key, value in updates.items():
        stored = getattr(image, key)
        if stored != value:
            changed[key] = value
    return changed


def apply_image_updates(locked, updates, *, user, expected_version):
    """Persist ``updates`` to an already-locked image with version checking.

    Returns ``"noop"`` when nothing changed, ``"conflict"`` when the optimistic
    version check fails (the row was modified concurrently), or ``"ok"`` on a
    successful write. On success and on conflict ``locked`` is refreshed from
    the database. Must be called inside the transaction that holds the
    ``select_for_update`` lock on ``locked``.
    """
    changed = _diff_updates(locked, updates)
    if not changed:
        return "noop"

    before = locked._snapshot()
    rowcount = Image.objects.filter(pk=locked.pk, version=expected_version).update(
        **changed, version=F("version") + 1, updated_at=timezone.now()
    )
    if rowcount == 0:
        locked.refresh_from_db()
        return "conflict"

    locked.refresh_from_db()
    after = locked._snapshot()
    changed_keys = [k for k in after if before.get(k) != after.get(k)]
    locked.log_action(
        "image.change",
        user=user,
        before={k: before[k] for k in changed_keys},
        after={k: after[k] for k in changed_keys},
    )
    return "ok"


def _commit_image_updates(request, locked, expected_version, updates):
    """Persist ``updates`` for the web UI and re-render the metadata fragment.

    Wraps :func:`apply_image_updates`: a noop or success re-renders the current
    state, a version clash renders the 409 conflict fragment.
    """
    result = apply_image_updates(
        locked, updates, user=request.user, expected_version=expected_version
    )
    if result == "conflict":
        return _render_fragment(request, locked, status=409, conflict=True)
    return _render_fragment(request, locked)


@login_required
@require_POST
def image_batch(request):
    raw_ids = request.POST.getlist("image_ids")
    image_ids = []
    for raw in raw_ids:
        try:
            image_ids.append(int(raw))
        except ValueError:
            return JsonResponse({"error": "Ungültige Bild-ID im Batch."}, status=400)
    if not image_ids:
        return JsonResponse(
            {"error": "Mindestens ein Bild muss ausgewählt sein."}, status=400
        )

    try:
        action, updates = parse_batch_payload(request.POST)
    except MetadataError as err:
        return JsonResponse({"error": str(err)}, status=400)

    with transaction.atomic():
        images = list(
            Image.objects.select_for_update()
            .select_related("box", "place")
            .filter(pk__in=image_ids)
        )
        if len(images) != len(set(image_ids)):
            return JsonResponse(
                {"error": "Einige Bilder wurden nicht gefunden."}, status=400
            )
        if any(image.box is None or image.box.archived for image in images):
            return JsonResponse(
                {"error": "Auswahl enthält archivierte oder unsortierte Bilder."},
                status=403,
            )

        if action == "place":
            place = _resolve_place(updates["place"], user=request.user)
            updates = {"place": place}

        updated = 0
        for image in images:
            changed = False
            for field, value in updates.items():
                if getattr(image, field) != value:
                    setattr(image, field, value)
                    changed = True
            if not changed:
                continue
            image.save(user=request.user)
            updated += 1

    return JsonResponse({"updated": updated, "action": action})


@login_required
def image_fragment(request, image_id):
    image = get_object_or_404(Image.objects.select_related("box", "place"), pk=image_id)
    return _render_fragment(request, image)


class _ImmichApplyError(Exception):
    """User-facing error raised while pulling metadata from an Immich photo."""


def _immich_updates(request, image):
    """Build the field updates for an Immich-apply request.

    A request carrying ``clear`` removes the slide's direct coordinates. Any
    other request resolves the pasted ``immich_link`` to an asset, fetches it,
    and lifts out the capture date and GPS coordinates. Pulling a date clears
    the "Datum unklar" flag and pulling coordinates clears "Ort unklar", since
    those values are now known. Raises :class:`_ImmichApplyError` with a German
    message for any user-facing failure.
    """
    if request.POST.get("clear"):
        if not image.has_coords:
            return {}
        return {"latitude": None, "longitude": None}

    if not request.user.has_immich_configured:
        raise _ImmichApplyError("Bitte zuerst einen Immich-API-Schlüssel hinterlegen.")
    if not settings.IMMICH_BASE_URL:
        raise _ImmichApplyError("Immich-Server ist nicht konfiguriert.")

    asset_id = parse_immich_asset_id(request.POST.get("immich_link", ""))
    if asset_id is None:
        raise _ImmichApplyError("Kein gültiger Immich-Link erkannt.")

    client = ImmichClient(settings.IMMICH_BASE_URL, request.user.immich_api_key)
    try:
        asset = client.get_asset(asset_id)
    except ImmichError:
        raise _ImmichApplyError(
            "Immich-Foto konnte nicht geladen werden. Stimmt der Link?"
        ) from None

    meta = extract_immich_metadata(asset)
    if meta.is_empty:
        raise _ImmichApplyError(
            "Im Immich-Foto sind weder Datum noch Standort hinterlegt."
        )

    updates = {}
    if meta.date is not None:
        try:
            parsed = dateparse.parse(meta.date)
        except dateparse.ParseError as err:
            raise _ImmichApplyError(str(err)) from err
        updates.update(
            date_display=parsed.display,
            date_earliest=parsed.earliest,
            date_latest=parsed.latest,
            date_precision=parsed.precision,
            date_todo=False,
            # Keep the exact time+offset so the export round-trips it; clear any
            # stale value when the photo only carries a day.
            immich_capture_datetime=meta.capture_datetime or "",
        )
    if meta.latitude is not None:
        updates.update(
            latitude=meta.latitude, longitude=meta.longitude, place_todo=False
        )
    return updates


@login_required
@require_POST
def image_apply_immich(request, image_id):
    expected_version, version_error = _parse_if_match(request)
    if version_error is not None:
        return version_error

    image = get_object_or_404(Image.objects.select_related("box", "place"), pk=image_id)
    if image.box and image.box.archived:
        return HttpResponseForbidden("Box ist archiviert.")

    try:
        updates = _immich_updates(request, image)
    except _ImmichApplyError as err:
        return _render_fragment(request, image, status=400, error=str(err))

    with transaction.atomic():
        try:
            locked = (
                Image.objects.select_related("box", "place")
                .select_for_update()
                .get(pk=image_id)
            )
        except Image.DoesNotExist:
            return HttpResponse("Bild nicht gefunden.", status=404)

        return _commit_image_updates(request, locked, expected_version, updates)


_PRECISION_LABELS = {
    "exact": "Tag",
    "month": "Monat",
    "season": "Saison",
    "year": "Jahr",
    "range": "Zeitraum",
    "decade": "Jahrzehnt",
    "unknown": "unbekannt",
}


def _format_parsed(parsed):
    start = parsed.earliest
    end = parsed.latest
    label = _PRECISION_LABELS.get(parsed.precision, parsed.precision)
    if parsed.precision == "exact":
        summary = start.isoformat()
    elif parsed.precision == "month":
        summary = f"{start:%m/%Y}"
    elif parsed.precision == "year":
        summary = f"{start.year}"
    elif parsed.precision == "decade":
        summary = f"{start.year}–{end.year}"
    elif parsed.precision == "season":
        summary = f"{start:%m/%Y} – {end:%m/%Y}"
    else:
        summary = f"{start.year}–{end.year}"
    return {
        "earliest": start.isoformat(),
        "latest": end.isoformat(),
        "precision": parsed.precision,
        "precision_label": label,
        "display": parsed.display,
        "summary": summary,
    }


@login_required
def date_autocomplete(request):
    text = request.GET.get("q", "")
    parsed_payload = None
    error = None
    if text.strip():
        try:
            parsed_payload = _format_parsed(dateparse.parse(text))
        except dateparse.ParseError as err:
            error = str(err)
    suggestions = dateparse.word_suggestions(text.strip())
    return JsonResponse(
        {"parsed": parsed_payload, "error": error, "suggestions": suggestions}
    )


def _bump_last_poll(user, now):
    throttle_cutoff = now - timedelta(seconds=POLL_THROTTLE_SECONDS)
    if user.last_poll is not None and user.last_poll >= throttle_cutoff:
        return
    get_user_model().objects.filter(pk=user.pk).update(last_poll=now)
    user.last_poll = now


def _driver_payload(driver_state):
    active = driver_state.active_driver
    if active is None:
        return None
    current_box = driver_state.current_box
    return {
        "user": active.name or active.username,
        "box_uuid": str(current_box.uuid) if current_box is not None else None,
        "image_id": driver_state.current_image_id,
    }


def _progress_payload(box):
    data = box.progress
    total = data["total"]
    done = data["done"]
    return {"total": total, "tagged": data["tagged"], "open_todos": total - done}


@login_required
def state(request):
    now = timezone.now()
    _bump_last_poll(request.user, now)

    box = None
    box_uuid = request.GET.get("box", "").strip()
    if box_uuid:
        box = Box.objects.filter(uuid=box_uuid).first()

    driver_state = DriverState.objects.select_related(
        "driver", "current_box", "current_image"
    ).get(pk=1)

    versions = {}
    progress_data = None
    if box is not None:
        versions = {
            str(pk): version
            for pk, version in Image.objects.filter(box=box).values_list(
                "pk", "version"
            )
        }
        progress_data = _progress_payload(box)

    presence_cutoff = DriverState.presence_cutoff()
    active_users = list(
        get_user_model()
        .objects.filter(last_poll__gte=presence_cutoff)
        .order_by("name", "username")
        .values_list("name", flat=True)
    )

    return JsonResponse(
        {
            "driver": _driver_payload(driver_state),
            "versions": versions,
            "progress": progress_data,
            "active_users": active_users,
        }
    )


def _driver_state_snapshot():
    state_row = DriverState.objects.select_related(
        "driver", "current_box", "current_image"
    ).get(pk=1)
    return {"driver": _driver_payload(state_row)}


def _resolve_driver_targets(data):
    box = None
    image = None
    box_uuid = (data.get("box_uuid") or "").strip()
    if box_uuid:
        box = Box.objects.filter(uuid=box_uuid).first()
    image_id_raw = (data.get("image_id") or "").strip()
    if image_id_raw:
        try:
            image = Image.objects.filter(pk=int(image_id_raw)).first()
        except ValueError:
            image = None
    return box, image


def _release_driver_seat(user):
    with transaction.atomic():
        state_row = DriverState.objects.select_for_update().get(pk=1)
        if state_row.driver_id == user.pk:
            state_row.driver = None
            state_row.save()


@login_required
@require_http_methods(["POST", "DELETE"])
def driver_state(request):
    now = timezone.now()
    _bump_last_poll(request.user, now)

    data = _get_request_data(request)

    if request.method == "DELETE" or data.get("release") == "true":
        _release_driver_seat(request.user)
        return JsonResponse(_driver_state_snapshot())

    box, image = _resolve_driver_targets(data)
    if (box is not None and box.archived) or (
        image is not None and image.box and image.box.archived
    ):
        return HttpResponseForbidden("Box ist archiviert.")

    with transaction.atomic():
        state_row = (
            DriverState.objects.select_related("driver").select_for_update().get(pk=1)
        )
        active = state_row.active_driver
        if active is not None and active.pk != request.user.pk:
            return JsonResponse(
                {"error": "occupied", "driver": active.name or active.username},
                status=409,
            )
        state_row.driver = request.user
        if box is not None:
            state_row.current_box = box
        if image is not None:
            state_row.current_image = image
        state_row.save()

    return JsonResponse(_driver_state_snapshot())


@login_required
def place_autocomplete(request):
    q = request.GET.get("q", "").strip()
    qs = Place.objects.all()
    if q:
        qs = qs.filter(name__icontains=q)
    matches = sorted(
        qs[:100],
        key=lambda p: (
            0 if p.name.lower().startswith(q.lower()) else 1,
            p.name.lower(),
        ),
    )[:20]
    return JsonResponse(
        {
            "results": [
                {"id": p.pk, "name": p.name, "has_coords": p.has_coords}
                for p in matches
            ]
        }
    )


def _annotated_places():
    return Place.objects.annotate(image_count=Count("images")).order_by(
        Case(When(latitude__isnull=True, then=0), default=1), "name"
    )


@login_required
def place_list(request):
    return render(request, "core/place_list.html", {"places": _annotated_places()})


@login_required
@require_POST
def place_set_coords(request, pk):
    place = get_object_or_404(Place, pk=pk)
    raw = request.POST.get("raw", "").strip()
    error = None
    if not raw:
        error = "Bitte einen Link oder Koordinaten eingeben."
    else:
        coords = parse_coordinates(raw)
        if coords is None:
            error = "Konnte keine Koordinaten erkennen."
        else:
            lat, lng = coords
            if place.latitude != lat or place.longitude != lng:
                place.latitude = lat
                place.longitude = lng
                place.save(user=request.user)
    place.image_count = place.images.count()
    return render(request, "core/_place_row.html", {"place": place, "error": error})


@login_required
@_upload_required
def box_edit(request, box_uuid=None):
    box = None
    if box_uuid is not None:
        box = get_object_or_404(Box, uuid=box_uuid)
        if box.archived:
            messages.error(request, "Archivierte Boxen können nicht bearbeitet werden.")
            return redirect("box_grid", box_uuid=box.uuid)

    if request.method == "POST":
        form = BoxForm(request.POST, instance=box)
        if form.is_valid():
            saved = form.save(commit=False)
            if box is None:
                saved.sort_order = _next_box_sort_order()
            saved.save(user=request.user)
            messages.success(request, "Box gespeichert.")
            return redirect("box_grid", box_uuid=saved.uuid)
    else:
        form = BoxForm(instance=box)

    return render(request, "core/box_edit.html", {"form": form, "box": box})


@login_required
@_staff_required
def box_archive(request, box_uuid):
    box = get_object_or_404(Box, uuid=box_uuid)
    if box.archived:
        return redirect("box_grid", box_uuid=box.uuid)

    form = BoxArchiveForm(box=box)
    if request.method == "POST":
        form = BoxArchiveForm(request.POST, box=box)
        if form.is_valid():
            if not box.immich_complete:
                messages.error(
                    request, "Box muss zuerst vollständig zu Immich hochgeladen werden."
                )
            else:
                try:
                    box.archive(user=request.user)
                except ValueError as err:
                    messages.error(request, str(err))
                else:
                    messages.success(request, f"Box „{box.name}“ archiviert.")
                    return redirect("box_grid", box_uuid=box.uuid)

    images = box.images.select_related("place").order_by("sequence_in_box")
    open_todos = [image for image in images if image.has_open_todos()]
    return render(
        request,
        "core/box_archive.html",
        {
            "box": box,
            "form": form,
            "progress": box.progress,
            "can_archive": box.can_archive,
            "open_todos": open_todos,
        },
    )


def _render_immich_status(request, box, *, message=None):
    return render(
        request,
        "core/_immich_status.html",
        {"box": box, "immich_message": message, "request": request},
    )


def _immich_finalize_rejection(request, box):
    if box.archived:
        return "Archivierte Box kann nicht hochgeladen werden."
    if not request.user.has_immich_configured:
        return "Bitte zuerst einen Immich-API-Schlüssel hinterlegen."
    if not settings.IMMICH_BASE_URL:
        return "Immich-Server ist nicht konfiguriert."
    if any(image.has_open_todos() for image in box.images.all()):
        return "Box hat noch offene Aufgaben."
    if box.immich_state == ImmichState.IN_PROGRESS:
        return "Upload läuft bereits."
    if not box.images.exists():
        return "Box enthält keine Bilder."
    return None


@login_required
@_immich_required
@require_POST
def box_immich_finalize(request, box_uuid):
    box = get_object_or_404(Box, uuid=box_uuid)

    rejection = _immich_finalize_rejection(request, box)
    if rejection is not None:
        return _render_immich_status(request, box, message=rejection)

    box.immich_state = ImmichState.IN_PROGRESS
    box.immich_error = ""
    box.save()
    finalize_box.enqueue(box.id, request.user.id)
    box.refresh_from_db()
    return _render_immich_status(request, box)


@login_required
@_immich_required
def box_immich_status(request, box_uuid):
    box = get_object_or_404(Box, uuid=box_uuid)
    return _render_immich_status(request, box)


@login_required
@_immich_required
@require_POST
def box_immich_retry(request, box_uuid):
    box = get_object_or_404(Box, uuid=box_uuid)

    if box.immich_state != ImmichState.FAILED:
        return _render_immich_status(
            request, box, message="Erneuter Versuch ist nur nach einem Fehler möglich."
        )
    if box.archived:
        return _render_immich_status(
            request, box, message="Archivierte Box kann nicht hochgeladen werden."
        )

    box.immich_state = ImmichState.IN_PROGRESS
    box.immich_error = ""
    box.save()
    finalize_box.enqueue(box.id, request.user.id)
    box.refresh_from_db()
    return _render_immich_status(request, box)


@login_required
@_superuser_required
@require_POST
def trigger_deploy(request):
    flag_path = getattr(settings, "DEPLOY_FLAG_FILE", "") or ""
    if not flag_path:
        messages.error(
            request, "Deploy ist nicht konfiguriert (DEPLOY_FLAG_FILE fehlt)."
        )
        if request.headers.get("HX-Request"):
            return HttpResponse(status=204, headers={"HX-Redirect": reverse("index")})
        return redirect("index")

    target = Path(flag_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{request.user.username} {timezone.now().isoformat()}\n")

    if request.headers.get("HX-Request"):
        return render(request, "core/_deploying.html")

    messages.success(
        request, "Deploy wurde angestoßen. Der Neustart erfolgt automatisch."
    )
    return redirect(request.META.get("HTTP_REFERER") or reverse("index"))


@login_required
def account_settings(request):
    user = request.user

    if request.method == "POST":
        if "generate_api_token" in request.POST:
            user.regenerate_api_token()
            messages.success(request, "Neuer API-Token erzeugt.")
            return redirect("account_settings")
        if "clear_api_token" in request.POST:
            user.clear_api_token()
            messages.success(request, "API-Token entfernt.")
            return redirect("account_settings")

        form = ImmichKeyForm(request.POST)
        if form.is_valid():
            key = form.cleaned_data["immich_api_key"].strip()
            if not key:
                user.immich_api_key = ""
                user.save(update_fields=["immich_api_key"])
                messages.success(request, "Immich-API-Schlüssel entfernt.")
                return redirect("account_settings")

            if not settings.IMMICH_BASE_URL:
                user.immich_api_key = key
                user.save(update_fields=["immich_api_key"])
                messages.warning(
                    request,
                    "Schlüssel gespeichert, aber der Immich-Server ist noch nicht "
                    "konfiguriert – der Schlüssel konnte nicht überprüft werden.",
                )
                return redirect("account_settings")

            client = ImmichClient(settings.IMMICH_BASE_URL, key)
            try:
                account = client.verify()
            except ImmichError:
                messages.error(
                    request,
                    "Der Immich-API-Schlüssel wurde abgelehnt. Bitte überprüfe "
                    "den Schlüssel und versuche es erneut.",
                )
            else:
                user.immich_api_key = key
                user.save(update_fields=["immich_api_key"])
                label = account.get("email") or account.get("name") or "Immich"
                messages.success(request, f"Mit Immich-Konto „{label}“ verbunden.")
                return redirect("account_settings")
    else:
        form = ImmichKeyForm(initial={"immich_api_key": user.immich_api_key})

    return render(
        request,
        "core/account_settings.html",
        {
            "form": form,
            "immich_base_url": settings.IMMICH_BASE_URL,
            "has_immich_configured": user.has_immich_configured,
            "api_token": user.api_token,
        },
    )


def healthz(request):
    return JsonResponse({"status": "ok"})
