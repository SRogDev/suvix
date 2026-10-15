"""Frame extraction at explicit timestamps via ffmpeg.

Extraction uses accurate seeking (``-ss`` *after* ``-i``) and verifies the
real presentation timestamp by parsing ``pts_time`` from the ``showinfo``
filter's stderr output:

- When ``pts_time`` parses, ``pts_verified=True`` and ``timestamp_seconds``
  is the actual presentation timestamp — never derived from the nominal
  frame rate.
- When it does not parse (e.g. a container that reports no usable pts),
  ``pts_verified=False`` and ``timestamp_seconds`` falls back to the requested
  timestamp. Callers must treat unverified timestamps as approximate.

Each extraction runs in its own temp directory (created per call, never
shared), which is removed on success, on failure, and on cancellation as far
as the context manager allows. Only image bytes cross the boundary — temp
paths are never exposed in public results.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile

from pydantic import BaseModel

from suvix.errors import MediaProcessingError

# Frames are decoded and re-encoded; cap the width so one frame cannot
# allocate an unbounded amount of memory.
_MAX_WIDTH = 1280
# Cap concurrent ffmpeg processes per extract_frames_at call.
_MAX_CONCURRENT_EXTRACTS = 8
_PTS_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


def make_frame_id(index: int, timestamp: float) -> str:
    """Build the canonical frame id, e.g. ``f0003@1.500s``."""
    return f"f{index:04d}@{timestamp:.3f}s"


class SampledFrame(BaseModel):
    """One extracted frame, with its bytes in memory.

    ``timestamp_seconds`` is the verified presentation timestamp when
    ``pts_verified`` is true, otherwise the requested timestamp (approximate).
    """

    frame_id: str
    timestamp_seconds: float
    pts_verified: bool
    image_bytes: bytes
    mime_type: str = "image/jpeg"
    width: int | None = None
    height: int | None = None


class FrameRegistry:
    """Maps frame ids to their timestamps for one extraction run.

    Evidence validation later checks claimed frame references against this
    registry; ids are only ever registered for frames actually extracted.
    """

    def __init__(self) -> None:
        self._timestamps: dict[str, float] = {}

    def register(self, frame_id: str, timestamp_seconds: float) -> None:
        """Record ``frame_id`` as extracted at ``timestamp_seconds``."""
        self._timestamps[frame_id] = timestamp_seconds

    def lookup(self, frame_id: str) -> float | None:
        """Return the registered timestamp, or ``None`` if unknown."""
        return self._timestamps.get(frame_id)

    def known_ids(self) -> list[str]:
        """Frame ids in registration order."""
        return list(self._timestamps)


def _ensure_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise MediaProcessingError(
            "ffmpeg binary not found. Install it to enable frame extraction "
            "(e.g. `apt install ffmpeg` on Debian/Ubuntu, `brew install ffmpeg` "
            "on macOS).",
            details={"binary": "ffmpeg"},
        )
    return path


def _extract_one_sync(
    ffmpeg: str, path: str, index: int, requested: float, out_dir: str
) -> SampledFrame:
    out_path = os.path.join(out_dir, f"frame_{index:04d}.jpg")
    result = subprocess.run(
        [
            ffmpeg,
            # -copyts preserves input presentation timestamps on the decoded
            # frames; without it the mp4 edit list shifts output pts to 0 and
            # showinfo would report pts_time relative to the seek point.
            # Default verbosity is kept: showinfo logs at info level, and
            # `-v error` would suppress its pts_time lines entirely.
            "-copyts",
            "-ss",
            f"{requested:.3f}",
            "-i",
            path,
            "-frames:v",
            "1",
            "-vf",
            f"scale={_MAX_WIDTH}:-2,showinfo",
            "-q:v",
            "3",
            "-y",
            out_path,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 or not os.path.isfile(out_path):
        raise MediaProcessingError(
            f"ffmpeg failed to extract frame at t={requested:.3f}s from {path!r}: "
            f"{result.stderr.strip() or 'unknown error'}",
            details={"path": path, "timestamp_seconds": requested},
        )
    with open(out_path, "rb") as fh:
        image_bytes = fh.read()

    pts_verified = False
    timestamp = requested
    for line in result.stderr.splitlines():
        match = _PTS_RE.search(line)
        if match:
            try:
                timestamp = float(match.group(1))
            except ValueError:
                continue
            else:
                pts_verified = True
                break

    frame_id = make_frame_id(index, timestamp)
    return SampledFrame(
        frame_id=frame_id,
        timestamp_seconds=timestamp,
        pts_verified=pts_verified,
        image_bytes=image_bytes,
        width=None,  # decoded below when possible
        height=None,
    )


def _probe_jpeg_dimensions(image_bytes: bytes) -> tuple[int | None, int | None]:
    """Parse width/height from a JPEG SOF marker without extra dependencies."""
    i = 2  # skip SOI (ff d8)
    data = image_bytes
    while i + 9 < len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        i += 2
        if marker in (0xC0, 0xC1, 0xC2):  # SOF0/1/2
            height = int.from_bytes(data[i + 3 : i + 5], "big")
            width = int.from_bytes(data[i + 5 : i + 7], "big")
            return width, height
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        length = int.from_bytes(data[i : i + 2], "big")
        if length < 2:
            break
        i += length
    return None, None


def _extract_one(
    ffmpeg: str, path: str, index: int, requested: float, out_dir: str
) -> SampledFrame:
    frame = _extract_one_sync(ffmpeg, path, index, requested, out_dir)
    width, height = _probe_jpeg_dimensions(frame.image_bytes)
    return frame.model_copy(update={"width": width, "height": height})


async def _extract_one_async(
    semaphore: asyncio.Semaphore, ffmpeg: str, path: str, index: int, requested: float, out_dir: str
) -> SampledFrame:
    async with semaphore:
        return await asyncio.to_thread(_extract_one, ffmpeg, path, index, requested, out_dir)


async def extract_frames_at(
    path: str,
    timestamps: list[float],
    *,
    max_frames: int | None = None,
    registry: FrameRegistry | None = None,
) -> list[SampledFrame]:
    """Extract one JPEG frame per requested timestamp.

    Returns frames in the same order as ``timestamps``. Raises
    :class:`~suvix.errors.MediaProcessingError` when the frame budget is
    exceeded, ffmpeg is missing, or any extraction fails. An empty timestamp
    list returns ``[]`` without touching ffmpeg.
    """
    if max_frames is not None and len(timestamps) > max_frames:
        raise MediaProcessingError(
            f"requested {len(timestamps)} frames exceeds max_frames={max_frames}",
            details={"requested": len(timestamps), "max_frames": max_frames},
        )
    if not timestamps:
        return []
    ffmpeg = _ensure_ffmpeg()

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_EXTRACTS)
    with tempfile.TemporaryDirectory(prefix="suvix-frames-") as tmpdir:
        coros = [
            _extract_one_async(semaphore, ffmpeg, path, index, requested, tmpdir)
            for index, requested in enumerate(timestamps)
        ]
        frames = await asyncio.gather(*coros)
    if registry is not None:
        for frame in frames:
            registry.register(frame.frame_id, frame.timestamp_seconds)
    return list(frames)
