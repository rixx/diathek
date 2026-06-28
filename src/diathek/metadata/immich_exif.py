"""Build the ``exiftool`` argument list for embedding diathek metadata.

Pure Python, no Django imports and no I/O: this only assembles the list of
arguments that the caller hands to ``subprocess.run`` (alongside the exiftool
binary, the target file, and operational flags like ``-overwrite_original``).

The values written here are EXIF/IPTC/XMP tag contents. The UI is German, so
user-supplied text (descriptions, place names) is kept verbatim.
"""

from __future__ import annotations


def build_exiftool_args(
    *,
    date_representative=None,
    capture_datetime=None,
    date_display="",
    description="",
    place_name=None,
    latitude=None,
    longitude=None,
    needs_flip=False,
):
    """Return the exiftool argument list for one image's metadata.

    The list excludes the exiftool binary, the target file path, and
    operational flags. Each tag assignment is a single ``"-Tag=value"``
    element; the leading charset directive is the only two-element entry.

    When ``capture_datetime`` (a timezone-aware ``datetime``, e.g. pulled from an
    Immich photo) is given it wins: its exact wall-clock time and UTC offset are
    written so the exported file round-trips to the same instant. Otherwise a
    bare ``date_representative`` is written at local noon with no offset, the
    best we can do for a date we only know to day precision.
    """
    args = ["-charset", "IPTC=UTF8"]

    if capture_datetime is not None:
        stamp = f"{capture_datetime:%Y:%m:%d %H:%M:%S}"
        args.append(f"-DateTimeOriginal={stamp}")
        args.append(f"-CreateDate={stamp}")
        offset = _format_offset(capture_datetime)
        if offset is not None:
            # Cover every offset tag Immich has read across versions so the
            # re-import lands on the same zone.
            args.append(f"-OffsetTimeOriginal={offset}")
            args.append(f"-OffsetTimeDigitized={offset}")
            args.append(f"-OffsetTime={offset}")
    elif date_representative is not None:
        stamp = f"{date_representative:%Y:%m:%d} 12:00:00"
        args.append(f"-DateTimeOriginal={stamp}")
        args.append(f"-CreateDate={stamp}")

    caption_parts = [part.strip() for part in (date_display, description)]
    caption = "\n".join(part for part in caption_parts if part)
    if caption:
        args.append(f"-IPTC:Caption-Abstract={caption}")
        args.append(f"-XMP-dc:Description={caption}")
        args.append(f"-EXIF:UserComment={caption}")

    if place_name is not None and place_name.strip():
        name = place_name.strip()
        args.append(f"-IPTC:City={name}")
        args.append(f"-XMP-photoshop:City={name}")

    if latitude is not None and longitude is not None:
        args.append(f"-GPSLatitude={abs(latitude)}")
        args.append(f"-GPSLatitudeRef={'N' if latitude >= 0 else 'S'}")
        args.append(f"-GPSLongitude={abs(longitude)}")
        args.append(f"-GPSLongitudeRef={'E' if longitude >= 0 else 'W'}")

    if needs_flip:
        args.append("-Orientation#=2")

    return args


def _format_offset(value):
    """Return the ``±HH:MM`` UTC offset of ``value``, or ``None`` if naive."""
    raw = value.strftime("%z")
    if not raw:
        return None
    return f"{raw[:3]}:{raw[3:]}"
