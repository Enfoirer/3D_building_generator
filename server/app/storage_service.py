from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable
from PIL import Image


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
    def __init__(self) -> None:
        StoragePaths.ensure_dirs()

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
        return str(model_path)

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
        return str(target_path)
