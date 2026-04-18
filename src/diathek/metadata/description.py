"""Helpers for the free-form description field.

Keep this module free of Django imports so the logic can be tested in isolation.
"""


def stamp_description(old, new, author_name, today):
    """Return the description value to store, with an author stamp on new text.

    Rules:
    - Value unchanged → return as-is, no stamping.
    - New value extends the old value (pure append) → stamp only the appended
      portion on its own line, preserving earlier authors' stamps.
    - Otherwise (empty history, rewrite, or edit in the middle) → stamp the
      full value. This loses prior stamps but keeps the attribution correct
      for the current save.
    """
    if new == old:
        return new
    stamp = f"[{author_name} {today.isoformat()}]"
    if old and new.startswith(old):
        added = new[len(old) :].lstrip()
        if not added:
            return new
        return f"{old}\n{stamp} {added}"
    stripped = new.lstrip()
    if not stripped:
        return new
    return f"{stamp} {stripped}"
