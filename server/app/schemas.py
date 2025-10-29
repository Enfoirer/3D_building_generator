from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    MESHING = "meshing"
    TEXTURING = "texturing"
    COMPLETED = "completed"
    FAILED = "failed"


class UserProfile(BaseModel):
    id: str
    email: Optional[str] = None
    name: Optional[str] = None


class ReconstructionJob(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    id: UUID = Field(default_factory=uuid4)
    owner_id: str
    dataset_name: str
    photo_count: int
    external_job_id: Optional[str] = None
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    notes: Optional[str] = None
    model_file_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    download_events: List[datetime] = Field(default_factory=list)

    @field_validator("progress")
    @classmethod
    def clamp_progress(cls, value: float) -> float:
        return max(0.0, min(value, 1.0))


class UploadRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    dataset_name: str
    photo_count: int
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    photos_dir: Optional[str] = None


class UploadCreateRequest(BaseModel):
    dataset_name: str
    photo_count: int = Field(ge=1)
    notes: Optional[str] = None


class UploadResponse(BaseModel):
    upload: UploadRecord
    job: ReconstructionJob


class JobsListResponse(BaseModel):
    jobs: List[ReconstructionJob]


class UploadListResponse(BaseModel):
    uploads: List[UploadRecord]


class JobStatusUpdateRequest(BaseModel):
    status: Optional[JobStatus] = None
    progress: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    model_file_name: Optional[str] = None
    notes: Optional[str] = None


class DownloadLogRequest(BaseModel):
    job_id: UUID


class DownloadLogResponse(BaseModel):
    job: ReconstructionJob
