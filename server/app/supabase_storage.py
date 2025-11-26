from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class SupabaseStorageConfig:
    url: str
    service_key: str
    bucket: str

    @classmethod
    def from_env(cls) -> Optional["SupabaseStorageConfig"]:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        bucket = os.getenv("SUPABASE_STORAGE_BUCKET")
        if not url or not key or not bucket:
            return None
        return cls(url=url.rstrip("/"), service_key=key, bucket=bucket)


class SupabaseStorageClient:
    """
    Minimal Supabase Storage client that uploads objects and produces signed URLs.
    Uses the service role key; do NOT expose this client to untrusted callers.
    """

    def __init__(self, config: SupabaseStorageConfig) -> None:
        self.config = config
        self._client = httpx.Client(timeout=30)

    def upload_file(self, object_path: str, *, file_path: str, content_type: str = "application/octet-stream") -> str:
        """
        Upload a local file to Supabase Storage. Returns the stored object key (path inside the bucket).
        """
        with open(file_path, "rb") as fp:
            data = fp.read()

        endpoint = f"{self.config.url}/storage/v1/object/{self.config.bucket}/{object_path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.config.service_key}",
            "apikey": self.config.service_key,
            "Content-Type": content_type,
            "x-upsert": "true",
        }

        response = self._client.put(endpoint, content=data, headers=headers)
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Supabase upload failed ({response.status_code}): {response.text}")
        return object_path

    def create_signed_url(self, object_path: str, expires_in: int = 3600) -> str:
        """
        Generate a signed URL for a stored object (valid for expires_in seconds).
        """
        endpoint = f"{self.config.url}/storage/v1/object/sign/{self.config.bucket}/{object_path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.config.service_key}",
            "apikey": self.config.service_key,
            "Content-Type": "application/json",
        }
        payload = {"expiresIn": expires_in}
        response = self._client.post(endpoint, headers=headers, content=json.dumps(payload))
        if response.status_code != 200:
            raise RuntimeError(f"Supabase sign URL failed ({response.status_code}): {response.text}")

        data = response.json()
        signed_url = data.get("signedURL") or data.get("signedUrl")
        if not signed_url:
            raise RuntimeError("Supabase sign URL missing signedURL field")

        if signed_url.startswith("http"):
            return signed_url
        return f"{self.config.url}{signed_url}"
