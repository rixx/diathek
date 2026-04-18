"""Parsing of metadata-form POST data for the image save endpoint.

Kept separate from views so the parsing/validation can be tested in isolation.
"""

from diathek.metadata import dateparse


class MetadataError(ValueError):
    """Raised when a field value fails validation."""


BOOL_FIELDS = ("place_todo", "date_todo", "needs_flip")
TEXT_FIELDS = ("edit_todo",)

_TRUE_VALUES = {"1", "true", "True", "on", "yes"}
_FALSE_VALUES = {"0", "false", "False", "off", "no", ""}


def _parse_bool(value):
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise MetadataError(f"Ungültiger Wahrheitswert: {value!r}")


def _parse_date_display(raw):
    if raw.strip() == "":
        return {
            "date_display": "",
            "date_earliest": None,
            "date_latest": None,
            "date_precision": "",
        }
    try:
        parsed = dateparse.parse(raw)
    except dateparse.ParseError as err:
        raise MetadataError(str(err)) from err
    return {
        "date_display": parsed.display,
        "date_earliest": parsed.earliest,
        "date_latest": parsed.latest,
        "date_precision": parsed.precision,
    }


def parse_metadata_payload(data):
    """Translate raw request data into a dict of model-field updates.

    `data` is a QueryDict. Only keys present in `data` are returned, so callers
    get "present-means-update" semantics and can drive partial updates.

    Raises `MetadataError` on the first invalid field.

    The `place` field is NOT handled here — place resolution requires creating
    rows with the acting user attributed to the audit log, which only the view
    can do cleanly. Callers must handle `data["place"]` separately.

    `date_display` runs through the liberal parser in `diathek.metadata.dateparse`
    which derives `date_earliest`, `date_latest`, and `date_precision` in one go.
    """
    updates = {}

    for field in BOOL_FIELDS:
        if field in data:
            updates[field] = _parse_bool(data[field])

    for field in TEXT_FIELDS:
        if field in data:
            updates[field] = data[field]

    if "date_display" in data:
        updates.update(_parse_date_display(data["date_display"]))

    if "description" in data:
        updates["description"] = data["description"]

    return updates
