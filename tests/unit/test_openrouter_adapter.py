"""Unit tests for the OpenRouter adapter (mocked ``openai`` SDK, no network)."""

from __future__ import annotations

import base64
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
from suvix.adapters.openrouter import OpenRouterExtractor
from suvix.errors import (
    InvalidInputError,
    ProviderConfigError,
    ProviderRequestError,
    ProviderTimeoutError,
    RateLimitError,
    UnsupportedSchemaError,
    UnsupportedStrategyError,
)
from suvix.options import ExtractionOptions

# ---------------------------------------------------------------------------
# Fake ``openai`` SDK
# ---------------------------------------------------------------------------

def make_openai_module(script: list):
    """Build a fake ``openai`` module.

    ``script`` is a list of outcomes for ``chat.completions.create``:
    a response object to return, or an exception instance to raise.
    """
    mod = ModuleType("openai")

    class OpenAIError(Exception):
        pass

    class APIStatusError(OpenAIError):
        def __init__(self, message="", *, status_code=None):
            super().__init__(message)
            self.status_code = status_code

    class RateLimitError(APIStatusError):
        pass

    class APITimeoutError(OpenAIError):
        pass

    class APIConnectionError(OpenAIError):
        pass

    class FakeCompletions:
        def __init__(self):
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            item = script.pop(0) if script else None
            if item is None:
                raise AssertionError("fake openai client ran out of scripted responses")
            if isinstance(item, BaseException):
                raise item
            return item

    created_clients: list[dict] = []

    class OpenAI:
        def __init__(self, **kwargs):
            created_clients.append(kwargs)
            self.kwargs = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    mod.OpenAI = OpenAI
    mod.OpenAIError = OpenAIError
    mod.APIStatusError = APIStatusError
    mod.RateLimitError = RateLimitError
    mod.APITimeoutError = APITimeoutError
    mod.APIConnectionError = APIConnectionError
    mod._created_clients = created_clients
    return mod


def ok_response(content: str = '{"ok": True}', **usage_overrides):
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    usage.update(usage_overrides)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(**usage),
    )


def _patch_openai(monkeypatch, script):
    mod = make_openai_module(script)
    monkeypatch.setitem(sys.modules, "openai", mod)
    return mod


def _request(**overrides):
    base = {
        "video_path": None,
        "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        "instructions": "Extract the data.",
        "options": ExtractionOptions(),
        "frames": [
            FrameInput(
                frame_id="f0",
                timestamp_seconds=1.5,
                image_bytes=b"\x89PNG_fake_bytes",
                mime_type="image/png",
            )
        ],
        "strategy": "selected_frames",
    }
    base.update(overrides)
    return AdapterRequest(**base)


# ---------------------------------------------------------------------------
# Configuration errors
# ---------------------------------------------------------------------------

def test_missing_api_key_raises_config_error(monkeypatch):
    # Patch the SDK first: the adapter checks the SDK before the key, and the
    # default suite must pass without the optional 'openai' package installed.
    _patch_openai(monkeypatch, [ok_response()])
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ProviderConfigError, match="OPENROUTER_API_KEY"):
        OpenRouterExtractor(model="openai/gpt-4o-mini")


def test_api_key_from_env(monkeypatch):
    mod = _patch_openai(monkeypatch, [ok_response()])
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key-123")
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini")
    assert ex._client.kwargs["api_key"] == "env-key-123"
    assert mod._created_clients[0]["api_key"] == "env-key-123"


def test_explicit_key_wins_over_env(monkeypatch):
    _patch_openai(monkeypatch, [ok_response()])
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key-123")
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="arg-key")
    assert ex._client.kwargs["api_key"] == "arg-key"


def test_missing_sdk_raises_config_error(monkeypatch):
    import importlib

    real_import_module = importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("No module named 'openai'")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    with pytest.raises(ProviderConfigError, match=r"pip install suvix\[openrouter\]"):
        OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")


def test_custom_base_url(monkeypatch):
    _patch_openai(monkeypatch, [ok_response()])
    ex = OpenRouterExtractor(
        model="openai/gpt-4o-mini", api_key="k", base_url="https://proxy.local/v1"
    )
    assert ex._client.kwargs["base_url"] == "https://proxy.local/v1"


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

def test_capabilities_are_honest(monkeypatch):
    _patch_openai(monkeypatch, [ok_response()])
    caps = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k").capabilities
    assert isinstance(caps, ExtractorCapabilities)
    assert caps.provider == "openrouter"
    assert caps.model == "openai/gpt-4o-mini"
    assert caps.native_video is False
    assert caps.image_input is True
    assert caps.multi_image is True
    assert caps.structured_output is True
    assert caps.usage_metadata is True
    assert caps.notes  # uncertainty documented


def test_name_identifies_provider_and_model(monkeypatch):
    _patch_openai(monkeypatch, [ok_response()])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    assert ex.name == "openrouter/openai/gpt-4o-mini"
    assert isinstance(ex, VideoExtractor)


# ---------------------------------------------------------------------------
# Strategy handling
# ---------------------------------------------------------------------------

def test_native_video_strategy_rejected(monkeypatch):
    _patch_openai(monkeypatch, [ok_response()])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    req = _request(strategy="native_video", video_path="clip.mp4", frames=None)
    with pytest.raises(UnsupportedStrategyError, match="selected_frames"):
        import asyncio
        asyncio.run(ex.extract(req))


def test_unknown_strategy_rejected(monkeypatch):
    _patch_openai(monkeypatch, [ok_response()])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    req = _request(strategy="auto")
    with pytest.raises(UnsupportedStrategyError):
        import asyncio
        asyncio.run(ex.extract(req))


