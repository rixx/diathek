"""⁂ Pure helpers for the Immich edit round-trip (Lightroom flow).

No Django imports. Two responsibilities:

* match uploaded (edited) filenames to their source assets in Immich, and
* snapshot the descriptive metadata of a source asset in the exact shape that
  Immich's ``updateAsset`` endpoint accepts, so it can be re-applied to the
  replacement asset.

The web views glue these to the Immich API client; nothing here touches the
network or the database, so it stays unit-testable.
"""

from __future__ import annotations

from pathlib import PurePath


def match_edit_filenames(filenames, sources):
    """⁂ Match each uploaded filename to exactly one source asset.

    ``sources`` are Immich asset payloads (dicts with at least ``id`` and
    ``originalFileName``). Matching is by filename stem, case-insensitive and
    extension-ignored, so an edited ``scan_001.jpg`` finds its ``scan_001.CR2``
    source. Returns ``(matched, unmatched, ambiguous)`` where ``matched`` maps
    filename → source asset and the other two are lists of filenames.
    Sources appearing more than once (the same photo link pasted twice) are
    de-duplicated by asset id; two *different* assets sharing a stem make every
    filename with that stem ambiguous.
    """
    by_stem = {}
    for source in sources:
        stem = _stem(source.get("originalFileName") or "")
        if not stem:
            continue
        candidates = by_stem.setdefault(stem, {})
        candidates[source["id"]] = source

    matched = {}
    unmatched = []
    ambiguous = []
    for filename in filenames:
        candidates = by_stem.get(_stem(filename), {})
        if not candidates:
            unmatched.append(filename)
        elif len(candidates) > 1:
            ambiguous.append(filename)
        else:
            matched[filename] = next(iter(candidates.values()))
    return matched, unmatched, ambiguous


def extract_edit_metadata(asset: dict) -> dict:
    """⁂ Snapshot a source asset's descriptive metadata for ``updateAsset``.

    Pulls the fields the plan carries over — capture time, description, GPS,
    rating, favourite flag, and visibility — from the authoritative asset
    payload, keyed exactly as ``PUT /assets/{id}`` expects them. Absent values
    are omitted rather than sent as ``null`` so the replacement asset keeps
    whatever Immich derives from the uploaded file for those fields.
    """
    exif = asset.get("exifInfo") or {}
    candidates = {
        "dateTimeOriginal": exif.get("dateTimeOriginal"),
        "description": exif.get("description"),
        "latitude": exif.get("latitude"),
        "longitude": exif.get("longitude"),
        "rating": exif.get("rating"),
        "isFavorite": asset.get("isFavorite"),
        "visibility": asset.get("visibility"),
    }
    return {key: value for key, value in candidates.items() if value is not None}


def _stem(name: str) -> str:
    return PurePath(name).stem.casefold()
