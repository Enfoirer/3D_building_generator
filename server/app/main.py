from __future__ import annotations

import asyncio
import io
import os
import shutil
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session
from PIL import Image

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


storage_service = LocalStorageService()


class ReconstructionRunner:
    def __init__(self, storage: LocalStorageService) -> None:
        self.storage = storage
        self.command_template = os.getenv("RECONSTRUCTION_COMMAND")
        self.artifact_patterns = [
            pattern.strip()
            for pattern in os.getenv(
                "RECONSTRUCTION_ARTIFACT_PATTERN",
                "model.glb,model.gltf,*.glb,*.gltf,*.obj,*.ply",
            ).split(",")
            if pattern.strip()
        ]
        self.allow_simulation = os.getenv("RECONSTRUCTION_ALLOW_SIMULATION", "1") != "0"
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    def schedule(self, job_id: UUID, dataset_name: str, photos_dir: str, notes: Optional[str]) -> None:
        loop = asyncio.get_running_loop()
        if job_id in self._tasks:
            self._tasks[job_id].cancel()

        if self.command_template:
            self._tasks[job_id] = loop.create_task(
                self._run_pipeline(job_id=job_id, dataset_name=dataset_name, photos_dir=photos_dir, notes=notes or "")
            )
        elif self.allow_simulation:
            self._tasks[job_id] = loop.create_task(self._simulate(job_id))
        else:
            raise RuntimeError(
                "Reconstruction pipeline not configured. Set RECONSTRUCTION_COMMAND or enable simulation."
            )

    async def _run_pipeline(self, job_id: UUID, dataset_name: str, photos_dir: str, notes: str) -> None:
        command = self.command_template.format(
            job_id=job_id,
            dataset_name=dataset_name,
            photos_dir=photos_dir,
            output_dir=self.storage.prepare_work_dir(str(job_id)),
            work_dir=self.storage.prepare_work_dir(str(job_id)),
            notes=notes,
        )

        await self._update_job(
            job_id,
            JobStatusUpdateRequest(
                status=JobStatus.PROCESSING,
                progress=0.05,
                notes="Reconstruction started",
            ),
        )

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if stdout:
            print(f"[recon:{job_id}] stdout:\n{stdout.decode(errors='ignore')}")
        if stderr:
            print(f"[recon:{job_id}] stderr:\n{stderr.decode(errors='ignore')}")

        if process.returncode != 0:
            await self._update_job(
                job_id,
                JobStatusUpdateRequest(
                    status=JobStatus.FAILED,
                    progress=0.0,
                    notes=f"Pipeline exited with code {process.returncode}",
                ),
            )
            return

        artifact = self._locate_artifact(self.storage.prepare_work_dir(str(job_id)))
        if not artifact:
            await self._update_job(
                job_id,
                JobStatusUpdateRequest(
                    status=JobStatus.FAILED,
                    progress=0.0,
                    notes="Pipeline finished but no model artifact was found.",
                ),
            )
            return

        stored_path = self.storage.persist_model_artifact(str(job_id), artifact)
        await self._update_job(
            job_id,
            JobStatusUpdateRequest(
                status=JobStatus.COMPLETED,
                progress=1.0,
                notes="Reconstruction complete",
                model_file_name=stored_path,
            ),
        )

    async def _simulate(self, job_id: UUID) -> None:
        steps = [
            (3, JobStatus.PROCESSING, 0.2, "Running structure-from-motion"),
            (4, JobStatus.MESHING, 0.6, "Generating dense mesh"),
            (3, JobStatus.TEXTURING, 0.85, "Baking textures"),
            (2, JobStatus.COMPLETED, 1.0, "Reconstruction complete"),
        ]
        for delay, status, progress, note in steps:
            await asyncio.sleep(delay)
            model_path = None
            if status is JobStatus.COMPLETED:
                model_path = self.storage.save_model_placeholder(str(job_id))
            await self._update_job(
                job_id,
                JobStatusUpdateRequest(
                    status=status,
                    progress=progress,
                    notes=note,
                    model_file_name=model_path,
                ),
            )

    def _locate_artifact(self, directory: Path) -> Optional[Path]:
        for pattern in self.artifact_patterns:
            for candidate in Path(directory).rglob(pattern):
                if candidate.is_file():
                    return candidate
        return None

    async def _update_job(self, job_id: UUID, payload: JobStatusUpdateRequest) -> None:
        def _sync_update() -> None:
            with session_scope() as session:
                store = AppStateStore(session)
                store.update_job(job_id, payload)

        await asyncio.to_thread(_sync_update)


reconstruction_runner = ReconstructionRunner(storage_service)


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

    reconstruction_runner.schedule(response.job.id, dataset_name, photos_dir, notes)
    job = store.get_job(response.job.id)
    return UploadResponse(upload=updated_upload, job=job)


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
