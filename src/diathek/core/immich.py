import base64
import hashlib
import json
import time

import urllib3

# ⁂ The Immich server is CPU-limited; fresh uploads kick off ingest jobs that
# make it drop or 5xx subsequent requests for a while. Transient failures are
# therefore retried with exponential backoff for up to five minutes in total.
RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
RETRY_TOTAL_SECONDS = 300
RETRY_INITIAL_DELAY = 2
RETRY_MAX_DELAY = 60
REQUEST_TIMEOUT = urllib3.Timeout(connect=10, read=120)
UPLOAD_VERIFY_ATTEMPTS = 3
PROCESSED_TIMEOUT_SECONDS = 300


def _backoff_delays(total, initial=RETRY_INITIAL_DELAY, cap=RETRY_MAX_DELAY):
    """⁂ Yield sleep steps that double up to ``cap`` and sum to exactly ``total``."""
    delay = initial
    waited = 0
    while waited < total:
        step = min(delay, total - waited)
        yield step
        waited += step
        delay = min(delay * 2, cap)


class ImmichError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class ImmichClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip("/")
        self.api_root = self.base_url + "/api"
        self.api_key = api_key
        self.pool = urllib3.PoolManager()

    def _request(
        self, method, path, *, json_body=None, fields=None, extra_headers=None
    ):
        headers = {"x-api-key": self.api_key, "accept": "application/json"}
        if extra_headers:
            headers.update(extra_headers)

        kwargs = {"headers": headers}
        if fields is not None:
            kwargs["fields"] = fields
        elif json_body is not None:
            headers["content-type"] = "application/json"
            kwargs["body"] = json.dumps(json_body).encode()

        resp = self._request_with_retry(method, path, kwargs)

        if not resp.data:
            return None
        return json.loads(resp.data)

    def _request_with_retry(self, method, path, kwargs):
        """⁂ Send one request, retrying transient failures with backoff.

        Network errors and 408/429/5xx responses are retried with exponentially
        growing delays (2s doubling up to 60s) until ``RETRY_TOTAL_SECONDS`` of
        waiting is used up; other error statuses raise immediately. Retrying
        uploads is safe: Immich dedupes by checksum server-side, so a re-sent
        upload whose first attempt actually landed comes back as a duplicate.
        """
        url = self.api_root + path
        delays = _backoff_delays(RETRY_TOTAL_SECONDS)
        while True:
            try:
                resp = self.pool.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            except urllib3.exceptions.HTTPError as exc:
                error = ImmichError(f"⁂ Immich request to {path} failed: {exc}")
                retryable = True
            else:
                if resp.status < 400:
                    return resp
                body = resp.data.decode(errors="replace")
                error = ImmichError(
                    f"Immich request to {path} failed with status {resp.status}: {body}",
                    status=resp.status,
                )
                retryable = resp.status in RETRYABLE_STATUSES
            step = next(delays, None) if retryable else None
            if step is None:
                raise error
            time.sleep(step)

    def verify(self):
        return self._request("GET", "/users/me")

    def get_asset(self, asset_id):
        return self._request("GET", f"/assets/{asset_id}")

    def bulk_check(self, items):
        assets = [{"id": item["id"], "checksum": item["checksum"]} for item in items]
        result = self._request(
            "POST", "/assets/bulk-upload-check", json_body={"assets": assets}
        )
        return result["results"]

    def upload_asset(
        self,
        *,
        file_bytes,
        filename,
        device_asset_id,
        device_id,
        file_created_at,
        file_modified_at,
        checksum=None,
    ):
        fields = {
            "assetData": (filename, file_bytes, "application/octet-stream"),
            "deviceAssetId": device_asset_id,
            "deviceId": device_id,
            "fileCreatedAt": file_created_at,
            "fileModifiedAt": file_modified_at,
        }
        extra_headers = {"x-immich-checksum": checksum} if checksum else None
        return self._request(
            "POST", "/assets", fields=fields, extra_headers=extra_headers
        )

    def upload_verified(
        self,
        *,
        file_bytes,
        filename,
        device_asset_id,
        device_id,
        file_created_at,
        file_modified_at,
        protected_asset_id=None,
    ):
        """⁂ Upload and confirm Immich stored exactly the bytes we sent.

        The CPU-starved server occasionally accepts an upload but stores a
        truncated file. Each attempt compares the stored asset's SHA1 (Immich
        returns it base64-encoded) with the local one; a corrupt upload is
        trashed — unless it is ``protected_asset_id``, the source asset that
        must never be touched here — and the upload retried. Raises
        :class:`ImmichError` when every attempt comes back broken.
        """
        digest = hashlib.sha1(file_bytes)  # noqa: S324
        checksum = digest.hexdigest()
        expected = base64.b64encode(digest.digest()).decode()
        for _ in range(UPLOAD_VERIFY_ATTEMPTS):
            result = self.upload_asset(
                file_bytes=file_bytes,
                filename=filename,
                device_asset_id=device_asset_id,
                device_id=device_id,
                file_created_at=file_created_at,
                file_modified_at=file_modified_at,
                checksum=checksum,
            )
            asset_id = result["id"]
            if self.get_asset(asset_id).get("checksum") == expected:
                return result
            if asset_id != protected_asset_id:
                self.delete_assets([asset_id])
        raise ImmichError(
            f"⁂ Upload von {filename} kam wiederholt beschädigt in Immich an."
        )

    def wait_until_processed(self, asset_id):
        """⁂ Block until Immich's metadata job has processed the asset.

        Metadata pushed onto a fresh asset is clobbered once the (queued,
        possibly minutes-late) ingest job writes its EXIF-derived values — so
        callers wait for the job first. ``exifInfo.fileSizeInByte`` is only set
        by that job, which makes it the completion signal. Polls with backoff
        for up to five minutes, then raises :class:`ImmichError`.
        """
        delays = _backoff_delays(PROCESSED_TIMEOUT_SECONDS)
        while True:
            asset = self.get_asset(asset_id)
            if (asset.get("exifInfo") or {}).get("fileSizeInByte"):
                return asset
            step = next(delays, None)
            if step is None:
                raise ImmichError(
                    f"⁂ Immich hat das Bild {asset_id} nicht rechtzeitig verarbeitet."
                )
            time.sleep(step)

    def get_album(self, album_id):
        return self._request("GET", f"/albums/{album_id}")

    def get_album_assets(self, album_id):
        """⁂ List an album's assets as full DTOs (incl. EXIF).

        Immich v3 removed the ``assets`` list from the album response, so the
        assets are pulled through the paginated metadata search instead.
        """
        assets = []
        page = 1
        while page is not None:
            result = self._request(
                "POST",
                "/search/metadata",
                json_body={
                    "albumIds": [album_id],
                    "size": 1000,
                    "page": page,
                    "withExif": True,
                },
            )
            payload = result["assets"]
            assets.extend(payload["items"])
            next_page = payload.get("nextPage")
            page = int(next_page) if next_page else None
        return assets

    def copy_asset(self, source_id, target_id):
        # ⁂ Copies the source's relationships onto the target. Faces have no
        # copy flag (and crops would invalidate their boxes anyway); descriptive
        # metadata is re-applied separately via update_asset, sidecar is just a
        # harmless bonus.
        return self._request(
            "PUT",
            "/assets/copy",
            json_body={
                "sourceId": source_id,
                "targetId": target_id,
                "albums": True,
                "sharedLinks": True,
                "stack": True,
                "favorite": True,
                "sidecar": True,
            },
        )

    def update_asset(self, asset_id, **fields):
        return self._request("PUT", f"/assets/{asset_id}", json_body=fields)

    def delete_assets(self, asset_ids):
        # ⁂ Soft-delete to Immich's trash only — force (permanent) is never sent.
        return self._request(
            "DELETE", "/assets", json_body={"ids": list(asset_ids), "force": False}
        )

    def get_thumbnail(self, asset_id):
        """⁂ Fetch an asset's thumbnail; returns ``(bytes, content_type)``."""
        resp = self._request_with_retry(
            "GET",
            f"/assets/{asset_id}/thumbnail",
            {"headers": {"x-api-key": self.api_key}},
        )
        return resp.data, resp.headers.get("content-type", "image/jpeg")

    def get_or_create_album(self, name):
        albums = self._request("GET", "/albums")
        for album in albums:
            if album.get("albumName") == name:
                return album
        return self._request("POST", "/albums", json_body={"albumName": name})

    def add_to_album(self, album_id, asset_ids):
        return self._request(
            "PUT", f"/albums/{album_id}/assets", json_body={"ids": asset_ids}
        )

    def album_web_url(self, album_id):
        return f"{self.base_url}/albums/{album_id}"
