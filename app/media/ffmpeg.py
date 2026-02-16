from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def photo_to_video(
    *,
    image_path: Path,
    output_path: Path,
    seconds: int,
    fps: int,
) -> None:
    ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-t",
        str(max(1, seconds)),
        "-vf",
        f"fps={max(1, fps)},format=yuv420p,scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    _run(command)


def album_to_video(
    *,
    image_paths: list[Path],
    output_path: Path,
    slide_seconds: int,
    fps: int,
) -> None:
    ensure_ffmpeg()
    if not image_paths:
        raise RuntimeError("album_to_video requires at least one image")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    slide_seconds = max(1, slide_seconds)
    fps = max(1, fps)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        concat_file = Path(f.name)
        for path in image_paths:
            escaped = _concat_escape(path)
            f.write(f"file '{escaped}'\n")
            f.write(f"duration {slide_seconds}\n")
        escaped_last = _concat_escape(image_paths[-1])
        f.write(f"file '{escaped_last}'\n")

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-vf",
        f"fps={fps},format=yuv420p,scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    try:
        _run(command)
    finally:
        concat_file.unlink(missing_ok=True)


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required but not found in PATH")


def _run(command: list[str]) -> None:
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"ffmpeg failed with code {proc.returncode}: {stderr}")


def _concat_escape(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "'\\''")

