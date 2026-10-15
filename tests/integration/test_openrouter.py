"""Opt-in live integration test for the OpenRouter adapter.

Runs ONLY when ``SUVIX_RUN_INTEGRATION_TESTS=1`` **and**
``OPENROUTER_API_KEY`` is set. Makes real, billable API calls against
https://openrouter.ai/api/v1 — never run in CI.

Tiny fixture: a 1x1 PNG frame and a minimal schema. The model slug below
is a documented default; override with ``SUVIX_OPENROUTER_MODEL``.
"""

from __future__ import annotations

import base64
import os

import pytest

from suvix.adapters.base import AdapterRequest, FrameInput
from suvix.adapters.openrouter import OpenRouterExtractor
from suvix.options import ExtractionOptions

RUN = os.environ.get("SUVIX_RUN_INTEGRATION_TESTS") == "1"
MODEL = os.environ.get("SUVIX_OPENROUTER_MODEL", "openai/gpt-4o-mini")

pytestmark = pytest.mark.skipif(
    not RUN, reason="integration tests are opt-in (SUVIX_RUN_INTEGRATION_TESTS=1)"
)

# 1x1 transparent PNG — the smallest valid image fixture.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _require_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        pytest.fail(
            "SUVIX_RUN_INTEGRATION_TESTS=1 is set but OPENROUTER_API_KEY is missing; "
            "refusing to run a live test without credentials."
        )
    return key


@pytest.mark.asyncio
async def test_live_selected_frames_extraction():
    key = _require_key()
    extractor = OpenRouterExtractor(model=MODEL, api_key=key)
    request = AdapterRequest(
        video_path=None,
        schema={
            "type": "object",
            "properties": {"dominant_color": {"type": "string"}},
            "required": ["dominant_color"],
        },
        instructions="Name the dominant color of this image.",
        options=ExtractionOptions(per_call_timeout_seconds=120.0),
        frames=[
            FrameInput(
                frame_id="f0",
                timestamp_seconds=0.0,
                image_bytes=_TINY_PNG,
                mime_type="image/png",
            )
        ],
        strategy="selected_frames",
    )
    result = await extractor.extract(request)
    assert result.data is not None, f"no data; raw_text={result.raw_text!r}"
    assert "dominant_color" in result.data
    assert result.usage.get("prompt_tokens", 0) > 0
