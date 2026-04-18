"""Parsing of metadata-form POST data for the image save endpoint.

Kept separate from views so the parsing/validation can be tested in isolation.
"""

import datetime

from diathek.core.models import DatePrecision


class MetadataError(ValueError):
    """Raised when a field value fails validation."""


BOOL_FIELDS = ("place_todo", "date_todo", "needs_flip")
DATE_FIELDS = ("date_earliest", "date_latest")
TEXT_FIELDS = ("date_display", "edit_todo")
KNOWN_FIELDS = {
    *BOOL_FIELDS,
    *DATE_FIELDS,
    *TEXT_FIELDS,
    "place",
    "date_precision",
    "description",
}

_TRUE_VALUES = {"1", "true", "True", "on", "yes"}
_FALSE_VALUES = {"0", "false", "False", "off", "no", ""}


def _parse_bool(value):
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise MetadataError(f"Ungültiger Wahrheitswert: {value!r}")


def _parse_date(value):
    raw = value.strip()
    if raw == "":
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError as err:
        raise MetadataError(f"Ungültiges Datum: {value!r}") from err


_VALID_PRECISIONS = {choice for choice, _ in DatePrecision.choices} | {""}


def _parse_precision(value):
    if value not in _VALID_PRECISIONS:
        raise MetadataError(f"Ungültige Präzision: {value!r}")
    return value


def parse_metadata_payload(data):
    """Translate raw request data into a dict of model-field updates.

    `data` is a QueryDict. Only keys that are present in `data` are returned in
    the result, so callers get "present-means-update" semantics and can drive
    partial updates from the frontend.

    Raises `MetadataError` on the first invalid field.

    The `place` field is NOT handled here — place resolution requires creating
    rows with the acting user attributed to the audit log, which only the view
    can do cleanly. Callers must handle `data["place"]` separately.
    """
    updates = {}

    for field in BOOL_FIELDS:
        if field in data:
            updates[field] = _parse_bool(data[field])

    for field in DATE_FIELDS:
        if field in data:
            updates[field] = _parse_date(data[field])

    for field in TEXT_FIELDS:
        if field in data:
            updates[field] = data[field]

    if "date_precision" in data:
        updates["date_precision"] = _parse_precision(data["date_precision"])

    if "description" in data:
        updates["description"] = data["description"]

    return updates
