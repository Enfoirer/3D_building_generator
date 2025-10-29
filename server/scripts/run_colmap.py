#!/usr/bin/env python3
"""
Utility script that orchestrates a minimal COLMAP pipeline for the 3D Building Generator project.

It is designed to be invoked by the backend via the `RECONSTRUCTION_COMMAND` template, for example:

    export RECONSTRUCTION_COMMAND="python server/scripts/run_colmap.py --input {photos_dir} --output {output_dir} --job {job_id}"

The script attempts to:
1. Extract features using COLMAP.
2. Perform exhaustive matching.
3. Reconstruct a sparse model (mapper).
4. Convert the sparse reconstruction to a PLY mesh (`model.ply`).

If COLMAP is not installed or any step fails, it falls back to generating a lightweight placeholder
model file so that end-to-end testing can continue.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def log(message: str) -> None:
    """Write a timestamped message to stdout so the backend can capture it."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[run_colmap] {timestamp} {message}", flush=True)


def run_command(command: list[str], cwd: Path | None = None) -> None:
    """Execute a subprocess and raise on failure with detailed output."""
    log(f"Running: {' '.join(command)}")
    process = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = process.stdout.decode(errors="ignore")
    if output:
        log(output)
    if process.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {process.returncode}: {' '.join(command)}")


def ensure_colmap_available(executable: str | None = None) -> str | None:
    """
    Returns the path to the COLMAP executable if available.
    The user can override via the COLMAP_BINARY environment variable.
    """
    candidate = executable or os.getenv("COLMAP_BINARY") or "colmap"
    return shutil.which(candidate)


def generate_placeholder_model(output_dir: Path, job_id: str) -> Path:
    """
    Write a minimal PLY file so downstream steps can proceed even without COLMAP.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "model_placeholder.ply"
    log(f"Generating placeholder model at {model_path}")
    model_path.write_text(
        "ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\n"
        "end_header\n0 0 0\n1 0 0\n0 1 0\n",
        encoding="utf-8",
    )
    return model_path


def run_colmap_pipeline(colmap_bin: str, input_dir: Path, output_dir: Path, job_id: str) -> Path:
    workspace = output_dir / "colmap_workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    sparse_dir = workspace / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)

    database_path = workspace / "database.db"

    # Step 1: feature extraction
    run_command(
        [
            colmap_bin,
            "feature_extractor",
            "--database_path",
            str(database_path),
            "--image_path",
            str(input_dir),
        ]
    )

    # Step 2: matching
    run_command(
        [
            colmap_bin,
            "exhaustive_matcher",
            "--database_path",
            str(database_path),
        ]
    )

    # Step 3: mapping (sparse reconstruction)
    run_command(
        [
            colmap_bin,
            "mapper",
            "--database_path",
            str(database_path),
            "--image_path",
            str(input_dir),
            "--output_path",
            str(sparse_dir),
        ]
    )

    # Step 4: convert the first sparse model to PLY as our usable artifact.
    first_model_dir = next((p for p in sparse_dir.iterdir() if p.is_dir()), None)
    if not first_model_dir:
        raise RuntimeError("COLMAP mapper did not produce a sparse model in the expected directory.")

    model_path = output_dir / "model.ply"
    run_command(
        [
            colmap_bin,
            "model_converter",
            "--input_path",
            str(first_model_dir),
            "--output_path",
            str(model_path),
            "--output_type",
            "PLY",
        ]
    )

    return model_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a COLMAP reconstruction pipeline.")
    parser.add_argument("--input", required=True, help="Directory containing the uploaded photos.")
    parser.add_argument("--output", required=True, help="Directory where the reconstructed model should be placed.")
    parser.add_argument("--job", default="", help="Job identifier (for logging purposes).")
    parser.add_argument("--colmap-binary", default=None, help="Optional path to the COLMAP executable.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_dir = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists():
        log(f"Input directory not found: {input_dir}")
        return 2

    colmap_bin = ensure_colmap_available(args.colmap_binary)
    job_id = args.job or "unknown-job"

    if colmap_bin is None:
        log("COLMAP binary not found. Generating placeholder model instead.")
        placeholder = generate_placeholder_model(output_dir, job_id)
        log(f"Placeholder model created at {placeholder}")
        return 0

    try:
        model_path = run_colmap_pipeline(colmap_bin, input_dir, output_dir, job_id)
    except Exception as exc:  # noqa: BLE001
        log(f"COLMAP pipeline failed: {exc}")
        placeholder = generate_placeholder_model(output_dir, job_id)
        log(f"Fallback placeholder model created at {placeholder}")
        return 1

    log(f"COLMAP pipeline finished. Model saved at {model_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
