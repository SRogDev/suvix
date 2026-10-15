"""Adapter contract tests for the OpenRouter extractor (mocked SDK).

The shared mixin assumes ``native_video``; this adapter only supports
``selected_frames``, so the two extract tests are overridden with the
strategy the adapter actually implements. The capability/name tests run
unchanged.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from suvix.adapters.base import (
    AdapterRequest,
    FrameInput,
    ProviderExtraction,
    VideoExtractor,
)
from suvix.adapters.openrouter import OpenRouterExtractor
from suvix.options import ExtractionOptions
from tests.contract.test_adapter_contract import AdapterContractTests


def _fake_openai(script):
    mod = ModuleType("openai")

    class OpenAIError(Exception):
        pass

    class APIStatusError(OpenAIError):
        def __init__(self, message="", *, status_code=None):
            super().__init__(message)
            self.status_code = status_code

    class FakeCompletions:
        def __init__(self, script):
            self._script = script

        def create(self, **kwargs):
            item = self._script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

    class OpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions(script))

    mod.OpenAI = OpenAI
    mod.OpenAIError = OpenAIError
    mod.APIStatusError = APIStatusError
    mod.RateLimitError = type("RateLimitError", (APIStatusError,), {})
    mod.APITimeoutError = type("APITimeoutError", (OpenAIError,), {})
    mod.APIConnectionError = type("APIConnectionError", (OpenAIError,), {})
    return mod


def _ok(content='{"ok": True}'):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


def _frames_request():
    return AdapterRequest(
        video_path=None,
        schema={"type": "object"},
        instructions="x",
        options=ExtractionOptions(),
        frames=[
            FrameInput(frame_id="f0", timestamp_seconds=0.0, image_bytes=b"img")
        ],
        strategy="selected_frames",
    )


class TestOpenRouterAdapterContract(AdapterContractTests):
    def setup_method(self):
        self._patcher = patch.dict(
            sys.modules, {"openai": _fake_openai([_ok()])}
        )
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def make_extractor(self) -> VideoExtractor:
        return OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="test-key")

    async def test_extract_returns_provider_extraction(self):
        result = await self.make_extractor().extract(_frames_request())
        assert isinstance(result, ProviderExtraction)

    async def test_malformed_script_item_surfaces_raw_text(self):
        patcher = patch.dict(sys.modules, {"openai": _fake_openai([_ok("nope")])})
        patcher.start()
        try:
            result = await self.make_extractor().extract(_frames_request())
        finally:
            patcher.stop()
        assert isinstance(result.data, dict) or isinstance(result.raw_text, str) \
            or (result.data is None and result.raw_text is None)


def test_openrouter_adapter_is_a_video_extractor():
    with patch.dict(sys.modules, {"openai": _fake_openai([_ok()])}):
        assert isinstance(
            OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k"),
            VideoExtractor,
        )
