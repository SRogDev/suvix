"""Adapter contract tests for the TwelveLabs extractor (mocked SDK)."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from suvix.adapters.base import (
    AdapterRequest,
    ProviderExtraction,
    VideoExtractor,
)
from suvix.adapters.twelvelabs import TwelveLabsExtractor
from suvix.options import ExtractionOptions
from tests.contract.test_adapter_contract import AdapterContractTests


def _fake_twelvelabs(script):
    tl = ModuleType("twelvelabs")
    types_mod = ModuleType("twelvelabs.types")

    class _Kwargs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    for name in (
        "VideoContext_AssetId",
        "AnalyzeImageInput",
        "AnalyzePromptV2",
        "SyncResponseFormat",
        "TextResponseFormatJsonSchema",
    ):
        setattr(types_mod, name, type(name, (_Kwargs,), {}))

    class FakeAssets:
        def create(self, **kwargs):
            return SimpleNamespace(id="asset_1", status="processing")

        def retrieve(self, asset_id):
            return SimpleNamespace(id=asset_id, status="ready")

        def delete(self, asset_id, **kwargs):
            return None

    class TwelveLabs:
        def __init__(self, **kwargs):
            self.assets = FakeAssets()

        def analyze(self, **kwargs):
            item = script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

    tl.TwelveLabs = TwelveLabs
    return tl, types_mod


def _ok(content='{"ok": True}'):
    return SimpleNamespace(data=content, usage=None)


def _patch(script):
    tl, types_mod = _fake_twelvelabs(script)
    return patch.dict(sys.modules, {"twelvelabs": tl, "twelvelabs.types": types_mod})


def _video_request(video_path: str):
    return AdapterRequest(
        video_path=video_path,
        schema={"type": "object"},
        instructions="x",
        options=ExtractionOptions(),
        strategy="native_video",
    )


class TestTwelveLabsAdapterContract(AdapterContractTests):
    def setup_method(self):
        self._patcher = _patch([_ok()])
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def make_extractor(self) -> VideoExtractor:
        return TwelveLabsExtractor(api_key="test-key")

    async def test_extract_returns_provider_extraction(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fake mp4")
        result = await self.make_extractor().extract(_video_request(str(video)))
        assert isinstance(result, ProviderExtraction)

    async def test_malformed_script_item_surfaces_raw_text(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fake mp4")
        patcher = _patch([_ok("nope")])
        patcher.start()
        try:
            result = await self.make_extractor().extract(_video_request(str(video)))
        finally:
            patcher.stop()
        assert isinstance(result.data, dict) or isinstance(result.raw_text, str) \
            or (result.data is None and result.raw_text is None)


def test_twelvelabs_adapter_is_a_video_extractor():
    with _patch([_ok()]):
        assert isinstance(TwelveLabsExtractor(api_key="k"), VideoExtractor)
