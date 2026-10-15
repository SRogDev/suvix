"""Adapter contract: the boundary between the provider-neutral core and
provider-specific SDKs. The core only ever talks to :class:`VideoExtractor`.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from suvix.contracts import EvidenceRef
from suvix.options import ExtractionOptions


class ExtractorCapabilities(BaseModel):
    """Factual, testable description of what an adapter supports.

    Capabilities must reflect the verified provider behavior (see
    ``docs/providers/<provider>.md``), never aspirations. If a provider does
    not expose internal sampling details, ``exposes_sampled_frames`` stays
    False and Suvix will not claim to know which frames were inspected.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    native_video: bool = False
    image_input: bool = False
    multi_image: bool = False
    structured_output: bool = False
    json_schema_notes: str = ""
    provider_upload: bool = False
    file_reference: bool = False
    max_duration_seconds: float | None = None
    max_file_bytes: int | None = None
    usage_metadata: bool = False
    timestamp_support: bool = False
    exposes_sampled_frames: bool = False
    notes: str = ""


class FrameInput(BaseModel):
    """One locally-extracted frame handed to an adapter (selected-frame mode)."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    frame_id: str
    timestamp_seconds: float
    image_bytes: bytes
    mime_type: str = "image/jpeg"


class AdapterRequest(BaseModel):
    """Everything an adapter needs for one provider call. Built by the core;
    the adapter must not silently change schema, strategy, or model."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    video_path: str | None = None
    json_schema: dict[str, Any] = Field(alias="schema")
    instructions: str
    options: ExtractionOptions
    frames: list[FrameInput] | None = None
    strategy: str


class ProviderExtraction(BaseModel):
    """Raw outcome of one adapter call, before core validation."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    data: dict[str, Any] | None = None
    raw_text: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


@runtime_checkable
class VideoExtractor(Protocol):
    """The interface every provider adapter implements."""

    @property
    def name(self) -> str:
        """Human identifier, e.g. ``"gemini/gemini-2.5-flash"``."""
        ...

    @property
    def capabilities(self) -> ExtractorCapabilities:
        ...

    async def extract(self, request: AdapterRequest) -> ProviderExtraction:
        """Perform one structured extraction call and return the raw outcome."""
        ...
