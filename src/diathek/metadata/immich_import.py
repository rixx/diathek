"""Pull date and location out of an Immich asset reference.

Pure Python, no Django imports. Two responsibilities:

* turn a pasted Immich photo link (or bare asset id) into an asset UUID, and
* read the capture date and GPS coordinates out of an Immich asset payload.

The web view glues these together: parse the link, fetch the asset via the
Immich API, then apply the extracted values to the current slide. Nothing here
touches the network or the database, so it stays unit-testable.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
# Both `/photos/<id>` (direct link) and `/albums/<id>/photos/<id>` (album link)
# put the asset id straight after the final `/photos/` segment.
_PHOTOS_RE = re.compile(rf"/photos/({_UUID})")
_BARE_RE = re.compile(rf"^\s*({_UUID})\s*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
# Immich's ``timeZone`` field is either an IANA name (``Europe/Berlin``) or a
# bare offset spelled ``UTC+2`` / ``UTC+02:00`` / ``GMT-5:30`` / plain ``UTC``.
_OFFSET_RE = re.compile(
    r"^(?:UTC|GMT)\s*(?:([+-])(\d{1,2})(?::?(\d{2}))?)?$", re.IGNORECASE
)


def parse_immich_asset_id(text: str) -> str | None:
    """Return the asset UUID referenced by ``text`` or ``None``.

    Accepts full Immich web links such as
    ``https://host/albums/<album>/photos/<asset>`` and
    ``https://host/photos/<asset>`` as well as a bare asset UUID. The id is
    lower-cased so it matches Immich's canonical form.
    """
    if not text:
        return None
    match = _PHOTOS_RE.search(text)
    if match is None:
        match = _BARE_RE.match(text)
    if match is None:
        return None
    return match.group(1).lower()


@dataclasses.dataclass(frozen=True)
class ImmichMetadata:
    date: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    capture_datetime: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.date is None and self.latitude is None


def extract_immich_metadata(asset: dict | None) -> ImmichMetadata:
    """Read the capture date and coordinates from an Immich asset payload.

    ``date`` is the local capture day (``YYYY-MM-DD``) and ``capture_datetime``
    the full local wall-clock timestamp *with* its UTC offset, both derived from
    ``exifInfo.dateTimeOriginal`` and ``exifInfo.timeZone``. Immich serialises
    ``dateTimeOriginal`` as an absolute instant (UTC) and keeps the original zone
    in ``timeZone``; we recombine them exactly the way Immich does so the value
    we later bake back into the exported file round-trips to the same instant and
    offset. ``date`` is handed to the regular date parser by the caller and is
    ``None`` when the timestamp is absent or malformed. Coordinates are quantised
    to six decimal places to match the ``Place`` model and are only returned when
    both latitude and longitude are present.
    """
    exif = (asset or {}).get("exifInfo") or {}

    raw_date = exif.get("dateTimeOriginal")
    date = None
    capture_datetime = None
    if isinstance(raw_date, str) and _DATE_RE.match(raw_date):
        local = _local_capture(raw_date, exif.get("timeZone"))
        if local is not None:
            date = local.date().isoformat()
            capture_datetime = local.isoformat()
        else:
            date = raw_date[:10]

    latitude = longitude = None
    lat = exif.get("latitude")
    lng = exif.get("longitude")
    if lat is not None and lng is not None:
        latitude = _quantize(lat)
        longitude = _quantize(lng)

    return ImmichMetadata(
        date=date,
        latitude=latitude,
        longitude=longitude,
        capture_datetime=capture_datetime,
    )


def _local_capture(raw_date: str, time_zone) -> datetime | None:
    """Recombine Immich's UTC instant and ``timeZone`` into a local datetime.

    Mirrors Immich's own ``mergeTimeZone``: the instant is parsed as UTC (a naive
    string is treated as UTC), then re-expressed in the asset's zone so the wall
    clock and offset match what the photo was actually taken with. Returns
    ``None`` for a timestamp that is not a real ISO datetime.
    """
    try:
        parsed = datetime.fromisoformat(raw_date)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    target = _resolve_timezone(time_zone)
    if target is None:
        target = parsed.tzinfo
    return parsed.astimezone(target)


def _resolve_timezone(time_zone):
    """Turn Immich's ``timeZone`` string into a tzinfo, or ``None`` if unusable."""
    if not isinstance(time_zone, str) or not time_zone.strip():
        return None
    value = time_zone.strip()
    match = _OFFSET_RE.match(value)
    if match is not None:
        sign, hours, minutes = match.groups()
        if sign is None:
            return UTC
        delta = timedelta(hours=int(hours), minutes=int(minutes or 0))
        return timezone(delta if sign == "+" else -delta)
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _quantize(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"))
