"""Unit tests for suvix.sampling.scene_changes.

Detection tests run against real clips generated with ffmpeg lavfi (solid
colors joined by hard cuts). Merge/factory-validation tests are pure and run
even without ffmpeg. The whole module follows the existing media-test
convention of skipping media-dependent tests cleanly when ffmpeg is absent.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from suvix.errors import MediaProcessingError
from suvix.sampling.scene_changes import (
    make_scene_sampler,
    merge_with_uniform_floor,
    scene_change_timestamps,
)
from suvix.sampling.uniform import uniform_timestamps

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg binary not available",
)


def _make_cut_clip(path: Path) -> Path:
    """8s clip with hard cuts at 2.0s and 5.0s: red 0-2s, lime 2-5s, blue 5-8s.

    Lime (not CSS green) is used for the middle segment on purpose: ffmpeg's
    scene score is luma-heavy and red -> #008000 green scores ~0.0 because
    both colors have nearly identical luma, while red -> lime scores ~0.64.
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
            "color=c=red:s=320x240:d=2:r=10",
            "-f",
            "lavfi",
            "-i",
            "color=c=lime:s=320x240:d=3:r=10",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:d=3:r=10",
            "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def _make_static_clip(path: Path) -> Path:
    """3s of a single solid color: no visual transitions at all."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x240:d=3:r=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="module")
def cut_clip_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _make_cut_clip(tmp_path_factory.mktemp("scene") / "cuts.mp4")


@pytest.fixture(scope="module")
def static_clip_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _make_static_clip(tmp_path_factory.mktemp("scene") / "static.mp4")


# ---------------------------------------------------------------------------
# scene_change_timestamps: real-ffmpeg detection
# ---------------------------------------------------------------------------


@requires_ffmpeg
def test_detects_hard_cuts_within_tolerance(cut_clip_path):
    timestamps = scene_change_timestamps(str(cut_clip_path), threshold=0.4)
    assert len(timestamps) == 2
    assert any(abs(t - 2.0) <= 0.2 for t in timestamps)
    assert any(abs(t - 5.0) <= 0.2 for t in timestamps)


@requires_ffmpeg
def test_static_video_yields_no_scene_timestamps(static_clip_path):
    assert scene_change_timestamps(str(static_clip_path), threshold=0.4) == []


@requires_ffmpeg
def test_detection_is_deterministic(cut_clip_path):
    first = scene_change_timestamps(str(cut_clip_path))
    second = scene_change_timestamps(str(cut_clip_path))
    assert first == second


@requires_ffmpeg
def test_detection_returns_sorted_timestamps(cut_clip_path):
    timestamps = scene_change_timestamps(str(cut_clip_path))
    assert timestamps == sorted(timestamps)


@requires_ffmpeg
def test_max_frames_caps_candidates_deterministically(cut_clip_path):
    capped = scene_change_timestamps(str(cut_clip_path), max_frames=1)
    assert len(capped) == 1
    # The evenly-spaced subset of [~2.0, ~5.0] with budget 1 keeps one cut.
    assert any(abs(t - cut) <= 0.2 for t in capped for cut in (2.0, 5.0))
    assert scene_change_timestamps(str(cut_clip_path), max_frames=1) == capped


@requires_ffmpeg
def test_missing_file_raises_media_error(tmp_path):
    with pytest.raises(MediaProcessingError, match="not found"):
        scene_change_timestamps(str(tmp_path / "does-not-exist.mp4"))


@requires_ffmpeg
def test_non_video_file_raises_media_error(tmp_path):
    bogus = tmp_path / "not-a-video.mp4"
    bogus.write_text("this is not a video", encoding="utf-8")
    with pytest.raises(MediaProcessingError, match="ffmpeg"):
        scene_change_timestamps(str(bogus))


@requires_ffmpeg
def test_missing_ffmpeg_raises_media_error(cut_clip_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(MediaProcessingError, match="ffmpeg"):
        scene_change_timestamps(str(cut_clip_path))


def test_invalid_threshold_raises():
    with pytest.raises(MediaProcessingError):
        scene_change_timestamps("whatever.mp4", threshold=1.5)
    with pytest.raises(MediaProcessingError):
        scene_change_timestamps("whatever.mp4", threshold=-0.1)


def test_invalid_max_frames_raises():
    with pytest.raises(MediaProcessingError):
        scene_change_timestamps("whatever.mp4", max_frames=0)


# ---------------------------------------------------------------------------
# merge_with_uniform_floor: pure merge semantics
# ---------------------------------------------------------------------------


def test_merge_floor_is_always_subset_of_result():
    result = merge_with_uniform_floor(
        [1.0, 3.0], duration_seconds=10.0, max_frames=8, floor_fraction=0.5
    )
    floor = uniform_timestamps(duration_seconds=10.0, max_frames=4)
    assert set(floor) <= set(result)
    assert result == sorted(result)
    assert len(result) <= 8


def test_merge_respects_budget_with_many_scene_candidates():
    scene = [i * 0.5 for i in range(20)]
    result = merge_with_uniform_floor(
        scene, duration_seconds=10.0, max_frames=6, floor_fraction=0.5
    )
    floor = uniform_timestamps(duration_seconds=10.0, max_frames=3)
    assert len(result) <= 6
    assert set(floor) <= set(result)
    assert result == sorted(result)


def test_merge_floor_fraction_one_returns_uniform_only():
    result = merge_with_uniform_floor(
        [1.0, 2.0, 3.0], duration_seconds=10.0, max_frames=4, floor_fraction=1.0
    )
    assert result == uniform_timestamps(duration_seconds=10.0, max_frames=4)


def test_merge_floor_fraction_zero_uses_scene_only():
    result = merge_with_uniform_floor(
        [1.0, 3.0], duration_seconds=10.0, max_frames=4, floor_fraction=0.0
    )
    assert result == [1.0, 3.0]


def test_merge_dedupes_scene_near_uniform_keeping_uniform():
    # floor for (10s, 4 frames, 0.5) is uniform(10, 2) == [0.0, 5.0];
    # 5.02 is within 0.05s of the uniform 5.0 and must be dropped.
    result = merge_with_uniform_floor(
        [5.02, 7.0], duration_seconds=10.0, max_frames=4, floor_fraction=0.5
    )
    assert result == [0.0, 5.0, 7.0]


def test_merge_dedupes_scene_candidates_against_each_other():
    result = merge_with_uniform_floor(
        [7.0, 7.02, 7.5], duration_seconds=10.0, max_frames=6, floor_fraction=0.5
    )
    assert 7.0 in result
    assert 7.02 not in result
    assert 7.5 in result


def test_merge_evenly_spaced_subset_when_scene_exceeds_remaining_budget():
    # floor == [0.0, 50.0], remaining budget 2, 8 scene candidates:
    # the evenly-spaced subset keeps the first and last candidates.
    scene = [10.0, 20.0, 30.0, 40.0, 60.0, 70.0, 80.0, 90.0]
    result = merge_with_uniform_floor(
        scene, duration_seconds=100.0, max_frames=4, floor_fraction=0.5
    )
    assert result == [0.0, 10.0, 50.0, 90.0]


def test_merge_filters_out_of_range_scene_timestamps():
    result = merge_with_uniform_floor(
        [-1.0, 10.0, 999.0], duration_seconds=10.0, max_frames=4, floor_fraction=0.5
    )
    assert result == uniform_timestamps(duration_seconds=10.0, max_frames=2)


def test_merge_empty_scene_returns_floor():
    result = merge_with_uniform_floor(
        [], duration_seconds=10.0, max_frames=4, floor_fraction=0.5
    )
    assert result == uniform_timestamps(duration_seconds=10.0, max_frames=2)


def test_merge_is_deterministic():
    scene = [0.7, 1.3, 2.9, 4.1, 8.8]
    first = merge_with_uniform_floor(scene, duration_seconds=10.0, max_frames=6)
    second = merge_with_uniform_floor(scene, duration_seconds=10.0, max_frames=6)
    assert first == second


def test_merge_invalid_inputs_raise():
    with pytest.raises(MediaProcessingError):
        merge_with_uniform_floor([], duration_seconds=0.0, max_frames=4)
    with pytest.raises(MediaProcessingError):
        merge_with_uniform_floor([], duration_seconds=10.0, max_frames=0)
    with pytest.raises(MediaProcessingError):
        merge_with_uniform_floor([], duration_seconds=10.0, max_frames=4, floor_fraction=1.5)
    with pytest.raises(MediaProcessingError):
        merge_with_uniform_floor([], duration_seconds=10.0, max_frames=4, floor_fraction=-0.1)


# ---------------------------------------------------------------------------
# make_scene_sampler: Sampler-protocol factory
# ---------------------------------------------------------------------------


@requires_ffmpeg
def test_scene_sampler_merges_floor_and_scene_cuts(cut_clip_path):
    sampler = make_scene_sampler(str(cut_clip_path))
    result = sampler(duration_seconds=8.0, max_frames=8)
    floor = uniform_timestamps(duration_seconds=8.0, max_frames=4)
    assert set(floor) <= set(result)
    assert result == sorted(result)
    assert len(result) <= 8
    # The 5.0s cut is not within 0.05s of any uniform floor timestamp
    # ([0, 2, 4, 6]) so it must survive the merge.
    assert any(abs(t - 5.0) <= 0.2 for t in result)


@requires_ffmpeg
def test_scene_sampler_propagates_missing_file_error(tmp_path):
    sampler = make_scene_sampler(str(tmp_path / "missing.mp4"))
    with pytest.raises(MediaProcessingError):
        sampler(duration_seconds=8.0, max_frames=4)


def test_scene_sampler_validates_arguments_eagerly():
    with pytest.raises(MediaProcessingError):
        make_scene_sampler("whatever.mp4", threshold=2.0)
    with pytest.raises(MediaProcessingError):
        make_scene_sampler("whatever.mp4", floor_fraction=-1.0)
