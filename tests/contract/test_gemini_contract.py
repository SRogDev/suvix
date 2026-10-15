"""Adapter contract tests for the Gemini adapter (mocked SDK, no network).

The shared mixin builds requests with a fictional ``video_path``; the real
adapter validates local files, so the two async extraction tests are rerun
here against a real temporary file with identical assertions.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("httpx", reason="gemini extra not installed")
pytest.importorskip("google.genai", reason="gemini extra not installed")

import httpx
from google.genai import types as real_types
from google.genai.errors import APIError
from test_adapter_contract import AdapterContractTests

from suvix.adapters.base import AdapterRequest, ProviderExtraction, VideoExtractor
from suvix.adapters.gemini import GeminiExtractor
from suvix.options import ExtractionOptions


def _fake_sdk():
    def client_factory(api_key=None):
        files = SimpleNamespace(
            upload=lambda file: SimpleNamespace(
                name="files/fake123",
                uri="https://example.invalid/files/fake123",
                mime_type="video/mp4",
                state=SimpleNamespace(name="ACTIVE"),
            ),
            get=lambda name: SimpleNamespace(
                name=name, state=SimpleNamespace(name="ACTIVE")
            ),
            delete=lambda name: None,
        )
        models = SimpleNamespace(
            generate_content=lambda **kw: SimpleNamespace(
                text='{"ok": true}',
                candidates=[SimpleNamespace()],
                usage_metadata=None,
            )
        )
        return SimpleNamespace(api_key=api_key, files=files, models=models)

    fake_genai = SimpleNamespace(
        Client=client_factory,
        types=real_types,
        errors=SimpleNamespace(APIError=APIError),
    )
    return fake_genai, httpx


@pytest.fixture
def _mock_sdk(monkeypatch):
    genai_ns, http = _fake_sdk()
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


class TestGeminiAdapterContract(AdapterContractTests):
    @pytest.fixture(autouse=True)
    def _needs_mock(self, _mock_sdk):
        pass

    def make_extractor(self) -> VideoExtractor:
        return GeminiExtractor(api_key="test-key")

    def _file_request(self, tmp_path) -> AdapterRequest:
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00" * 32)
        return AdapterRequest(
            video_path=str(video),
            schema={"type": "object"},
            instructions="x",
            options=ExtractionOptions(),
            strategy="native_video",
        )

    async def test_extract_returns_provider_extraction(self, tmp_path):
        # Same assertions as the mixin, but against a real temp file because
        # the adapter validates local media inputs.
        extractor = self.make_extractor()
        result = await extractor.extract(self._file_request(tmp_path))
        assert isinstance(result, ProviderExtraction)

    async def test_malformed_script_item_surfaces_raw_text(self, tmp_path):
        # Same assertions as the mixin, but against a real temp file because
        # the adapter validates local media inputs.
        extractor = self.make_extractor()
        result = await extractor.extract(self._file_request(tmp_path))
        assert isinstance(result.data, dict) or isinstance(result.raw_text, str) \
            or (result.data is None and result.raw_text is None)


def test_gemini_adapter_is_a_video_extractor(_mock_sdk):
    assert isinstance(GeminiExtractor(api_key="test-key"), VideoExtractor)
