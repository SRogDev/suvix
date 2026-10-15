"""Shared fixtures for media unit tests (offline: clips generated with ffmpeg)."""

import subprocess
from pathlib import Path

import pytest


def make_test_clip(
    path: Path,
    *,
    duration: float = 4.0,
    size: str = "320x240",
    rate: int = 30,
    with_audio: bool = False,
) -> Path:
    """Generate a deterministic testsrc clip (H.264, yuv420p) at ``path``."""
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size={size}:rate={rate}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration}"]
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += ["-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture()
def clip_path(tmp_path: Path) -> Path:
    """A 4s, 320x240, 30fps CFR clip without audio."""
    return make_test_clip(tmp_path / "clip.mp4")


@pytest.fixture()
def clip_with_audio_path(tmp_path: Path) -> Path:
    """A 4s clip with a sine-wave audio track."""
    return make_test_clip(tmp_path / "clip_audio.mp4", with_audio=True)


def make_vfr_clip(path: Path) -> Path:
    """A 4s clip that is genuinely variable-frame-rate: 2s of 30fps testsrc
    followed by 2s of 10fps testsrc (concatenated with ``-vsync vfr``).

    The container's nominal ``avg_frame_rate`` (30fps) does NOT describe the
    second half, so only parsed presentation timestamps are honest here.
    """
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=30",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=10",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0",
            "-vsync",
            "vfr",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture()
def vfr_clip_path(tmp_path: Path) -> Path:
    """A 4s VFR clip (30fps for 2s, then 10fps for 2s)."""
    return make_vfr_clip(tmp_path / "vfr.mp4")
