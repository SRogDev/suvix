"""Scene-change sampling: visual-transition candidates merged with a
uniform floor.

Semantics, stated honestly: a *scene change* here is a **visual transition**
— a frame whose ffmpeg ``scene`` score against its predecessor exceeds a
threshold. It is not a semantic event: a hard cut between two similar-luma
shots can score ~0, and a flash or fast pan inside one continuous event can
score high. Nothing in this module claims scene-change sampling is more
accurate than uniform sampling; no benchmark evidence for that exists.

Design (research-mandated, Phase 1: AKS arXiv:2502.21261, BOLT
arXiv:2503.02897, KeyFrame 2025): scene-change timestamps are an
**additional candidate source merged with a uniform floor, never a
replacement**. Pure relevance/cut-driven selection starves temporal
coverage — long uneventful stretches get no samples at all — so
:func:`merge_with_uniform_floor` always reserves
``ceil(max_frames * floor_fraction)`` of the budget for uniform samples
and only fills the remaining budget from scene candidates.

Detection shells out to ffmpeg's ``select='gt(scene,T)'`` filter with
``metadata=print`` and parses ``pts_time`` from its stderr log — the same
subprocess/error style as :mod:`suvix.media.frames`. Verified in this
environment (ffmpeg 8.1) on generated hard-cut clips: solid-color cuts
land exactly on the cut timestamps. The scan decodes the whole video, so
it is bounded by an explicit timeout and is deterministic for a given
file and threshold.

Integration: wired behind the explicit ``ExtractionOptions.sampling``
field (``"uniform"`` default, ``"scene_changes"`` opt-in). The planner
records ``sampling="scene_changes"`` / ``requires_scene_sampling=True`` on
the strategy decision, and ``suvix.extraction._run_selected_frames`` then
builds its coarse timestamps through :func:`make_scene_sampler` (run via
``asyncio.to_thread`` — detection blocks on ffmpeg) instead of
:func:`~suvix.sampling.uniform.uniform_timestamps`. Selecting it is always
the developer's explicit choice; the planner never picks it on its own,
and the default pipeline is unchanged. :func:`make_scene_sampler` also
remains available standalone as a callable matching the
:class:`~suvix.sampling.base.Sampler` protocol.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess

from suvix.errors import MediaProcessingError
from suvix.sampling.base import Sampler
from suvix.sampling.uniform import uniform_timestamps

# Scene candidates closer than this to an already-kept timestamp are
# dropped as duplicates; the uniform floor always wins the tie.
_DEDUPE_SECONDS = 0.05
# The detection pass decodes the entire video; bound it explicitly.
_SCAN_TIMEOUT_SECONDS = 300
_PTS_TIME_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


def _ensure_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise MediaProcessingError(
            "ffmpeg binary not found. Install it to enable scene-change "
            "detection (e.g. `apt install ffmpeg` on Debian/Ubuntu, "
            "`brew install ffmpeg` on macOS).",
            details={"binary": "ffmpeg"},
        )
    return path


def _validate_threshold(threshold: float) -> None:
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise MediaProcessingError(
            f"threshold must be a finite number in [0, 1], got {threshold}",
            details={"threshold": threshold},
        )


def _validate_floor_fraction(floor_fraction: float) -> None:
    if not math.isfinite(floor_fraction) or not 0.0 <= floor_fraction <= 1.0:
        raise MediaProcessingError(
            f"floor_fraction must be a finite number in [0, 1], got {floor_fraction}",
            details={"floor_fraction": floor_fraction},
        )


def _format_threshold(threshold: float) -> str:
    """Format a threshold for an ffmpeg filter expression (no exponents)."""
    return format(threshold, ".6f").rstrip("0").rstrip(".") or "0"


def _evenly_spaced_subset(items: list[float], budget: int) -> list[float]:
    """Deterministic evenly-spaced subset of ``items`` with ``budget`` items.

    Endpoints are included when ``budget >= 2``; a budget of 1 keeps the
    middle item. Returns ``items`` unchanged when it already fits.
    """
    if budget < 1:
        return []
    if len(items) <= budget:
        return list(items)
    if budget == 1:
        return [items[(len(items) - 1) // 2]]
    indices = [round(i * (len(items) - 1) / (budget - 1)) for i in range(budget)]
    return [items[i] for i in dict.fromkeys(indices)]


def scene_change_timestamps(
    video_path: str,
    *,
    threshold: float = 0.4,
    max_frames: int | None = None,
) -> list[float]:
    """Detect visual-transition timestamps (seconds) in ``video_path``.

    Runs ffmpeg's scene filter and returns the ascending presentation
    timestamps whose scene score is strictly greater than ``threshold``
    (an ffmpeg scene score in [0, 1]; higher means a more abrupt visual
    change). When ``max_frames`` is given and more candidates are found,
    an evenly-spaced deterministic subset of that size is returned.

    Raises :class:`~suvix.errors.MediaProcessingError` when the file does
    not exist, ffmpeg is missing, the scan times out, or ffmpeg fails
    (e.g. the file is not a readable video). Deterministic: the same file
    and threshold always produce the same timestamps.
    """
    _validate_threshold(threshold)
    if max_frames is not None and max_frames < 1:
        raise MediaProcessingError(
            f"max_frames must be at least 1, got {max_frames}",
            details={"max_frames": max_frames},
        )
    if not os.path.isfile(video_path):
        raise MediaProcessingError(
            f"video file not found: {video_path!r}",
            details={"path": video_path},
        )
    ffmpeg = _ensure_ffmpeg()
    select = f"select='gt(scene,{_format_threshold(threshold)})',metadata=print"
    try:
        result = subprocess.run(
            [ffmpeg, "-v", "info", "-i", video_path, "-vf", select, "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=_SCAN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaProcessingError(
            f"ffmpeg scene detection timed out after {_SCAN_TIMEOUT_SECONDS}s "
            f"for {video_path!r}",
            details={"path": video_path, "timeout_seconds": _SCAN_TIMEOUT_SECONDS},
        ) from exc
    except OSError as exc:
        raise MediaProcessingError(
            f"ffmpeg could not be executed for scene detection: {exc}",
            details={"path": video_path, "binary": "ffmpeg"},
        ) from exc
    if result.returncode != 0:
        raise MediaProcessingError(
            f"ffmpeg failed to detect scene changes in {video_path!r}: "
            f"{result.stderr.strip() or 'unknown error'}",
            details={"path": video_path, "returncode": result.returncode},
        )

    timestamps: list[float] = []
    for line in result.stderr.splitlines():
        # pts_time also appears in unrelated ffmpeg log lines; only the
        # metadata filter's frame headers are scene candidates.
        if "Parsed_metadata" not in line:
            continue
        match = _PTS_TIME_RE.search(line)
        if match:
            try:
                timestamps.append(float(match.group(1)))
            except ValueError:
                continue
    timestamps = sorted(set(timestamps))
    if max_frames is not None and len(timestamps) > max_frames:
        timestamps = _evenly_spaced_subset(timestamps, max_frames)
    return timestamps


def merge_with_uniform_floor(
    scene_timestamps: list[float],
    *,
    duration_seconds: float,
    max_frames: int,
    floor_fraction: float = 0.5,
) -> list[float]:
    """Merge scene candidates with a guaranteed uniform floor.

    ``ceil(max_frames * floor_fraction)`` of the budget is reserved for
    uniform samples (via :func:`~suvix.sampling.uniform.uniform_timestamps`);
    the uniform floor is always a subset of the result. The remaining
    budget is filled with scene candidates in ascending order; when
    candidates exceed the remaining budget, an evenly-spaced deterministic
    subset is kept. Candidates outside ``[0, duration_seconds)``, and any
    candidate closer than 0.05s to an already-kept timestamp (uniform
    floor first, then earlier scene candidates), are dropped. Returns
    ascending timestamps, at most ``max_frames`` of them.
    """
    if duration_seconds <= 0:
        raise MediaProcessingError(
            f"duration_seconds must be positive, got {duration_seconds}",
            details={"duration_seconds": duration_seconds},
        )
    if max_frames < 1:
        raise MediaProcessingError(
            f"max_frames must be at least 1, got {max_frames}",
            details={"max_frames": max_frames},
        )
    _validate_floor_fraction(floor_fraction)

    floor_budget = math.ceil(max_frames * floor_fraction)
    floor = (
        uniform_timestamps(duration_seconds=duration_seconds, max_frames=floor_budget)
        if floor_budget > 0
        else []
    )
    remaining = max_frames - len(floor)
    if remaining <= 0:
        return sorted(floor)

    candidates = sorted(
        {
            float(t)
            for t in scene_timestamps
            if math.isfinite(float(t)) and 0.0 <= float(t) < duration_seconds
        }
    )
    kept: list[float] = []
    for candidate in candidates:
        if any(abs(candidate - t) < _DEDUPE_SECONDS for t in floor):
            continue
        if any(abs(candidate - t) < _DEDUPE_SECONDS for t in kept):
            continue
        kept.append(candidate)
    if len(kept) > remaining:
        kept = _evenly_spaced_subset(kept, remaining)
    return sorted([*floor, *kept])


def make_scene_sampler(
    video_path: str,
    *,
    threshold: float = 0.4,
    floor_fraction: float = 0.5,
) -> Sampler:
    """Build a :class:`~suvix.sampling.base.Sampler` for one video file.

    The returned callable closes over ``video_path`` (the ``Sampler``
    protocol itself only receives ``duration_seconds``/``max_frames``).
    Each call re-runs scene detection on the file and merges the result
    with the uniform floor; detection failures propagate as
    :class:`~suvix.errors.MediaProcessingError`. Arguments are validated
    eagerly so misconfiguration fails here, not mid-pipeline.
    """
    _validate_threshold(threshold)
    _validate_floor_fraction(floor_fraction)

    def sampler(*, duration_seconds: float, max_frames: int) -> list[float]:
        scene = scene_change_timestamps(video_path, threshold=threshold)
        return merge_with_uniform_floor(
            scene,
            duration_seconds=duration_seconds,
            max_frames=max_frames,
            floor_fraction=floor_fraction,
        )

    return sampler
