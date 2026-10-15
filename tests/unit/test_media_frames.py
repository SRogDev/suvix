"""Unit tests for suvix.media.frames (offline: clips generated with ffmpeg)."""

import os
import shutil
import tempfile

import pytest

from suvix.errors import MediaProcessingError
from suvix.media.frames import (
    FrameRegistry,
    SampledFrame,
    extract_frames_at,
    make_frame_id,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe binaries not available",
)


def test_make_frame_id_format():
    assert make_frame_id(3, 1.5) == "f0003@1.500s"


def test_make_frame_id_pads_index():
    assert make_frame_id(42, 0.123456) == "f0042@0.123s"


def test_registry_register_and_lookup():
    registry = FrameRegistry()
    assert registry.lookup("f0000@0.500s") is None
    registry.register("f0000@0.500s", 0.5)
    registry.register("f0001@1.500s", 1.5)
    assert registry.lookup("f0000@0.500s") == 0.5
    assert registry.lookup("f0001@1.500s") == 1.5
    assert registry.known_ids() == ["f0000@0.500s", "f0001@1.500s"]


async def test_extract_frames_at_timestamps(clip_path):
    timestamps = [0.5, 1.5, 2.5]
    frames = await extract_frames_at(str(clip_path), timestamps)
    assert len(frames) == 3
    for index, (frame, requested) in enumerate(zip(frames, timestamps, strict=True)):
        assert isinstance(frame, SampledFrame)
        assert frame.frame_id == make_frame_id(index, frame.timestamp_seconds)
        assert frame.timestamp_seconds == pytest.approx(requested, abs=0.05)
        assert frame.mime_type == "image/jpeg"
        assert frame.image_bytes[:3] == b"\xff\xd8\xff"  # JPEG magic bytes
        assert frame.width is not None and frame.width <= 1280
        assert frame.height is not None and frame.height > 0


async def test_extract_frames_pts_verified_for_cfr(clip_path):
    # A constant-frame-rate testsrc clip: extracted pts must match the request.
    frames = await extract_frames_at(str(clip_path), [0.5, 1.5, 2.5])
    assert all(frame.pts_verified for frame in frames)


async def test_extract_frames_pts_verified_for_vfr(vfr_clip_path):
    # The second half runs at 10fps while the container claims 30fps: only a
    # parsed presentation timestamp is honest. t=2.5 lands on a real 10fps
    # frame boundary (2.0, 2.1, ..., 2.5).
    frames = await extract_frames_at(str(vfr_clip_path), [2.5])
    assert len(frames) == 1
    assert frames[0].pts_verified is True
    assert frames[0].timestamp_seconds == pytest.approx(2.5, abs=0.05)


async def test_extract_frames_populates_registry(clip_path):
    registry = FrameRegistry()
    frames = await extract_frames_at(str(clip_path), [0.5, 1.5], registry=registry)
    assert len(registry.known_ids()) == 2
    for frame in frames:
        assert registry.lookup(frame.frame_id) == pytest.approx(frame.timestamp_seconds)


async def test_extract_frames_over_budget_raises(clip_path):
    with pytest.raises(MediaProcessingError, match="max_frames"):
        await extract_frames_at(str(clip_path), [0.5, 1.5, 2.5], max_frames=2)


async def test_extract_frames_empty_list_returns_empty(clip_path):
    assert await extract_frames_at(str(clip_path), []) == []


async def test_extract_frames_cleans_temp_dir_on_success(clip_path, monkeypatch):
    created: list[str] = []
    real_tmpdir = tempfile.TemporaryDirectory

    def tracking_tmpdir(*args, **kwargs):
        tmp = real_tmpdir(*args, **kwargs)
        created.append(tmp.name)
        return tmp

    monkeypatch.setattr(tempfile, "TemporaryDirectory", tracking_tmpdir)
    await extract_frames_at(str(clip_path), [0.5])
    assert created, "expected at least one temp dir to be created"
    assert all(not os.path.exists(path) for path in created)


async def test_extract_frames_cleans_temp_dir_on_failure(clip_path, monkeypatch, tmp_path):
    created: list[str] = []
    real_tmpdir = tempfile.TemporaryDirectory

    def tracking_tmpdir(*args, **kwargs):
        tmp = real_tmpdir(*args, **kwargs)
        created.append(tmp.name)
        return tmp

    monkeypatch.setattr(tempfile, "TemporaryDirectory", tracking_tmpdir)
    missing = tmp_path / "does-not-exist.mp4"
    with pytest.raises(MediaProcessingError):
        await extract_frames_at(str(missing), [0.5])
    assert created, "expected at least one temp dir to be created"
    assert all(not os.path.exists(path) for path in created)


async def test_extract_frames_ffmpeg_absent_raises(clip_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(MediaProcessingError, match="ffmpeg"):
        await extract_frames_at(str(clip_path), [0.5])
