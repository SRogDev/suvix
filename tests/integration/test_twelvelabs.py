"""Opt-in live integration test for the TwelveLabs adapter.

Runs ONLY when ``SUVIX_RUN_INTEGRATION_TESTS=1`` **and**
``TWELVELABS_API_KEY`` is set. Makes real, billable API calls against
https://api.twelvelabs.io/v1.3 — never run in CI.

Tiny fixture: a minimal MP4 (a few black frames). The adapter uploads it,
analyzes it, and deletes the asset in a ``finally`` block. The model below
is the documented default; override with ``SUVIX_TWELVELABS_MODEL``.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from suvix.adapters.base import AdapterRequest
from suvix.adapters.twelvelabs import TwelveLabsExtractor
from suvix.options import ExtractionOptions

RUN = os.environ.get("SUVIX_RUN_INTEGRATION_TESTS") == "1"
MODEL = os.environ.get("SUVIX_TWELVELABS_MODEL", "pegasus1.5")

pytestmark = pytest.mark.skipif(
    not RUN, reason="integration tests are opt-in (SUVIX_RUN_INTEGRATION_TESTS=1)"
)


def _require_key() -> str:
    key = os.environ.get("TWELVELABS_API_KEY")
    if not key:
        pytest.fail(
            "SUVIX_RUN_INTEGRATION_TESTS=1 is set but TWELVELABS_API_KEY is missing; "
            "refusing to run a live test without credentials."
        )
    return key


def _tiny_mp4(path: str) -> None:
    """Render a 2-second black MP4 with ffmpeg (skipped if ffmpeg is absent)."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available to build the fixture video")
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2:r=5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", path,
        ],
        check=True,
        timeout=60,
    )


@pytest.mark.asyncio
async def test_live_native_video_extraction(tmp_path):
    key = _require_key()
    video = tmp_path / "tiny.mp4"
    _tiny_mp4(str(video))

    extractor = TwelveLabsExtractor(model=MODEL, api_key=key)
    request = AdapterRequest(
        video_path=str(video),
        schema={
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
        instructions="Describe what is visible in this video.",
        options=ExtractionOptions(per_call_timeout_seconds=300.0),
        strategy="native_video",
    )
    result = await extractor.extract(request)
    assert result.data is not None, f"no data; raw_text={result.raw_text!r}"
    assert "description" in result.data
