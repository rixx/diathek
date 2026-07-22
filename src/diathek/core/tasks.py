from django.conf import settings
from django.tasks import task
from django.utils import timezone

from diathek.core.immich import ImmichClient, ImmichError
from diathek.core.immich_export import render_processed_image, sha1_hex
from diathek.core.models import Box, ImmichState, User


@task
def finalize_box(box_id, user_id):
    box = Box.objects.get(pk=box_id)
    user = User.objects.get(pk=user_id)

    if not user.immich_api_key:
        message = "Kein Immich-API-Schlüssel konfiguriert."
        box.immich_state = ImmichState.FAILED
        box.immich_error = message
        box.save()
        raise ValueError(message)

    if not settings.IMMICH_BASE_URL:
        message = "Immich-Server ist nicht konfiguriert."
        box.immich_state = ImmichState.FAILED
        box.immich_error = message
        box.save()
        raise ValueError(message)

    box.immich_state = ImmichState.IN_PROGRESS
    box.immich_error = ""
    box.save()

    try:
        client = ImmichClient(settings.IMMICH_BASE_URL, user.immich_api_key)
        album = client.get_or_create_album(f"diathek-{box.name}")

        images = list(box.images.all().order_by("sequence_in_box"))
        asset_ids = []
        for image in images:
            if image.immich_is_current:
                asset_ids.append(image.immich_asset_id)
                continue

            tmp = render_processed_image(image)
            try:
                checksum = sha1_hex(tmp)
                result = client.upload_asset(
                    file_bytes=tmp.read_bytes(),
                    filename=image.filename,
                    device_asset_id=str(image.uuid),
                    device_id="diathek",
                    file_created_at=image.created_at.isoformat(),
                    file_modified_at=image.created_at.isoformat(),
                    checksum=checksum,
                )
            finally:
                tmp.unlink(missing_ok=True)

            image.immich_asset_id = result["id"]
            image.immich_checksum = checksum
            image.immich_signature = image.compute_immich_signature()
            image.immich_uploaded_at = timezone.now()
            image.immich_owner = user
            image.save(skip_log=True, bump_version=False)
            asset_ids.append(image.immich_asset_id)

        if asset_ids:
            client.add_to_album(album["id"], asset_ids)

        to_verify = [img for img in images if img.immich_checksum]
        if to_verify:
            results = client.bulk_check(
                [
                    {"id": str(img.uuid), "checksum": img.immich_checksum}
                    for img in to_verify
                ]
            )
            missing = sum(1 for entry in results if entry["action"] == "accept")
            if missing:
                raise ImmichError(  # noqa: TRY301
                    f"{missing} von {len(to_verify)} Bildern fehlen in Immich."
                )

        box.immich_state = ImmichState.UPLOADED
        box.immich_album_url = client.album_web_url(album["id"])
        box.save()
        box.log_action(
            "box.immich_push",
            user=user,
            after={"image_count": len(images), "album_url": box.immich_album_url},
        )
    except Exception as exc:
        box.immich_state = ImmichState.FAILED
        box.immich_error = str(exc)
        box.save()
        raise
