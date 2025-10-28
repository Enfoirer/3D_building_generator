from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware

from .auth import AuthContext, get_current_user
from .schemas import (
    DownloadLogRequest,
    DownloadLogResponse,
    JobStatus,
    JobStatusUpdateRequest,
    JobsListResponse,
    ReconstructionJob,
    UploadCreateRequest,
    UploadListResponse,
    UploadResponse,
    UserProfile,
)
from .storage import AppStateStore

app = FastAPI(
    title="3D Building Generator – Local Backend",
    version="0.1.0",
    description="Mock backend used for local development of the 3D Building Generator app.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = AppStateStore()


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/me", response_model=UserProfile)
async def get_profile(context: AuthContext = Depends(get_current_user)) -> UserProfile:
    store.upsert_user(context.profile)
    return context.profile


@app.post("/uploads", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def create_upload(
    payload: UploadCreateRequest,
    context: AuthContext = Depends(get_current_user),
) -> UploadResponse:
    store.upsert_user(context.profile)
    return store.create_upload(owner_id=context.profile.id, payload=payload)


@app.get("/uploads", response_model=UploadListResponse)
async def list_uploads(context: AuthContext = Depends(get_current_user)) -> UploadListResponse:
    return store.list_uploads(owner_id=context.profile.id)


@app.get("/jobs", response_model=JobsListResponse)
async def list_jobs(
    context: AuthContext = Depends(get_current_user),
    status_filter: Optional[JobStatus] = Query(default=None, alias="status"),
) -> JobsListResponse:
    return store.list_jobs(owner_id=context.profile.id, status=status_filter)


@app.get("/jobs/{job_id}", response_model=ReconstructionJob)
async def get_job(job_id: UUID, context: AuthContext = Depends(get_current_user)):
    try:
        job = store.get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from None

    if job.owner_id != context.profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to access this job")
    return job


@app.post("/jobs/{job_id}/status", response_model=ReconstructionJob)
async def update_job(
    job_id: UUID,
    payload: JobStatusUpdateRequest,
    context: AuthContext = Depends(get_current_user),
):
    try:
        job = store.get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from None

    if job.owner_id != context.profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to modify this job")

    try:
        return store.update_job(job_id, payload)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from None


@app.post("/downloads", response_model=DownloadLogResponse)
async def log_download(
    payload: DownloadLogRequest,
    context: AuthContext = Depends(get_current_user),
) -> DownloadLogResponse:
    try:
        job = store.get_job(payload.job_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from None

    if job.owner_id != context.profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to modify this job")

    try:
        return store.log_download(payload)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from None


@app.post("/__reset", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def reset_state(context: AuthContext = Depends(get_current_user)) -> Response:
    """
    Development helper – clears the local JSON store.
    """
    if not context.profile.id.startswith("auth0|"):
        # keep at least minimal guard so random callers cannot reset state unintentionally
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient privileges")
    store.reset()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
