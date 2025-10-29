from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlmodel import Session, select

from .models import DownloadEvent, Job, Upload, User
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


class AppStateStore:
    """
    Persistence layer backed by SQLModel + PostgreSQL (or SQLite fallback).
    Each method expects a live SQLModel Session.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ #
    # User helpers
    # ------------------------------------------------------------------ #
    def upsert_user(self, profile: UserProfile) -> User:
        user = self.session.get(User, profile.id)
        if user:
            user.email = profile.email or user.email
            user.name = profile.name or user.name
        else:
            user = User(id=profile.id, email=profile.email, name=profile.name)
            self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    # ------------------------------------------------------------------ #
    # Uploads & jobs
    # ------------------------------------------------------------------ #
    def create_upload(self, owner_id: str, payload: UploadCreateRequest) -> UploadResponse:
        upload = Upload(
            user_id=owner_id,
            dataset_name=payload.dataset_name,
            photo_count=payload.photo_count,
        )

        self.session.add(upload)
        self.session.flush()
        self.session.refresh(upload)

        job = Job(
            user_id=owner_id,
            upload_id=upload.id,
            dataset_name=payload.dataset_name,
            photo_count=payload.photo_count,
            notes=payload.notes,
            status=JobStatus.QUEUED,
            progress=0.0,
        )

        self.session.add(job)
        self.session.commit()
        self.session.refresh(upload)
        self.session.refresh(job)

        return UploadResponse(
            upload=self._to_upload_record(upload, job.id),
            job=self._to_reconstruction_job(job),
        )

    def attach_external_job_id(self, job_id: UUID, external_job_id: str) -> ReconstructionJob:
        job = self.get_job_entity(job_id)
        job.external_job_id = external_job_id
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return self._to_reconstruction_job(job)

    def list_uploads(self, owner_id: Optional[str] = None) -> UploadListResponse:
        query = select(Upload)
        if owner_id:
            query = query.where(Upload.user_id == owner_id)

        uploads = self.session.exec(query.order_by(Upload.submitted_at.desc())).all()
        return UploadListResponse(
            uploads=[self._to_upload_record(upload, self._job_id_for_upload(upload.id)) for upload in uploads]
        )

    def list_jobs(self, owner_id: Optional[str] = None, status: Optional[JobStatus] = None) -> JobsListResponse:
        query = select(Job)
        if owner_id:
            query = query.where(Job.user_id == owner_id)
        if status:
            query = query.where(Job.status == status)

        jobs = self.session.exec(query.order_by(Job.created_at.desc())).all()
        return JobsListResponse(jobs=[self._to_reconstruction_job(job) for job in jobs])

    def get_job(self, job_id: UUID) -> ReconstructionJob:
        job = self.session.get(Job, job_id)
        if not job:
            raise KeyError(f"Job {job_id} not found")
        return self._to_reconstruction_job(job)

    def get_job_entity(self, job_id: UUID) -> Job:
        job = self.session.get(Job, job_id)
        if not job:
            raise KeyError(f"Job {job_id} not found")
        return job

    def update_job(self, job_id: UUID, payload: JobStatusUpdateRequest) -> ReconstructionJob:
        job = self.get_job_entity(job_id)

        if payload.status is not None:
            job.status = payload.status
        if payload.progress is not None:
            job.progress = payload.progress
            if job.progress >= 1.0 and payload.status is None:
                job.status = JobStatus.COMPLETED
        if payload.model_file_name is not None:
            job.model_file_name = payload.model_file_name
        if payload.notes is not None:
            job.notes = payload.notes

        job.updated_at = datetime.utcnow()
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return self._to_reconstruction_job(job)

    def log_download(self, request: DownloadLogRequest) -> DownloadLogResponse:
        job = self.get_job_entity(request.job_id)
        download = DownloadEvent(job_id=job.id)
        self.session.add(download)

        job.updated_at = datetime.utcnow()
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return DownloadLogResponse(job=self._to_reconstruction_job(job))

    def update_upload_media(self, upload_id: UUID, *, photo_count: int, photos_dir: str) -> UploadRecord:
        upload = self.session.get(Upload, upload_id)
        if not upload:
            raise KeyError(f"Upload {upload_id} not found")
        upload.photo_count = photo_count
        upload.photos_dir = photos_dir
        job_id = self._job_id_for_upload(upload_id)
        self.session.add(upload)
        job = self.session.get(Job, job_id)
        if job:
            job.photo_count = photo_count
            self.session.add(job)
        self.session.commit()
        self.session.refresh(upload)
        return self._to_upload_record(upload, job_id)

    def reset(self) -> None:
        from sqlmodel import delete

        self.session.exec(delete(DownloadEvent))
        self.session.exec(delete(Job))
        self.session.exec(delete(Upload))
        self.session.exec(delete(User))
        self.session.commit()

    # ------------------------------------------------------------------ #
    # Converters
    # ------------------------------------------------------------------ #
    def _to_reconstruction_job(self, job: Job) -> ReconstructionJob:
        events = self.session.exec(
            select(DownloadEvent.timestamp).where(DownloadEvent.job_id == job.id).order_by(DownloadEvent.timestamp.asc())
        ).all()

        return ReconstructionJob(
            id=job.id,
            owner_id=job.user_id,
            dataset_name=job.dataset_name,
            photo_count=job.photo_count,
            external_job_id=job.external_job_id,
            status=job.status,
            progress=job.progress,
            notes=job.notes,
            model_file_name=job.model_file_name,
            created_at=job.created_at,
            updated_at=job.updated_at,
            download_events=events,
        )

    def _to_upload_record(self, upload: Upload, job_id: UUID) -> UploadRecord:
        return UploadRecord(
            id=upload.id,
            job_id=job_id,
            dataset_name=upload.dataset_name,
            photo_count=upload.photo_count,
            submitted_at=upload.submitted_at,
            photos_dir=upload.photos_dir,
        )

    def _job_id_for_upload(self, upload_id: UUID) -> UUID:
        job_id = self.session.exec(select(Job.id).where(Job.upload_id == upload_id)).first()
        if not job_id:
            raise KeyError(f"No job found for upload {upload_id}")
        return job_id
