"""Opt-in integration tests for the Gemini adapter (real API calls).

Skipped by default. Run with::

    SUVIX_RUN_INTEGRATION_TESTS=1 GEMINI_API_KEY=... \\
        uv run pytest tests/integration/test_gemini.py -v

Uses a tiny (<2s) ffmpeg-generated video to keep cost minimal. The adapter
deletes the uploaded provider file in a finally block after the run.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from suvix.adapters.base import AdapterRequest
from suvix.adapters.gemini import GeminiExtractor
from suvix.options import ExtractionOptions

RUN = os.environ.get("SUVIX_RUN_INTEGRATION_TESTS") == "1"
HAS_KEY = bool(os.environ.get("GEMINI_API_KEY"))

pytestmark = pytest.mark.skipif(
    not (RUN and HAS_KEY),
    reason="integration tests need SUVIX_RUN_INTEGRATION_TESTS=1 and GEMINI_API_KEY",
)


def _make_tiny_video(path: str) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1.5:size=160x120:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "timestamp_seconds": {"type": "number", "minimum": 0},
                    "description": {"type": "string"},
                },
                "required": ["timestamp_seconds", "description"],
            },
        }
    },
    "required": ["events"],
}


async def test_native_video_extraction_end_to_end(tmp_path):
    video = tmp_path / "tiny.mp4"
    _make_tiny_video(str(video))

    extractor = GeminiExtractor()  # reads GEMINI_API_KEY from the environment
    request = AdapterRequest(
        video_path=str(video),
        schema=SCHEMA,
        instructions=(
            "This is a synthetic test pattern video. List one event per second "
            "of video with its timestamp in seconds and a short description."
        ),
        options=ExtractionOptions(per_call_timeout_seconds=600.0),
        strategy="native_video",
    )
    result = await extractor.extract(request)

    print(f"\nmodel={extractor.name} usage={result.usage} warnings={result.warnings}")
    assert isinstance(result.data, dict), f"expected parsed data, raw_text={result.raw_text!r}"
    assert "events" in result.data
    assert isinstance(result.usage.get("total_tokens"), int)
    assert all(e.ref_type == "provider_reported" for e in result.evidence)
