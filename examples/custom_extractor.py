"""A custom extractor: implement the VideoExtractor protocol yourself.

Any class with ``name``, ``capabilities``, and an async ``extract`` method
satisfies the protocol — no subclassing required. Suvix handles strategy
selection, validation, recovery, and usage aggregation around it.

Usage:
    uv run python examples/custom_extractor.py
"""

from __future__ import annotations

import asyncio

from suvix import Suvix
from suvix.adapters.base import (
    AdapterRequest,
    ExtractorCapabilities,
    ProviderExtraction,
    VideoExtractor,
)
from suvix.contracts import EvidenceRef


class EchoExtractor:
    """A minimal hand-written adapter: echoes one canned event per call."""

    @property
    def name(self) -> str:
        return "echo/custom-1"

    @property
    def capabilities(self) -> ExtractorCapabilities:
        return ExtractorCapabilities(
            provider="echo",
            model="custom-1",
            native_video=True,  # claims the video path; never invent claims
            structured_output=True,
            usage_metadata=False,  # no token counts from this adapter
            notes="Example adapter from examples/custom_extractor.py.",
        )

    async def extract(self, request: AdapterRequest) -> ProviderExtraction:
        assert request.strategy == "native_video", "this example only does native"
        return ProviderExtraction(
            data={"events": [{"timestamp_seconds": 2.0, "event_type": "demo"}]},
            evidence=[
                EvidenceRef(
                    ref_type="provider_reported",
                    timestamp_seconds=2.0,
                    note="reported by the custom adapter",
                )
            ],
            usage={},
        )


assert isinstance(EchoExtractor(), VideoExtractor)  # protocol conformance


async def main() -> None:
    schema = {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "timestamp_seconds": {"type": "number"},
                        "event_type": {"type": "string"},
                    },
                    "required": ["timestamp_seconds", "event_type"],
                },
            }
        },
        "required": ["events"],
    }
    result = await Suvix().extract(
        video="sample.mp4",
        schema=schema,
        instructions="Demo.",
        extractor=EchoExtractor(),
    )
    print("strategy:", result.execution.strategy)
    print("data:    ", result.data)
    print("valid:   ", result.validation.valid)


if __name__ == "__main__":
    asyncio.run(main())
