"""Unit tests for the TwelveLabs adapter (mocked ``twelvelabs`` SDK, no network)."""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from suvix.adapters.base import (
    AdapterRequest,
    ExtractorCapabilities,
    FrameInput,
    ProviderExtraction,
    VideoExtractor,
)
from suvix.adapters.twelvelabs import TwelveLabsExtractor
from suvix.errors import (
    InvalidInputError,
    ProviderConfigError,
    ProviderRequestError,
    ProviderTimeoutError,
    RateLimitError,
    UnsupportedMediaError,
    UnsupportedStrategyError,
)
from suvix.options import ExtractionOptions

# ---------------------------------------------------------------------------
# Fake ``twelvelabs`` SDK
# ---------------------------------------------------------------------------

def make_twelvelabs_modules(*, asset_status: str = "ready", analyze_script=None):
    """Build fake ``twelvelabs`` and ``twelvelabs.types`` modules."""
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

    script = list(analyze_script or [])

    class FakeAssets:
        def __init__(self):
            self.created: list[dict] = []
            self.deleted: list[str] = []
            self.retrieved: list[str] = []

        def create(self, **kwargs):
            self.created.append(kwargs)
            asset_id = f"asset_{len(self.created)}"
            return SimpleNamespace(id=asset_id, status="processing")

        def retrieve(self, asset_id):
            self.retrieved.append(asset_id)
            return SimpleNamespace(id=asset_id, status=asset_status)

        def delete(self, asset_id, **kwargs):
            self.deleted.append(asset_id)
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.assets = FakeAssets()
            self.analyze_calls: list[dict] = []

        def analyze(self, **kwargs):
            self.analyze_calls.append(kwargs)
            item = script.pop(0) if script else None
            if item is None:
                raise AssertionError("fake twelvelabs client ran out of scripted responses")
            if isinstance(item, BaseException):
                raise item
            return item

    tl.TwelveLabs = FakeClient
    return tl, types_mod


def _patch_twelvelabs(monkeypatch, **kwargs):
    tl, types_mod = make_twelvelabs_modules(**kwargs)
    monkeypatch.setitem(sys.modules, "twelvelabs", tl)
    monkeypatch.setitem(sys.modules, "twelvelabs.types", types_mod)
    return tl


def ok_analyze(data: str = '{"summary": "a cat"}', **usage):
    return SimpleNamespace(
        data=data,
        usage=SimpleNamespace(**usage) if usage else None,
    )


def _video_request(tmp_path, **overrides):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00\x00\x00 fake mp4 bytes")
    base = {
        "video_path": str(video),
        "schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
        "instructions": "Summarize the video.",
        "options": ExtractionOptions(),
        "strategy": "native_video",
    }
    base.update(overrides)
    return AdapterRequest(**base)


def _run(ex, req):
    return asyncio.run(ex.extract(req))


# ---------------------------------------------------------------------------
# Configuration errors
# ---------------------------------------------------------------------------

def test_missing_api_key_raises_config_error(monkeypatch):
    # Patch the SDK first: the adapter checks the SDK before the key, and the
    # default suite must pass without the optional 'twelvelabs' package.
    _patch_twelvelabs(monkeypatch)
    monkeypatch.delenv("TWELVELABS_API_KEY", raising=False)
    with pytest.raises(ProviderConfigError, match="TWELVELABS_API_KEY"):
        TwelveLabsExtractor()


def test_api_key_from_env(monkeypatch, tmp_path):
    tl = _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze()])
    monkeypatch.setenv("TWELVELABS_API_KEY", "tlk_env_key")
    ex = TwelveLabsExtractor()
    assert ex._client.kwargs["api_key"] == "tlk_env_key"
    assert tl.TwelveLabs is not None


def test_missing_sdk_raises_config_error(monkeypatch):
    import importlib

    real_import_module = importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == "twelvelabs" or name.startswith("twelvelabs."):
            raise ImportError(f"No module named '{name}'")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.delenv("TWELVELABS_API_KEY", raising=False)
    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    for mod_name in ("twelvelabs", "twelvelabs.types"):
        monkeypatch.delitem(sys.modules, mod_name, raising=False)
    with pytest.raises(ProviderConfigError, match=r"pip install suvix\[twelvelabs\]"):
        TwelveLabsExtractor(api_key="k")


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

def test_capabilities_reflect_verified_workflow(monkeypatch):
    _patch_twelvelabs(monkeypatch)
    caps = TwelveLabsExtractor(api_key="k").capabilities
    assert isinstance(caps, ExtractorCapabilities)
    assert caps.provider == "twelvelabs"
    assert caps.native_video is True
    assert caps.image_input is True
    assert caps.multi_image is True
    assert caps.structured_output is True  # verified json_schema response_format
    assert caps.usage_metadata is True
    assert caps.timestamp_support is True
    assert caps.exposes_sampled_frames is False
    assert caps.provider_upload is True
    assert caps.file_reference is True
    assert caps.max_duration_seconds == 3600
    assert caps.notes


