"""Public result contracts.

The extracted business ``data`` is always kept separate from execution
metadata: ``evidence``, ``validation``, ``usage``, and ``execution``.
One modeling approach is used consistently: pydantic models.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvidenceRef(BaseModel):
    """A normalized reference connecting an extracted claim to observed video
    material.

    ``ref_type`` is honest about provenance:

    - ``provider_reported``: timestamp came from the provider; Suvix did not
      independently verify which frames the provider inspected.
    - ``frame``: Suvix extracted this exact frame locally (timestamp preserved).
    - ``segment``: the claim refers to a time interval of the video.
    - ``description``: model-generated textual evidence, not a timestamp.
    """

    model_config = ConfigDict(extra="forbid")

    ref_type: Literal["provider_reported", "frame", "segment", "description"] = (
        "provider_reported"
    )
    timestamp_seconds: float | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    frame_id: str | None = None
    segment_id: str | None = None
    note: str | None = None

    @field_validator("timestamp_seconds", "start_seconds", "end_seconds")
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("evidence timestamps must be finite")
        return value

    @model_validator(mode="after")
    def _interval_ordered(self) -> EvidenceRef:
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.start_seconds > self.end_seconds
        ):
            raise ValueError("evidence start_seconds must not exceed end_seconds")
        return self


class ValidationIssue(BaseModel):
    """One structural or semantic problem found during validation."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    field: str | None = None  # JSON-pointer style, e.g. "/events/0/type"
    severity: Literal["error", "warning"] = "error"


class ValidationReport(BaseModel):
    """Outcome of local structural (+ deterministic semantic) validation."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class UsageReport(BaseModel):
    """Provider-reported usage plus local counters. Missing provider values
    stay ``None`` — Suvix never invents usage numbers."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    provider_requests: int = 0
    recovery_requests: int = 0
    sampled_frames: int = 0
    video_duration_seconds: float | None = None
    latency_seconds: float = 0.0
    estimated_cost_usd: float | None = None
    cost_basis: Literal["measured", "estimated", "unavailable"] = "unavailable"
    raw: dict[str, Any] = Field(default_factory=dict)


class ExecutionMetadata(BaseModel):
    """How the extraction was performed. Recorded, never hidden."""

    model_config = ConfigDict(extra="forbid")

    strategy: str
    strategy_reason: str
    provider: str
    model: str
    stages: list[str] = Field(default_factory=list)
    refinement_rounds: int = 0
    recovery_attempts: int = 0
    validation_status: Literal["passed", "failed", "not_run"] = "not_run"
    warnings: list[str] = Field(default_factory=list)
    elapsed_seconds: float = 0.0
    frame_count: int = 0
    provider_calls: int = 0


class ExtractionResult(BaseModel):
    """The complete outcome of :meth:`suvix.api.Suvix.extract`."""

    model_config = ConfigDict(extra="forbid")

    data: dict[str, Any]
    evidence: list[EvidenceRef] = Field(default_factory=list)
    validation: ValidationReport
    usage: UsageReport
    execution: ExecutionMetadata
