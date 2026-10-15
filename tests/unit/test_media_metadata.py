"""Unit tests for suvix.media.metadata (offline: clips generated with ffmpeg)."""

import shutil

import pytest

from suvix.errors import MediaProcessingError, UnsupportedMediaError
from suvix.media.metadata import VideoMetadata, inspect_video

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe binaries not available",
)


async def test_inspect_real_file(clip_path):
    meta = await inspect_video(str(clip_path))
    assert isinstance(meta, VideoMetadata)
    assert meta.duration_seconds == pytest.approx(4.0, abs=0.05)
    assert meta.width == 320
    assert meta.height == 240
    assert meta.fps == pytest.approx(30.0, abs=0.1)
    assert meta.codec == "h264"
    assert meta.has_audio is False
    assert meta.file_size_bytes > 0


async def test_inspect_detects_audio(clip_with_audio_path):
    meta = await inspect_video(str(clip_with_audio_path))
    assert meta.has_audio is True


async def test_missing_file_raises_unsupported():
    with pytest.raises(UnsupportedMediaError, match="not found|cannot|missing"):
        await inspect_video("/nonexistent/path/clip.mp4")


async def test_max_file_bytes_exceeded(clip_path):
    size = clip_path.stat().st_size
    with pytest.raises(UnsupportedMediaError, match="max_file_bytes"):
        await inspect_video(str(clip_path), max_file_bytes=size - 1)


async def test_max_file_bytes_not_exceeded(clip_path):
    size = clip_path.stat().st_size
    meta = await inspect_video(str(clip_path), max_file_bytes=size)
    assert meta.file_size_bytes == size


async def test_max_duration_seconds_exceeded(clip_path):
    with pytest.raises(UnsupportedMediaError, match="max_duration_seconds"):
        await inspect_video(str(clip_path), max_duration_seconds=1.0)


async def test_max_duration_seconds_not_exceeded(clip_path):
    meta = await inspect_video(str(clip_path), max_duration_seconds=60.0)
    assert meta.duration_seconds == pytest.approx(4.0, abs=0.05)


async def test_ffprobe_absent_raises_media_processing_error(clip_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(MediaProcessingError, match="ffprobe"):
        await inspect_video(str(clip_path))


async def test_corrupt_file_raises_media_processing_error(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video file")
    with pytest.raises(MediaProcessingError):
        await inspect_video(str(bad))