def test_name_identifies_provider(monkeypatch):
    _patch_twelvelabs(monkeypatch)
    ex = TwelveLabsExtractor(api_key="k")
    assert ex.name.startswith("twelvelabs/")
    assert isinstance(ex, VideoExtractor)


# ---------------------------------------------------------------------------
# native_video strategy
# ---------------------------------------------------------------------------

def test_native_video_uploads_and_analyzes(monkeypatch, tmp_path):
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze()])
    ex = TwelveLabsExtractor(api_key="k")
    result = _run(ex, _video_request(tmp_path))

    assert isinstance(result, ProviderExtraction)
    assert result.data == {"summary": "a cat"}

    client = ex._client
    # One direct-upload asset created from the local file bytes.
    assert len(client.assets.created) == 1
    assert client.assets.created[0]["method"] == "direct"

    # Analysis ran against the asset with structured output requested.
    assert len(client.analyze_calls) == 1
    call = client.analyze_calls[0]
    assert call["model_name"] == "pegasus1.5"  # documented default
    assert call["video"].asset_id == "asset_1"
    assert call["response_format"].type == "json_schema"
    assert call["response_format"].json_schema.strict is True

    # The uploaded asset is deleted afterwards (cleanup in finally).
    assert client.assets.deleted == ["asset_1"]


def test_explicit_model_is_used(monkeypatch, tmp_path):
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze()])
    ex = TwelveLabsExtractor(model="pegasus1.6", api_key="k")
    _run(ex, _video_request(tmp_path))
    assert ex._client.analyze_calls[0]["model_name"] == "pegasus1.6"


def test_url_video_uses_url_upload(monkeypatch, tmp_path):
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze()])
    ex = TwelveLabsExtractor(api_key="k")
    req = _video_request(tmp_path, video_path="https://example.com/clip.mp4")
    _run(ex, req)
    assert ex._client.assets.created[0]["method"] == "url"
    assert ex._client.assets.created[0]["url"] == "https://example.com/clip.mp4"
    assert ex._client.assets.deleted == ["asset_1"]


def test_asset_deleted_even_when_analysis_fails(monkeypatch, tmp_path):
    class Boom(Exception):
        status_code = 500

    _patch_twelvelabs(monkeypatch, analyze_script=[Boom("provider blew up")])
    ex = TwelveLabsExtractor(api_key="k")
    with pytest.raises(ProviderRequestError):
        _run(ex, _video_request(tmp_path))
    # Cleanup still ran.
    assert ex._client.assets.deleted == ["asset_1"]


def test_failed_asset_processing_raises(monkeypatch, tmp_path):
    _patch_twelvelabs(monkeypatch, asset_status="failed", analyze_script=[ok_analyze()])
    ex = TwelveLabsExtractor(api_key="k")
    with pytest.raises(ProviderRequestError, match="failed"):
        _run(ex, _video_request(tmp_path))


def test_missing_video_file_raises(monkeypatch, tmp_path):
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze()])
    ex = TwelveLabsExtractor(api_key="k")
    req = _video_request(tmp_path, video_path=str(tmp_path / "nope.mp4"))
    with pytest.raises(UnsupportedMediaError, match="read"):
        _run(ex, req)


def test_native_video_without_video_path_rejected(monkeypatch):
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze()])
    ex = TwelveLabsExtractor(api_key="k")
    req = AdapterRequest(
        video_path=None,
        schema={"type": "object"},
        instructions="x",
        options=ExtractionOptions(),
        strategy="native_video",
    )
    with pytest.raises(InvalidInputError, match="video_path"):
        _run(ex, req)


# ---------------------------------------------------------------------------
# selected_frames strategy (verified: 1-20 images, Pegasus 1.6)
# ---------------------------------------------------------------------------

def _frames_request(**overrides):
    frames = [
        FrameInput(frame_id="f0", timestamp_seconds=0.0, image_bytes=b"img0"),
        FrameInput(frame_id="f1", timestamp_seconds=2.0, image_bytes=b"img1"),
    ]
    base = {
        "video_path": None,
        "schema": {"type": "object"},
        "instructions": "Describe.",
        "options": ExtractionOptions(),
        "frames": frames,
        "strategy": "selected_frames",
    }
    base.update(overrides)
    return AdapterRequest(**base)


def test_selected_frames_uploads_images_and_analyzes(monkeypatch):
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze('{"ok": true}')])
    ex = TwelveLabsExtractor(api_key="k")
    result = _run(ex, _frames_request())

    assert result.data == {"ok": True}
    client = ex._client
    # Each frame became its own image asset.
    assert len(client.assets.created) == 2
    call = client.analyze_calls[0]
    assert call["model_name"] == "pegasus1.6"  # images require Pegasus 1.6
    assert len(call["image"]) == 2
    assert call["image"][0].name == "frame_f0"
    # Frame evidence is honest: these exact frames were extracted locally.
    assert [r.ref_type for r in result.evidence] == ["frame", "frame"]
    assert result.evidence[0].frame_id == "f0"
    # Cleanup deleted both image assets.
    assert sorted(client.assets.deleted) == ["asset_1", "asset_2"]


