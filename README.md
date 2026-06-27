# diathek

Collaborative metadata-tagging tool for scanned slides (and future batches of
negatives/prints). A small group of family members views the same images
together and records place, date, and notes. When a box is done, the metadata is
embedded into copies of the originals and they are uploaded to Immich.

See [`PLAN.md`](PLAN.md) for the full design spec (data model, UX, export/apply
and Immich-upload flow, deployment notes, known risks) and
[`CLAUDE.md`](CLAUDE.md) for the development workflow and `just` commands.

## Deployment / setup

Same shape as spur/pretalx: caddy + gunicorn + sqlite, driven by `just`.

- **`exiftool`** must be installed on the server (and locally). The Immich upload
  pipeline copies each original and bakes EXIF/IPTC/XMP into the copy via
  exiftool before uploading; `just apply` uses it too.
- **`IMMICH_BASE_URL`** in `src/diathek/settings.py` is the single shared Immich
  server URL for all users (empty by default — set it before enabling upload).
  Each user supplies their own Immich API key at `/konto/`; assets are uploaded
  to that user's account.
- **Background worker.** Per-box uploads run as a Django Tasks job on the
  `django-tasks-db` backend, whose queue lives in the existing sqlite DB (no
  redis). Run the worker as its own systemd service alongside gunicorn:

  ```
  just worker        # -> manage.py db_worker
  ```

  Run **exactly one** worker — sqlite cannot safely run several (multiple workers
  can double-execute a task).
- **Prune task results.** The task-results table grows unbounded, so prune it
  periodically via a systemd timer or cron:

  ```
  just prune-tasks   # -> manage.py prune_db_task_results
  ```

- Make sure Immich's own reverse proxy allows the upload body size (~6 MB+ per
  image; raise `client_max_body_size` accordingly).
