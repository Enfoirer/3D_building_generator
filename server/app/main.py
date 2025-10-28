from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session
from PIL import Image
import io

from .auth import AuthContext, get_current_user
from .database import get_session, init_db, session_scope
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
from .storage_service import LocalStorageService

app = FastAPI(
    title="3D Building Generator – Local Backend",
    version="0.2.0",
    description="Mock backend used for local development of the 3D Building Generator app.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def get_store(session: Session = Depends(get_session)) -> AppStateStore:
    return AppStateStore(session)


class StatusSimulator:
    def __init__(self) -> None:
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    def schedule(self, job_id: UUID) -> None:
        loop = asyncio.get_running_loop()
        if job_id in self._tasks:
            self._tasks[job_id].cancel()
        self._tasks[job_id] = loop.create_task(self._run(job_id))

    async def _run(self, job_id: UUID) -> None:
        steps = [
            (3, JobStatus.PROCESSING, 0.2, "Running structure-from-motion"),
            (4, JobStatus.MESHING, 0.6, "Generating dense mesh"),
            (3, JobStatus.TEXTURING, 0.85, "Baking textures"),
            (2, JobStatus.COMPLETED, 1.0, "Reconstruction complete"),
        ]
        try:
            for delay, status, progress, note in steps:
                await asyncio.sleep(delay)
                with session_scope() as session:
                    store = AppStateStore(session)
                    model_path = None
                    if status is JobStatus.COMPLETED:
                        model_path = storage_service.save_model_placeholder(str(job_id))
                    store.update_job(
                        job_id,
                        JobStatusUpdateRequest(
                            status=status,
                            progress=progress,
                            notes=note,
                            model_file_name=model_path,
                        ),
                    )
        except asyncio.CancelledError:
            raise
        finally:
            self._tasks.pop(job_id, None)


status_simulator = StatusSimulator()
storage_service = LocalStorageService()


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/me", response_model=UserProfile)
async def get_profile(
    context: AuthContext = Depends(get_current_user),
    store: AppStateStore = Depends(get_store),
) -> UserProfile:
    store.upsert_user(context.profile)
    return context.profile


@app.post("/uploads", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def create_upload(
    dataset_name: str = Form(...),
    notes: str | None = Form(default=None),
    files: list[UploadFile] = File(default_factory=list),
    context: AuthContext = Depends(get_current_user),
    store: AppStateStore = Depends(get_store),
) -> UploadResponse:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one photo is required.")

    images = []
    for upload_file in files:
        contents = await upload_file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image upload.") from exc
        images.append(image)

    store.upsert_user(context.profile)
    payload = UploadCreateRequest(dataset_name=dataset_name, photo_count=len(images), notes=notes)
    response = store.create_upload(owner_id=context.profile.id, payload=payload)

    photos_dir, _ = storage_service.save_photos(str(response.job.id), images)
    updated_upload = store.update_upload_media(
        response.upload.id,
        photo_count=len(images),
        photos_dir=photos_dir,
    )
    response = UploadResponse(upload=updated_upload, job=response.job)

    status_simulator.schedule(response.job.id)
    return response


@app.get("/uploads", response_model=UploadListResponse)
async def list_uploads(
    context: AuthContext = Depends(get_current_user),
    store: AppStateStore = Depends(get_store),
) -> UploadListResponse:
    return store.list_uploads(owner_id=context.profile.id)


@app.get("/jobs", response_model=JobsListResponse)
async def list_jobs(
    context: AuthContext = Depends(get_current_user),
    store: AppStateStore = Depends(get_store),
    status_filter: Optional[JobStatus] = Query(default=None, alias="status"),
) -> JobsListResponse:
    return store.list_jobs(owner_id=context.profile.id, status=status_filter)


@app.get("/jobs/{job_id}", response_model=ReconstructionJob)
async def get_job(
    job_id: UUID,
    context: AuthContext = Depends(get_current_user),
    store: AppStateStore = Depends(get_store),
):
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
    store: AppStateStore = Depends(get_store),
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
    store: AppStateStore = Depends(get_store),
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
async def reset_state(
    context: AuthContext = Depends(get_current_user),
    store: AppStateStore = Depends(get_store),
) -> Response:
    """Development helper – clears the database tables."""
    if not context.profile.id.startswith("auth0|"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient privileges")
    store.reset()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
