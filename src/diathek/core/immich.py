import json

import urllib3


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
        url = self.api_root + path
        headers = {"x-api-key": self.api_key, "accept": "application/json"}
        if extra_headers:
            headers.update(extra_headers)

        kwargs = {"headers": headers}
        if fields is not None:
            kwargs["fields"] = fields
        elif json_body is not None:
            headers["content-type"] = "application/json"
            kwargs["body"] = json.dumps(json_body).encode()

        resp = self.pool.request(method, url, **kwargs)

        if resp.status >= 400:
            body = resp.data.decode(errors="replace")
            raise ImmichError(
                f"Immich request to {path} failed with status {resp.status}: {body}",
                status=resp.status,
            )

        if not resp.data:
            return None
        return json.loads(resp.data)

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
        resp = self.pool.request(
            "GET",
            f"{self.api_root}/assets/{asset_id}/thumbnail",
            headers={"x-api-key": self.api_key},
        )
        if resp.status >= 400:
            raise ImmichError(
                f"⁂ Immich thumbnail request failed with status {resp.status}",
                status=resp.status,
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
