"""Video metadata inspection via ffprobe.

ffprobe is an optional external dependency: its absence raises a clear,
actionable :class:`~suvix.errors.MediaProcessingError` instead of a raw
``FileNotFoundError``. Blocking subprocess calls run in a worker thread via
``asyncio.to_thread`` so the event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from fractions import Fraction

from pydantic import BaseModel

from suvix.errors import MediaProcessingError, UnsupportedMediaError


class VideoMetadata(BaseModel):
    """Probe results for one local video file. Fields are ``None`` when the
    container does not report them; ``file_size_bytes`` always comes from the
    filesystem."""

    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: float | None
    codec: str | None
    has_audio: bool = False
    file_size_bytes: int


def _ensure_ffprobe() -> str:
    path = shutil.which("ffprobe")
    if path is None:
        raise MediaProcessingError(
            "ffprobe binary not found. Install it to enable media inspection "
            "(e.g. `apt install ffmpeg` on Debian/Ubuntu, `brew install ffmpeg` "
            "on macOS) or skip media-dependent features.",
            details={"binary": "ffprobe"},
        )
    return path


def _parse_fps(value: str | None) -> float | None:
    """Parse ffprobe's ``avg_frame_rate``, which may be a fraction like
    ``30000/1001`` or ``0/0`` for unknown."""
    if not value:
        return None
    try:
        fraction = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    if fraction.denominator == 0 or fraction <= 0:
        return None
    return float(fraction)


def _inspect_sync(path: str) -> VideoMetadata:
    ffprobe = _ensure_ffprobe()
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-print_format",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise MediaProcessingError(
            f"ffprobe failed for {path!r}: {result.stderr.strip() or 'unknown error'}",
            details={"path": path, "returncode": result.returncode},
        )
    try:
        probe = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaProcessingError(
            f"ffprobe returned invalid JSON for {path!r}: {exc}",
            details={"path": path},
        ) from exc

    fmt = probe.get("format", {}) or {}
    duration_raw = fmt.get("duration")
    try:
        duration = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration = None

    width = height = fps = codec = None
    has_audio = False
    for stream in probe.get("streams", []) or []:
        codec_type = stream.get("codec_type")
        if codec_type == "video" and width is None:
            width = stream.get("width")
            height = stream.get("height")
            fps = _parse_fps(stream.get("avg_frame_rate"))
            codec = stream.get("codec_name")
        elif codec_type == "audio":
            has_audio = True

    return VideoMetadata(
        duration_seconds=duration,
        width=width,
        height=height,
        fps=fps,
        codec=codec,
        has_audio=has_audio,
        file_size_bytes=os.path.getsize(path),
    )


async def inspect_video(
    path: str,
    *,
    max_file_bytes: int | None = None,
    max_duration_seconds: float | None = None,
) -> VideoMetadata:
    """Inspect a local video file with ffprobe.

    Raises :class:`~suvix.errors.UnsupportedMediaError` when the file does not
    exist or exceeds ``max_file_bytes``/``max_duration_seconds`` (the error
    message names the exceeded limit), and
    :class:`~suvix.errors.MediaProcessingError` when ffprobe is missing or
    fails.
    """
    if not os.path.isfile(path):
        raise UnsupportedMediaError(
            f"video file not found: {path!r}",
            details={"path": path},
        )
    if max_file_bytes is not None:
        size = os.path.getsize(path)
        if size > max_file_bytes:
            raise UnsupportedMediaError(
                f"file size {size} bytes exceeds max_file_bytes={max_file_bytes}",
                details={"file_size_bytes": size, "max_file_bytes": max_file_bytes},
            )
    metadata = await asyncio.to_thread(_inspect_sync, path)
    if max_duration_seconds is not None and metadata.duration_seconds is not None:
        if metadata.duration_seconds > max_duration_seconds:
            raise UnsupportedMediaError(
                f"duration {metadata.duration_seconds:.3f}s exceeds "
                f"max_duration_seconds={max_duration_seconds}",
                details={
                    "duration_seconds": metadata.duration_seconds,
                    "max_duration_seconds": max_duration_seconds,
                },
            )
    return metadata
