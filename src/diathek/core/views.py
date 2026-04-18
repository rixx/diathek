from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F, Max
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from PIL import UnidentifiedImageError

from diathek.core.forms import ImportForm, RegistrationForm
from diathek.core.metadata import MetadataError, parse_metadata_payload
from diathek.core.models import Box, Image, InviteCode, Place
from diathek.core.thumbnails import build_assets
from diathek.metadata import dateparse
from diathek.metadata.description import stamp_description


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


@login_required
def index(request):
    active_boxes = Box.objects.filter(archived=False).order_by("sort_order", "name")
    unsorted_count = Image.objects.filter(box__isnull=True).count()
    return render(
        request,
        "core/index.html",
        {"boxes": active_boxes, "unsorted_count": unsorted_count},
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


def _resolve_target_box(form, user):
    choice = form.cleaned_data["box_choice"]
    if choice == ImportForm.BOX_UNSORTED:
        return None
    if choice == ImportForm.BOX_NEW:
        box = Box(
            name=form.cleaned_data["new_box_name"],
            description=form.cleaned_data.get("new_box_description") or "",
        )
        box.save(user=user)
        return box
    return Box.objects.get(pk=int(choice), archived=False)


def _save_image_files(image, original_bytes, original_name, assets):
    image.image.save(original_name, ContentFile(original_bytes), save=False)
    image.thumb_small.save(f"{image.uuid}.webp", assets.thumb_small, save=False)
    if assets.thumb_detail is not None:
        image.thumb_detail.save(f"{image.uuid}.webp", assets.thumb_detail, save=False)


@login_required
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

            start_sequence = Image.next_sequence_for(target_box)
            created = []
            skipped_hash = []
            offset = 0
            for uploaded in ordered:
                raw = uploaded.read()
                try:
                    assets = build_assets(raw)
                except (UnidentifiedImageError, OSError):
                    raise _ImportError(
                        f"Datei {uploaded.name} ist kein gültiges Bild."
                    ) from None

                if (
                    target_box is not None
                    and Image.objects.filter(
                        box=target_box, content_hash=assets.content_hash
                    ).exists()
                ):
                    skipped_hash.append(uploaded.name)
                    continue
                if (
                    target_box is None
                    and Image.objects.filter(
                        box__isnull=True, content_hash=assets.content_hash
                    ).exists()
                ):
                    skipped_hash.append(uploaded.name)
                    continue

                image = Image(
                    box=target_box,
                    filename=uploaded.name,
                    sequence_in_box=(
                        start_sequence + offset if target_box is not None else None
                    ),
                    content_hash=assets.content_hash,
                    file_size=assets.file_size,
                    width=assets.width,
                    height=assets.height,
                )
                _save_image_files(image, raw, uploaded.name, assets)
                image.save(user=request.user)
                created.append(image)
                if target_box is not None:
                    offset += 1
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


@login_required
def unsorted_view(request):
    images = Image.objects.filter(box__isnull=True).order_by("filename")
    active_boxes = Box.objects.filter(archived=False).order_by("sort_order", "name")
    return render(
        request, "core/unsorted.html", {"images": images, "boxes": active_boxes}
    )


@login_required
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


def _metadata_context(image, request, *, conflict=False, error=None):
    position, total, prev_id, next_id = _neighbours(image)
    return {
        "image": image,
        "box": image.box,
        "recent_places": list(Place.objects.recent()),
        "recent_dates": Image.recent_date_displays(),
        "position": position,
        "total": total,
        "prev_id": prev_id,
        "next_id": next_id,
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
        return redirect("index")
    context = _metadata_context(image, request)
    return render(request, "core/detail.html", context)


@login_required
@require_http_methods(["PATCH", "POST"])
def image_save(request, image_id):
    data = _get_request_data(request)

    expected_version_raw = request.headers.get("If-Match")
    if expected_version_raw is None:
        return HttpResponse("If-Match header fehlt.", status=428)
    try:
        expected_version = int(expected_version_raw)
    except ValueError:
        return HttpResponse("If-Match header ungültig.", status=428)

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

        changed = _diff_updates(locked, updates)
        if not changed:
            return _render_fragment(request, locked)

        before = locked._snapshot()

        rowcount = Image.objects.filter(pk=image_id, version=expected_version).update(
            **changed, version=F("version") + 1, updated_at=timezone.now()
        )
        if rowcount == 0:
            locked.refresh_from_db()
            return _render_fragment(request, locked, status=409, conflict=True)

        locked.refresh_from_db()
        after = locked._snapshot()
        changed_keys = [k for k in after if before.get(k) != after.get(k)]
        locked.log_action(
            "image.change",
            user=request.user,
            before={k: before[k] for k in changed_keys},
            after={k: after[k] for k in changed_keys},
        )

    return _render_fragment(request, locked)


def _diff_updates(image, updates):
    changed = {}
    for key, value in updates.items():
        stored = getattr(image, key)
        if stored != value:
            changed[key] = value
    return changed


@login_required
def image_fragment(request, image_id):
    image = get_object_or_404(Image.objects.select_related("box", "place"), pk=image_id)
    return _render_fragment(request, image)


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
