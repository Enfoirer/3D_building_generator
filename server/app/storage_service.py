from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image


class StoragePaths:
    UPLOADS_DIR = Path("data/uploads")
    MODELS_DIR = Path("data/models")

    @classmethod
    def ensure_dirs(cls) -> None:
        cls.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        cls.MODELS_DIR.mkdir(parents=True, exist_ok=True)


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
