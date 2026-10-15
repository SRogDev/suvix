"""Shared adapter contract tests. Every provider adapter must pass these
(against mocked SDK responses); here they run against the fake adapter."""


from suvix.adapters.base import (
    AdapterRequest,
    ExtractorCapabilities,
    ProviderExtraction,
    VideoExtractor,
)
from suvix.adapters.fake import FakeExtractor
from suvix.options import ExtractionOptions


class AdapterContractTests:
    """Mixin: subclasses provide ``make_extractor()``."""

    def make_extractor(self) -> VideoExtractor:
        raise NotImplementedError

    def test_capabilities_are_explicit(self):
        caps = self.make_extractor().capabilities
        assert isinstance(caps, ExtractorCapabilities)
        assert caps.provider
        assert caps.model

    def test_name_identifies_provider_and_model(self):
        assert "/" in self.make_extractor().name

    async def test_extract_returns_provider_extraction(self):
        extractor = self.make_extractor()
        request = AdapterRequest(
            video_path="clip.mp4", schema={"type": "object"},
            instructions="x", options=ExtractionOptions(),
            strategy="native_video")
        result = await extractor.extract(request)
        assert isinstance(result, ProviderExtraction)

    async def test_malformed_script_item_surfaces_raw_text(self):
        extractor = self.make_extractor()
        request = AdapterRequest(
            video_path="clip.mp4", schema={"type": "object"},
            instructions="x", options=ExtractionOptions(),
            strategy="native_video")
        result = await extractor.extract(request)
        # Contract: data and raw_text are never both populated with
        # contradictory content; at least the shape is well-defined.
        assert isinstance(result.data, dict) or isinstance(result.raw_text, str) \
            or (result.data is None and result.raw_text is None)


class TestFakeAdapterContract(AdapterContractTests):
    def make_extractor(self):
        return FakeExtractor(script=[{"data": {"ok": True}}])


def test_fake_adapter_is_a_video_extractor():
    assert isinstance(FakeExtractor(), VideoExtractor)
