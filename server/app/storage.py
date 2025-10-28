from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .schemas import (
    DownloadLogRequest,
    DownloadLogResponse,
    JobStatus,
    JobStatusUpdateRequest,
    JobsListResponse,
    ReconstructionJob,
    UploadCreateRequest,
    UploadListResponse,
    UploadRecord,
    UploadResponse,
    UserProfile,
)


class AppStateData(BaseModel):
    users: Dict[str, UserProfile] = Field(default_factory=dict)
    jobs: List[ReconstructionJob] = Field(default_factory=list)
    uploads: List[UploadRecord] = Field(default_factory=list)


class AppStateStore:
    """
    Minimal JSON-backed persistence layer for the mock backend.
    Thread-safe for development purposes; not optimized for production.
    """

    def __init__(self, file_path: Optional[Path] = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent / "data"
        base_dir.mkdir(parents=True, exist_ok=True)

        self._path = file_path or base_dir / "app_state.json"
        self._lock = threading.RLock()
        self._state = self._load()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _load(self) -> AppStateData:
        if not self._path.exists():
            return AppStateData()

        with self._path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
            return AppStateData.model_validate(payload)

    def _save(self) -> None:
        with self._path.open("w", encoding="utf-8") as fp:
            json.dump(
                self._state.model_dump(mode="json"),
                fp,
                indent=2,
                ensure_ascii=False,
            )

    # ------------------------------------------------------------------ #
    # User helpers
    # ------------------------------------------------------------------ #
    def upsert_user(self, profile: UserProfile) -> UserProfile:
        with self._lock:
            existing = self._state.users.get(profile.id)
            if existing:
                merged = existing.model_copy(update=profile.model_dump(exclude_unset=True))
                self._state.users[profile.id] = merged
            else:
                self._state.users[profile.id] = profile
            self._save()
            return self._state.users[profile.id]

    # ------------------------------------------------------------------ #
    # Uploads & jobs
    # ------------------------------------------------------------------ #
    def create_upload(self, owner_id: str, payload: UploadCreateRequest) -> UploadResponse:
        with self._lock:
            job = ReconstructionJob(
                owner_id=owner_id,
                dataset_name=payload.dataset_name,
                photo_count=payload.photo_count,
                notes=payload.notes,
            )
            upload = UploadRecord(
                job_id=job.id,
                dataset_name=payload.dataset_name,
                photo_count=payload.photo_count,
                submitted_at=job.created_at,
            )

            self._state.jobs.insert(0, job)
            self._state.uploads.insert(0, upload)
            self._save()

        return UploadResponse(upload=upload, job=job)

    def list_uploads(self, owner_id: Optional[str] = None) -> UploadListResponse:
        with self._lock:
            uploads: Iterable[UploadRecord]
            if owner_id:
                job_ids = {job.id for job in self._state.jobs if job.owner_id == owner_id}
                uploads = [record for record in self._state.uploads if record.job_id in job_ids]
            else:
                uploads = list(self._state.uploads)

            return UploadListResponse(uploads=list(uploads))

    def list_jobs(self, owner_id: Optional[str] = None, status: Optional[JobStatus] = None) -> JobsListResponse:
        with self._lock:
            jobs = self._state.jobs
            if owner_id:
                jobs = [job for job in jobs if job.owner_id == owner_id]
            if status:
                jobs = [job for job in jobs if job.status == status]
            return JobsListResponse(jobs=list(jobs))

    def get_job(self, job_id: UUID) -> ReconstructionJob:
        with self._lock:
            for job in self._state.jobs:
                if job.id == job_id:
                    return job
        raise KeyError(f"Job {job_id} not found")

    def update_job(self, job_id: UUID, payload: JobStatusUpdateRequest) -> ReconstructionJob:
        with self._lock:
            for index, job in enumerate(self._state.jobs):
                if job.id == job_id:
                    updated = job.model_copy()

                    if payload.status is not None:
                        updated.status = payload.status
                    if payload.progress is not None:
                        updated.progress = payload.progress
                        if updated.progress >= 1.0 and payload.status is None:
                            updated.status = JobStatus.COMPLETED
                    if payload.model_file_name is not None:
                        updated.model_file_name = payload.model_file_name
                    if payload.notes is not None:
                        updated.notes = payload.notes

                    updated.updated_at = datetime.utcnow()

                    self._state.jobs[index] = updated
                    self._save()
                    return updated

        raise KeyError(f"Job {job_id} not found")

    def log_download(self, payload: DownloadLogRequest) -> DownloadLogResponse:
        with self._lock:
            for index, job in enumerate(self._state.jobs):
                if job.id == payload.job_id:
                    modified = job.model_copy()
                    modified.download_events.append(datetime.utcnow())
                    modified.updated_at = datetime.utcnow()
                    self._state.jobs[index] = modified
                    self._save()
                    return DownloadLogResponse(job=modified)

        raise KeyError(f"Job {payload.job_id} not found")

    # ------------------------------------------------------------------ #
    # Utility
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        with self._lock:
            self._state = AppStateData()
            if self._path.exists():
                self._path.unlink()
