"""Extract latitude/longitude from a pasted Google Maps URL or a plain pair.

Pure Python, no Django imports. The user flow: paste a Google Maps link into
the place form and have the coordinates lifted out automatically. We also
accept a bare ``lat, lng`` pair so users can type coordinates directly.
"""

from __future__ import annotations

import re
from decimal import Decimal

PIN_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
AT_RE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
PAIR_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_coordinates(text: str) -> tuple[Decimal, Decimal] | None:
    """Return (lat, lng) parsed from ``text`` or ``None`` if nothing matches.

    Priority: the ``!3d…!4d…`` pair (the actual pin in Google Maps data blobs)
    wins over the ``@lat,lng`` map-centre (which points at the viewport, not
    the pin). Plain ``lat, lng`` input is accepted as a last resort.
    """
    if not text:
        return None

    for regex in (PIN_RE, AT_RE):
        match = regex.search(text)
        if match:
            coords = _to_decimals(match.group(1), match.group(2))
            if coords is not None:
                return coords

    match = PAIR_RE.match(text)
    if match:
        coords = _to_decimals(match.group(1), match.group(2))
        if coords is not None:
            return coords

    return None


def _to_decimals(lat_raw: str, lng_raw: str) -> tuple[Decimal, Decimal] | None:
    lat = Decimal(lat_raw)
    lng = Decimal(lng_raw)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat.quantize(Decimal("0.000001")), lng.quantize(Decimal("0.000001"))