def test_selected_frames_rejects_non_pegasus16_model(monkeypatch):
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze()])
    ex = TwelveLabsExtractor(model="pegasus1.5", api_key="k")
    with pytest.raises(UnsupportedStrategyError, match="pegasus1.6"):
        _run(ex, _frames_request())


def test_selected_frames_rejects_too_many_frames(monkeypatch):
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze()])
    ex = TwelveLabsExtractor(api_key="k")
    frames = [
        FrameInput(frame_id=f"f{i}", timestamp_seconds=float(i), image_bytes=b"x")
        for i in range(21)
    ]
    with pytest.raises(UnsupportedStrategyError, match="20"):
        _run(ex, _frames_request(frames=frames))


def test_selected_frames_without_frames_rejected(monkeypatch):
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze()])
    ex = TwelveLabsExtractor(api_key="k")
    with pytest.raises(InvalidInputError, match="frames"):
        _run(ex, _frames_request(frames=None))


def test_unknown_strategy_rejected(monkeypatch):
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze()])
    ex = TwelveLabsExtractor(api_key="k")
    with pytest.raises(UnsupportedStrategyError):
        _run(ex, _frames_request(strategy="auto"))


# ---------------------------------------------------------------------------
# Parsing, usage, evidence
# ---------------------------------------------------------------------------

def test_malformed_output_surfaces_raw_text(monkeypatch, tmp_path):
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze("not json at all")])
    ex = TwelveLabsExtractor(api_key="k")
    result = _run(ex, _video_request(tmp_path))
    assert result.data is None
    assert result.raw_text == "not json at all"
    assert result.warnings


def test_usage_mapping(monkeypatch, tmp_path):
    _patch_twelvelabs(
        monkeypatch,
        analyze_script=[ok_analyze(input_tokens=120, output_tokens=30)],
    )
    ex = TwelveLabsExtractor(api_key="k")
    result = _run(ex, _video_request(tmp_path))
    assert result.usage == {"input_tokens": 120, "output_tokens": 30}


def test_provider_reported_timestamps_become_evidence(monkeypatch, tmp_path):
    data = '{"events": [{"start_time": 12.5, "end_time": 18.0, "label": "goal"}]}'
    _patch_twelvelabs(monkeypatch, analyze_script=[ok_analyze(data)])
    ex = TwelveLabsExtractor(api_key="k")
    result = _run(ex, _video_request(tmp_path))
    assert result.data["events"][0]["label"] == "goal"
    assert len(result.evidence) == 1
    ref = result.evidence[0]
    assert ref.ref_type == "provider_reported"
    assert ref.start_seconds == 12.5
    assert ref.end_seconds == 18.0


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

def test_rate_limit_error_mapping(monkeypatch, tmp_path):
    class ApiError(Exception):
        def __init__(self):
            self.status_code = 429
            super().__init__("too many requests")

    _patch_twelvelabs(monkeypatch, analyze_script=[ApiError()])
    ex = TwelveLabsExtractor(api_key="k")
    with pytest.raises(RateLimitError):
        _run(ex, _video_request(tmp_path))


def test_timeout_error_mapping(monkeypatch, tmp_path):
    class TimeoutLike(Exception):
        pass

    TimeoutLike.__name__ = "ReadTimeout"
    _patch_twelvelabs(monkeypatch, analyze_script=[TimeoutLike("slow")])
    ex = TwelveLabsExtractor(api_key="k")
    with pytest.raises(ProviderTimeoutError):
        _run(ex, _video_request(tmp_path))


def test_api_error_maps_to_provider_request_error(monkeypatch, tmp_path):
    class ApiError(Exception):
        def __init__(self):
            self.status_code = 500
            super().__init__("internal error")

    _patch_twelvelabs(monkeypatch, analyze_script=[ApiError()])
    ex = TwelveLabsExtractor(api_key="k")
    with pytest.raises(ProviderRequestError):
        _run(ex, _video_request(tmp_path))


def test_error_messages_never_contain_the_key(monkeypatch, tmp_path):
    secret = "tlk_supersecret"

    class ApiError(Exception):
        def __init__(self):
            self.status_code = 500
            super().__init__(f"failed for key {secret}")

    _patch_twelvelabs(monkeypatch, analyze_script=[ApiError()])
    ex = TwelveLabsExtractor(api_key=secret)
    with pytest.raises(ProviderRequestError) as exc_info:
        _run(ex, _video_request(tmp_path))
    assert secret not in str(exc_info.value)
