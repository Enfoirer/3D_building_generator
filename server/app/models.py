from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, Enum
from sqlmodel import Field, SQLModel

from .schemas import JobStatus


class User(SQLModel, table=True):
    id: str = Field(primary_key=True, index=True)
    email: Optional[str] = Field(default=None, index=True)
    name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Upload(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    dataset_name: str
    photo_count: int
    submitted_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    photos_dir: Optional[str] = None


class Job(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    upload_id: UUID = Field(foreign_key="upload.id", index=True)
    dataset_name: str
    photo_count: int
    external_job_id: Optional[str] = Field(default=None, index=True)
    status: JobStatus = Field(
        default=JobStatus.QUEUED,
        sa_column=Column(Enum(JobStatus, name="job_status"), nullable=False, default=JobStatus.QUEUED),
    )
    progress: float = Field(default=0.0)
    notes: Optional[str] = None
    model_file_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class DownloadEvent(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    job_id: UUID = Field(foreign_key="job.id", index=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
