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
from decimal import Decimal

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
# Both `/photos/<id>` (direct link) and `/albums/<id>/photos/<id>` (album link)
# put the asset id straight after the final `/photos/` segment.
_PHOTOS_RE = re.compile(rf"/photos/({_UUID})")
_BARE_RE = re.compile(rf"^\s*({_UUID})\s*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


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

    @property
    def is_empty(self) -> bool:
        return self.date is None and self.latitude is None


def extract_immich_metadata(asset: dict | None) -> ImmichMetadata:
    """Read the capture date and coordinates from an Immich asset payload.

    ``date`` is the ``YYYY-MM-DD`` portion of ``exifInfo.dateTimeOriginal`` (or
    ``None`` when absent or malformed); it is handed to the regular date parser
    by the caller. Coordinates are quantised to six decimal places to match the
    ``Place`` model and are only returned when both latitude and longitude are
    present.
    """
    exif = (asset or {}).get("exifInfo") or {}

    raw_date = exif.get("dateTimeOriginal")
    date = None
    if isinstance(raw_date, str) and _DATE_RE.match(raw_date):
        date = raw_date[:10]

    latitude = longitude = None
    lat = exif.get("latitude")
    lng = exif.get("longitude")
    if lat is not None and lng is not None:
        latitude = _quantize(lat)
        longitude = _quantize(lng)

    return ImmichMetadata(date=date, latitude=latitude, longitude=longitude)


def _quantize(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"))
