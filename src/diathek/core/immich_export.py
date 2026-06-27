"""Turn an :class:`Image` into a processed temp file ready for Immich upload.

Django-aware glue around the pure ``build_exiftool_args`` builder: it reads the
stored original bytes, copies them to a temp file, and shells out to
``exiftool`` to embed the EXIF/IPTC/XMP tags in place. The caller owns the
returned temp file and must delete it once the upload finishes.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

from django.core.files.storage import default_storage

from diathek.metadata.immich_exif import build_exiftool_args


class ExiftoolError(Exception):
    """Raised when the exiftool subprocess fails or is unavailable."""


def build_args_for_image(image):
    place = image.place
    if image.has_coords:
        latitude, longitude = image.latitude, image.longitude
    elif place is not None:
        latitude, longitude = place.latitude, place.longitude
    else:
        latitude, longitude = None, None
    return build_exiftool_args(
        date_representative=image.date_representative(),
        date_display=image.date_display,
        description=image.description,
        place_name=place.name if place else None,
        latitude=latitude,
        longitude=longitude,
        needs_flip=image.needs_flip,
    )


def render_processed_image(image):
    """Return a temp file Path holding the original bytes with metadata embedded.

    Raises :class:`ValueError` if there is no stored original, and
    :class:`ExiftoolError` if exiftool fails or is missing. The temp file is
    deleted on failure; the caller must delete it on success.
    """
    if not image.image:
        raise ValueError("Image has no stored original to process.")

    suffix = Path(image.image.name).suffix
    with default_storage.open(image.image.name, "rb") as source:
        original_bytes = source.read()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(original_bytes)
        tmp_path = Path(handle.name)

    args = build_args_for_image(image)
    command = ["exiftool", *args, "-overwrite_original", str(tmp_path)]
    try:
        subprocess.run(command, check=True, capture_output=True)  # noqa: S603
    except FileNotFoundError as exc:
        tmp_path.unlink(missing_ok=True)
        raise ExiftoolError("exiftool is not installed or not on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        tmp_path.unlink(missing_ok=True)
        stderr = exc.stderr.decode("utf-8", "replace").strip() if exc.stderr else ""
        message = "exiftool failed"
        if stderr:
            message = f"{message}: {stderr}"
        raise ExiftoolError(message) from exc

    return tmp_path


def sha1_hex(path):
    """Return the SHA-1 hex digest of the file at ``path`` (Immich dedup key)."""
    digest = hashlib.sha1()  # noqa: S324
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
