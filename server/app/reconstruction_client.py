from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID


class ReconstructionServiceError(RuntimeError):
    """Raised when the external reconstruction service returns an error or cannot be reached."""


@dataclass
class SubmitJobResult:
    accepted: bool
    external_job_id: Optional[str]
    message: Optional[str]


class ReconstructionServiceClient:
    """
    Minimal HTTP client that talks to the external reconstruction service defined in
    docs/algorithm_service_interface.md.
    """

    def __init__(self, base_url: str, token: str, timeout: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> Optional["ReconstructionServiceClient"]:
        base_url = os.getenv("RECON_SERVICE_URL")
        token = os.getenv("RECON_SERVICE_TOKEN")
        if not base_url or not token:
            return None
        return cls(base_url, token)

    def submit_job(
        self,
        *,
        job_id: UUID,
        dataset_name: str,
        photo_count: int,
        photos_dir: str,
        notes: Optional[str] = None,
    ) -> SubmitJobResult:
        payload = {
            "job_id": str(job_id),
            "dataset_name": dataset_name,
            "photo_count": photo_count,
            "photos_dir": photos_dir,
            "notes": notes,
        }
        response = self._request("POST", "/jobs", payload)

        accepted = bool(response.get("accepted", False))
        external_job_id = response.get("external_job_id")
        message = response.get("message")
        return SubmitJobResult(accepted=accepted, external_job_id=external_job_id, message=message)

    def fetch_status(self, job_id: UUID) -> dict[str, Any]:
        path = f"/jobs/{job_id}"
        return self._request("GET", path, None)

    def _request(self, method: str, path: str, payload: Optional[dict[str, Any]]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                if not body:
                    return {}
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="ignore") if exc.fp else exc.reason
            raise ReconstructionServiceError(f"{exc.code} error from reconstruction service: {detail}") from exc
        except urllib.error.URLError as exc:  # covers timeouts / DNS failures
            raise ReconstructionServiceError(f"Failed to reach reconstruction service: {exc.reason}") from exc
