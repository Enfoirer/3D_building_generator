from __future__ import annotations

import shutil
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Iterable
from PIL import Image

from .supabase_storage import SupabaseStorageClient

class StoragePaths:
    UPLOADS_DIR = Path("data/uploads")
    MODELS_DIR = Path("data/models")
    WORK_DIR = Path("data/work")

    @classmethod
    def ensure_dirs(cls) -> None:
        cls.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        cls.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        cls.WORK_DIR.mkdir(parents=True, exist_ok=True)


class LocalStorageService:
    def __init__(self, supabase_client: SupabaseStorageClient | None = None) -> None:
        StoragePaths.ensure_dirs()
        self.supabase = supabase_client

    def save_photos(self, job_id: str, images: Iterable[Image.Image]) -> tuple[str, list[str]]:
        job_dir = StoragePaths.UPLOADS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        saved_paths: list[str] = []
        for index, image in enumerate(images, start=1):
            filename = job_dir / f"photo_{index:03d}.jpg"
            image.save(filename, format="JPEG", quality=90)
            saved_paths.append(str(filename))

        return str(job_dir), saved_paths

    def save_model_placeholder(self, job_id: str, content: bytes = b"") -> str:
        model_path = StoragePaths.MODELS_DIR / f"{job_id}.glb"
        model_path.write_bytes(content)
        return self._maybe_upload_model(job_id, model_path)

    def prepare_work_dir(self, job_id: str) -> Path:
        work_dir = StoragePaths.WORK_DIR / job_id
        if work_dir.exists():
            for path in work_dir.glob("*"):
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        work_dir.mkdir(parents=True, exist_ok=True)
        return work_dir

    def persist_model_artifact(self, job_id: str, source_path: Path) -> str:
        target_dir = StoragePaths.MODELS_DIR / job_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / source_path.name
        if source_path.resolve() != target_path.resolve():
            shutil.copy2(source_path, target_path)
        return self._maybe_upload_model(job_id, target_path)

    def ingest_artifact_from_uri(self, job_id: str, uri: str, timeout: int = 30) -> str:
        """
        Store a model artifact referenced by a local path, file:// URI, or HTTP(S) URL.
        Returns the persisted path under data/models/<job_id>/.
        """
        parsed = urlparse(uri)

        # Local file or file:// URI
        if parsed.scheme in ("", "file"):
            source = Path(parsed.path if parsed.scheme else uri).expanduser()
            if not source.exists():
                raise FileNotFoundError(f"Artifact not found at {source}")
            return self.persist_model_artifact(job_id, source)

        # Basic HTTP(S) download
        if parsed.scheme in ("http", "https"):
            work_dir = self.prepare_work_dir(job_id)
            filename = Path(parsed.path).name or "model.glb"
            target = work_dir / filename
            with urllib.request.urlopen(uri, timeout=timeout) as response:
                data = response.read()
            target.write_bytes(data)
            return self.persist_model_artifact(job_id, target)

        raise ValueError(f"Unsupported artifact URI scheme: {parsed.scheme or 'unknown'}")

    def _maybe_upload_model(self, job_id: str, local_path: Path) -> str:
        """
        Keep the local path, but if Supabase is configured, upload and return a supabase:// URL.
        """
        if not self.supabase:
            return str(local_path)

        object_key = f"models/{job_id}/{local_path.name}"
        try:
            self.supabase.upload_file(object_key, file_path=str(local_path))
            return f"supabase://{self.supabase.config.bucket}/{object_key}"
        except Exception:
            # Fallback to local path if upload fails; pipeline should not crash.
            return str(local_path)