def test_selected_frames_without_frames_rejected(monkeypatch):
    _patch_openai(monkeypatch, [ok_response()])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    req = _request(frames=None)
    with pytest.raises(InvalidInputError, match="frames"):
        import asyncio
        asyncio.run(ex.extract(req))


# ---------------------------------------------------------------------------
# Schema compatibility
# ---------------------------------------------------------------------------

def test_non_object_root_schema_rejected(monkeypatch):
    _patch_openai(monkeypatch, [ok_response()])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    req = _request(schema={"type": "array", "items": {"type": "string"}})
    with pytest.raises(UnsupportedSchemaError, match="object"):
        import asyncio
        asyncio.run(ex.extract(req))


def test_invalid_json_schema_rejected(monkeypatch):
    _patch_openai(monkeypatch, [ok_response()])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    req = _request(schema={"type": "not-a-real-type"})
    with pytest.raises(UnsupportedSchemaError):
        import asyncio
        asyncio.run(ex.extract(req))


# ---------------------------------------------------------------------------
# Successful extraction
# ---------------------------------------------------------------------------

def test_extract_builds_expected_request(monkeypatch):
    _patch_openai(monkeypatch, [ok_response('{"ok": true}')])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    result = _run(ex, _request())

    assert isinstance(result, ProviderExtraction)
    assert result.data == {"ok": True}

    calls = ex._client.chat.completions.calls
    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["model"] == "openai/gpt-4o-mini"

    # response_format: strict json_schema with the caller's schema.
    rf = kwargs["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
    }

    # require_parameters forces routing to endpoints that support it.
    assert kwargs["extra_body"] == {"provider": {"require_parameters": True}}

    # Message: text part first, then base64 data-URI image parts.
    messages = kwargs["messages"]
    assert len(messages) == 1
    content = messages[0]["content"]
    assert content[0]["type"] == "text"
    assert "Extract the data." in content[0]["text"]
    assert content[1]["type"] == "image_url"
    expected_uri = "data:image/png;base64," + base64.b64encode(b"\x89PNG_fake_bytes").decode()
    assert content[1]["image_url"]["url"] == expected_uri


def test_extract_maps_usage(monkeypatch):
    _patch_openai(monkeypatch, [ok_response('{"ok": true}',
                                           prompt_tokens=11, completion_tokens=6, total_tokens=17)])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    result = _run(ex, _request())
    assert result.usage["prompt_tokens"] == 11
    assert result.usage["completion_tokens"] == 6
    assert result.usage["total_tokens"] == 17


def test_extract_emits_frame_evidence(monkeypatch):
    _patch_openai(monkeypatch, [ok_response('{"ok": true}')])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    result = _run(ex, _request())
    assert len(result.evidence) == 1
    ref = result.evidence[0]
    assert ref.ref_type == "frame"
    assert ref.frame_id == "f0"
    assert ref.timestamp_seconds == 1.5


def test_malformed_content_surfaces_raw_text(monkeypatch):
    _patch_openai(monkeypatch, [ok_response("definitely not json")])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    result = _run(ex, _request())
    assert result.data is None
    assert result.raw_text == "definitely not json"
    assert result.warnings  # the failure is disclosed, not silent


def test_empty_content_surfaces_raw_text(monkeypatch):
    _patch_openai(monkeypatch, [ok_response("")])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    result = _run(ex, _request())
    assert result.data is None
    assert isinstance(result.raw_text, str)


def _run(ex, req):
    import asyncio
    return asyncio.run(ex.extract(req))


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

def _error_case(monkeypatch, exc):
    _patch_openai(monkeypatch, [exc])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    return ex


def test_rate_limit_error_mapping(monkeypatch):
    script = []
    mod = _patch_openai(monkeypatch, script)
    script.append(mod.RateLimitError("slow down", status_code=429))
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    with pytest.raises(RateLimitError):
        _run(ex, _request())


def test_status_429_maps_to_rate_limit(monkeypatch):
    script = []
    mod = _patch_openai(monkeypatch, script)
    script.append(mod.APIStatusError("limited", status_code=429))
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    with pytest.raises(RateLimitError):
        _run(ex, _request())


def test_timeout_maps_to_provider_timeout(monkeypatch):
    script = []
    mod = _patch_openai(monkeypatch, script)
    script.append(mod.APITimeoutError("timed out"))
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    with pytest.raises(ProviderTimeoutError):
        _run(ex, _request())


def test_connection_error_maps_to_provider_request_error(monkeypatch):
    script = []
    mod = _patch_openai(monkeypatch, script)
    script.append(mod.APIConnectionError("boom"))
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    with pytest.raises(ProviderRequestError):
        _run(ex, _request())


def test_server_error_maps_to_provider_request_error(monkeypatch):
    script = []
    mod = _patch_openai(monkeypatch, script)
    script.append(mod.APIStatusError("bad gateway", status_code=502))
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    with pytest.raises(ProviderRequestError):
        _run(ex, _request())


def test_error_messages_never_contain_the_key(monkeypatch):
    mod = make_openai_module([])
    secret = "sk-or-v1-supersecretkey"
    _patch_openai(monkeypatch, [mod.APIConnectionError(f"failed with key {secret}")])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key=secret)
    with pytest.raises(ProviderRequestError) as exc_info:
        _run(ex, _request())
    assert secret not in str(exc_info.value)
    for value in exc_info.value.details.values():
        assert secret not in str(value)


def test_unexpected_exception_maps_to_provider_request_error(monkeypatch):
    _patch_openai(monkeypatch, [RuntimeError("weird")])
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini", api_key="k")
    with pytest.raises(ProviderRequestError):
        _run(ex, _request())
