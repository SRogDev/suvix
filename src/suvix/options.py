"""Typed extraction options with conservative defaults.

A small, explicit config object instead of a sprawling keyword-argument list.
Promote a setting here only when it materially improves developer control.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StrategyName = Literal["auto", "native_video", "selected_frames"]

STRATEGIES: tuple[str, ...] = ("auto", "native_video", "selected_frames")

SamplingMode = Literal["uniform", "scene_changes"]

SAMPLING_MODES: tuple[str, ...] = ("uniform", "scene_changes")


class ExtractionOptions(BaseModel):
    """Knobs controlling one extraction run. All resource-consuming settings
    have explicit bounds; defaults are deliberately conservative."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: StrategyName = "auto"
    max_frames: int = Field(default=8, ge=1, le=512)
    coarse_interval_seconds: float = Field(default=5.0, gt=0)
    # Sampling applies to the selected_frames strategy only. "scene_changes"
    # merges ffmpeg scene-transition candidates with a uniform floor (the
    # floor is always kept; see suvix.sampling.scene_changes). The two
    # scene_* knobs are ignored unless sampling == "scene_changes".
    sampling: SamplingMode = "uniform"
    scene_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    scene_floor_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    max_refinement_rounds: int = Field(default=2, ge=0, le=10)
    max_recovery_attempts: int = Field(default=2, ge=0, le=10)
    per_call_timeout_seconds: float | None = Field(default=120.0, gt=0)
    max_file_bytes: int | None = Field(default=None, gt=0)
    max_duration_seconds: float | None = Field(default=None, gt=0)
    enable_recovery: bool = True
    require_evidence: bool = False
    collect_usage: bool = True
