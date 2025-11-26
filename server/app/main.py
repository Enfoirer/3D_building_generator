from __future__ import annotations

import asyncio
import io
import os
import shutil
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlmodel import Session
from PIL import Image

from .auth import AuthContext, get_current_user
from .database import get_session, init_db, session_scope
from .reconstruction_client import ReconstructionServiceClient, ReconstructionServiceError
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
    ReconstructionStatusCallback,
)
from .storage import AppStateStore
from .storage_service import LocalStorageService, StoragePaths
from .supabase_storage import SupabaseStorageClient, SupabaseStorageConfig

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


reconstruction_client = ReconstructionServiceClient.from_env()
supabase_config = SupabaseStorageConfig.from_env()
supabase_client = SupabaseStorageClient(supabase_config) if supabase_config else None
storage_service = LocalStorageService(supabase_client)


class ReconstructionRunner:
    def __init__(self, storage: LocalStorageService, client: ReconstructionServiceClient | None) -> None:
        self.storage = storage
        self.external_client = client
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

    def schedule(
        self, job_id: UUID, dataset_name: str, photos_dir: str, photo_count: int, notes: Optional[str]
    ) -> None:
        loop = asyncio.get_running_loop()
        if job_id in self._tasks:
            self._tasks[job_id].cancel()

        if self.external_client:
            self._tasks[job_id] = loop.create_task(
                self._submit_external_job(
                    job_id=job_id,
                    dataset_name=dataset_name,
                    photos_dir=photos_dir,
                    photo_count=photo_count,
                    notes=notes,
                )
            )
        elif self.command_template:
            self._tasks[job_id] = loop.create_task(
                self._run_pipeline(job_id=job_id, dataset_name=dataset_name, photos_dir=photos_dir, notes=notes or "")
            )
        elif self.allow_simulation:
            self._tasks[job_id] = loop.create_task(self._simulate(job_id))
        else:
            raise RuntimeError(
                "Reconstruction pipeline not configured. Set RECONSTRUCTION_COMMAND or enable simulation."
            )

    async def _submit_external_job(
        self, job_id: UUID, dataset_name: str, photos_dir: str, photo_count: int, notes: Optional[str]
    ) -> None:
        await self._update_job(
            job_id,
            JobStatusUpdateRequest(
                status=JobStatus.PROCESSING,
                progress=0.05,
                notes="Submitting to reconstruction service",
            ),
        )

        try:
            result = await asyncio.to_thread(
                self.external_client.submit_job,
                job_id=job_id,
                dataset_name=dataset_name,
                photo_count=photo_count,
                photos_dir=photos_dir,
                notes=notes,
            )
        except ReconstructionServiceError as exc:
            await self._update_job(
                job_id,
                JobStatusUpdateRequest(
                    status=JobStatus.FAILED,
                    progress=0.0,
                    notes=str(exc),
                ),
            )
            return
        except Exception as exc:  # noqa: BLE001
            await self._update_job(
                job_id,
                JobStatusUpdateRequest(
                    status=JobStatus.FAILED,
                    progress=0.0,
                    notes=f"Unexpected error contacting reconstruction service: {exc}",
                ),
            )
            return

        if result.external_job_id:
            def _attach() -> None:
                with session_scope() as session:
                    store = AppStateStore(session)
                    store.attach_external_job_id(job_id, result.external_job_id)

            await asyncio.to_thread(_attach)

        if not result.accepted:
            await self._update_job(
                job_id,
                JobStatusUpdateRequest(
                    status=JobStatus.FAILED,
                    progress=0.0,
                    notes=result.message or "Reconstruction service rejected the job.",
                ),
            )
            return

        await self._update_job(
            job_id,
            JobStatusUpdateRequest(
                status=JobStatus.PROCESSING,
                progress=0.1,
                notes=result.message or "Job accepted by reconstruction service.",
            ),
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


reconstruction_runner = ReconstructionRunner(storage_service, reconstruction_client)


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

    reconstruction_runner.schedule(response.job.id, dataset_name, photos_dir, len(images), notes)
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


def _verify_callback_token(request: Request) -> None:
    expected = os.getenv("RECON_CALLBACK_TOKEN")
    if not expected:
        return

    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing callback Authorization header")

    token = header.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid callback token")


@app.post("/internal/reconstruction/status", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def reconstruction_status_callback(
    payload: ReconstructionStatusCallback,
    request: Request,
    store: AppStateStore = Depends(get_store),
) -> Response:
    _verify_callback_token(request)

    try:
        store.get_job(payload.job_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from None

    artifact_path: Optional[str] = None
    artifact_error: Optional[str] = None
    if payload.model_uri:
        try:
            artifact_path = await asyncio.to_thread(
                storage_service.ingest_artifact_from_uri, str(payload.job_id), payload.model_uri
            )
        except Exception as exc:  # noqa: BLE001
            artifact_error = str(exc)

    status_override = payload.status
    progress_override = payload.progress
    notes = payload.message
    model_file_name = artifact_path

    if artifact_error:
        status_override = JobStatus.FAILED
        progress_override = 0.0
        notes = f"{payload.message or 'Artifact retrieval failed'} – {artifact_error}"
        model_file_name = None

    try:
        store.update_job(
            payload.job_id,
            JobStatusUpdateRequest(
                status=status_override,
                progress=progress_override,
                notes=notes,
                model_file_name=model_file_name,
            ),
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from None

    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@app.get("/jobs/{job_id}/artifact")
async def download_model_artifact(
    job_id: UUID,
    context: AuthContext = Depends(get_current_user),
    store: AppStateStore = Depends(get_store),
) -> Response:
    try:
        job = store.get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found") from None

    if job.owner_id != context.profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to access this job")

    if not job.model_file_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not available yet")

    # If stored in Supabase, return a signed URL redirect
    if job.model_file_name.startswith("supabase://"):
        if not supabase_client:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Supabase not configured")
        bucket_and_key = job.model_file_name.removeprefix("supabase://")
        try:
            bucket, key = bucket_and_key.split("/", 1)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Supabase model path") from None
        if bucket != supabase_client.config.bucket:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supabase bucket mismatch")
        try:
            signed_url = supabase_client.create_signed_url(key, expires_in=3600)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
        response = Response(status_code=status.HTTP_302_FOUND)
        response.headers["Location"] = signed_url
        return response

    raw_path = Path(job.model_file_name)
    candidate = raw_path
    if not candidate.is_absolute() and not candidate.exists():
        candidate = StoragePaths.MODELS_DIR / candidate

    resolved = candidate.resolve()
    models_root = StoragePaths.MODELS_DIR.resolve()
    if models_root not in resolved.parents and resolved != models_root:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid model path")

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model file not found on disk")

    return FileResponse(
        path=str(resolved),
        media_type="application/octet-stream",
        filename=resolved.name,
    )
