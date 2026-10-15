"""Basic extraction with Suvix — offline, no API keys.

Runs the full pipeline (strategy selection, validation, usage reporting)
against the FakeExtractor, a deterministic stand-in for a real provider.
Replace it with a real adapter (e.g. suvix.adapters.gemini.GeminiExtractor)
to hit a provider.

Usage:
    uv run python examples/basic_extraction.py [video.mp4]
"""

from __future__ import annotations

import asyncio
import sys

from suvix import ExtractionOptions, Suvix
from suvix.adapters.fake import FakeExtractor

SCHEMA = {
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
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}


async def main(video: str) -> None:
    extractor = FakeExtractor(
        script=[
            {
                "data": {
                    "events": [
                        {"timestamp_seconds": 1.5, "event_type": "goal"},
                    ]
                },
                "evidence": [
                    {
                        "ref_type": "provider_reported",
                        "timestamp_seconds": 1.5,
                        "note": "crowd roars",
                    }
                ],
            }
        ]
    )
    result = await Suvix().extract(
        video=video,
        schema=SCHEMA,
        instructions="Identify each visible event of interest.",
        extractor=extractor,
        options=ExtractionOptions(max_refinement_rounds=0),
    )
    print("strategy:  ", result.execution.strategy)
    print("data:      ", result.data)
    print("valid:     ", result.validation.valid)
    print("evidence:  ", [e.model_dump(exclude_none=True) for e in result.evidence])
    print("usage:     ", result.usage.model_dump(exclude_none=True))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "sample.mp4"))
