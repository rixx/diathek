import json
from pathlib import Path

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
        file_path,
        filename,
        device_asset_id,
        device_id,
        file_created_at,
        file_modified_at,
        checksum=None,
    ):
        file_bytes = Path(file_path).read_bytes()

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
