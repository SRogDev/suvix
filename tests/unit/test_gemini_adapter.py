"""Unit tests for the Gemini adapter.

No network, no API keys: the ``google.genai`` SDK surface is replaced with
in-memory fakes via ``monkeypatch`` on ``suvix.adapters.gemini._load_sdk``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("httpx", reason="gemini extra not installed")
pytest.importorskip("google.genai", reason="gemini extra not installed")

import httpx
from google.genai import types as real_types
from google.genai.errors import APIError

from suvix.adapters.base import AdapterRequest, FrameInput
from suvix.adapters.gemini import GeminiExtractor, to_gemini_schema
from suvix.errors import (
    InvalidInputError,
    ProviderConfigError,
    ProviderRequestError,
    ProviderTimeoutError,
    RateLimitError,
    UnsupportedMediaError,
    UnsupportedSchemaError,
    UnsupportedStrategyError,
)
from suvix.options import ExtractionOptions

# ---------------------------------------------------------------------------
# Fake google.genai SDK surface
# ---------------------------------------------------------------------------


class FakeFiles:
    def __init__(self, states: list[str] | None = None):
        self.states = states or ["ACTIVE"]
        self.uploaded: list[str] = []
        self.deleted: list[str] = []
        self._polls = 0

    def upload(self, file: str):
        self.uploaded.append(file)
        return SimpleNamespace(
            name="files/fake123",
            uri="https://generativelanguage.googleapis.com/v1beta/files/fake123",
            mime_type="video/mp4",
            state=SimpleNamespace(name=self.states[0]),
        )

    def get(self, name: str):
        self._polls += 1
        state = self.states[min(self._polls, len(self.states) - 1)]
        return SimpleNamespace(name=name, state=SimpleNamespace(name=state))

    def delete(self, name: str):
        self.deleted.append(name)
        return None


class FakeModels:
    def __init__(self, response=None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class FakeClient:
    def __init__(self, api_key: str | None = None, files: FakeFiles | None = None,
                 models: FakeModels | None = None):
        self.api_key = api_key
        self.files = files or FakeFiles()
        self.models = models or FakeModels()


def make_response(text: str = '{"ok": true}', usage=None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))],
        usage_metadata=usage,
    )


def fake_sdk(files: FakeFiles | None = None, models: FakeModels | None = None):
    """Return (fake_genai_module, httpx) for monkeypatching _load_sdk."""
    created = []

    def client_factory(api_key: str | None = None):
        client = FakeClient(api_key=api_key, files=files, models=models)
        created.append(client)
        return client

    fake_genai = SimpleNamespace(
        Client=client_factory,
        types=real_types,
        errors=SimpleNamespace(APIError=APIError),
        _created=created,
    )
    return (fake_genai, httpx), created


@pytest.fixture
def sdk(monkeypatch):
    """Default fake SDK: ACTIVE upload, JSON text response."""
    (genai_ns, http), created = fake_sdk(
        models=FakeModels(response=make_response())
    )
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    return created


def make_request(**overrides) -> AdapterRequest:
    base = {
        "video_path": "clip.mp4",
        "schema": {"type": "object"},
        "instructions": "Extract events.",
        "options": ExtractionOptions(),
        "strategy": "native_video",
    }
    base.update(overrides)
    return AdapterRequest(**base)


# ---------------------------------------------------------------------------
# Construction / configuration
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_config_error(sdk, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ProviderConfigError, match="GEMINI_API_KEY"):
        GeminiExtractor(api_key=None)


def test_explicit_api_key_used(sdk, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    created = sdk
    GeminiExtractor(api_key="sk-test-explicit")
    assert created and created[0].api_key == "sk-test-explicit"


def test_env_api_key_used(sdk, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test-env")
    created = sdk
    GeminiExtractor()
    assert created and created[0].api_key == "sk-test-env"


def test_missing_sdk_raises_config_error(monkeypatch):
    def boom():
        raise ProviderConfigError("pip install suvix[gemini] to use the Gemini adapter")
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", boom)
    with pytest.raises(ProviderConfigError, match="suvix\\[gemini\\]"):
        GeminiExtractor(api_key="sk-test")


def test_name_identifies_provider_and_model(sdk):
    ext = GeminiExtractor(api_key="sk-test", model="gemini-3.8-flash")
    assert ext.name == "gemini/gemini-3.8-flash"


def test_capabilities_only_verified_values(sdk):
    caps = GeminiExtractor(api_key="sk-test").capabilities
    assert caps.provider == "gemini"
    assert caps.model == "gemini-3.8-flash"
    assert caps.native_video is True
    assert caps.image_input is True
    assert caps.multi_image is True
    assert caps.structured_output is True
    assert caps.provider_upload is True
    assert caps.file_reference is True
    assert caps.usage_metadata is True
    assert caps.timestamp_support is True
    # The API documents 1 FPS internal sampling but responses never expose
    # sampled frame ids -> Suvix must not claim them.
    assert caps.exposes_sampled_frames is False
    assert "docs/providers/gemini.md" in caps.notes


def test_api_key_never_leaks_into_errors(sdk, monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    secret = "sk-super-secret-key-12345"
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    (genai_ns, http), _ = fake_sdk(
        models=FakeModels(error=APIError(500, {"error": {"message": "boom"}}))
    )
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    ext = GeminiExtractor(api_key=secret)
    with pytest.raises(ProviderRequestError) as excinfo:
        import asyncio
        asyncio.run(ext.extract(make_request(video_path=str(video))))
    assert secret not in str(excinfo.value)
    assert secret not in repr(excinfo.value.details)


# ---------------------------------------------------------------------------
# Schema translation
# ---------------------------------------------------------------------------


def test_valid_subset_passes_through_unchanged():
    schema = {
        "type": "object",
        "title": "Extraction",
        "description": "Events in the video.",
        "properties": {
            "timestamp_seconds": {"type": "number", "minimum": 0.0, "maximum": 3600.0},
            "kind": {"type": "string", "enum": ["goal", "foul"], "format": "x-kind"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 10,
            },
            "pair": {
                "type": "array",
                "prefixItems": [{"type": "number"}, {"type": "string"}],
            },
            "maybe": {"type": ["string", "null"]},
        },
        "required": ["timestamp_seconds"],
        "additionalProperties": False,
    }
    assert to_gemini_schema(schema) == schema


def test_anyof_and_root_ref_are_supported():
    assert to_gemini_schema({"anyOf": [{"type": "string"}, {"type": "null"}]}) == {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }
    schema = {"type": "object", "properties": {"child": {"$ref": "#"}}}
    assert to_gemini_schema(schema) == schema


def test_defs_are_inlined_not_dropped():
    schema = {
        "$defs": {
            "Event": {
                "type": "object",
                "properties": {"timestamp_seconds": {"type": "number"}},
                "required": ["timestamp_seconds"],
            }
        },
        "type": "object",
        "properties": {
            "events": {"type": "array", "items": {"$ref": "#/$defs/Event"}},
        },
    }
    out = to_gemini_schema(schema)
    assert "$defs" not in out
    assert out["properties"]["events"]["items"] == {
        "type": "object",
        "properties": {"timestamp_seconds": {"type": "number"}},
        "required": ["timestamp_seconds"],
    }


def test_benign_metadata_keywords_pass_through():
    schema = {
        "type": "string",
        "default": "unknown",
        "examples": ["a"],
        "$schema": "https://json-schema.org/draft/2020-12/schema",
    }
    out = to_gemini_schema(schema)
    assert out["default"] == "unknown"


@pytest.mark.parametrize(
    "keyword,schema",
    [
        ("oneOf", {"oneOf": [{"type": "string"}, {"type": "integer"}]}),
        ("allOf", {"allOf": [{"type": "object"}, {"type": "object"}]}),
        ("not", {"not": {"type": "string"}}),
        ("if", {"if": {"type": "string"}, "then": {"type": "string"}}),
        ("pattern", {"type": "string", "pattern": "^a+$"}),
        ("minLength", {"type": "string", "minLength": 1}),
        ("maxLength", {"type": "string", "maxLength": 5}),
        ("multipleOf", {"type": "number", "multipleOf": 0.5}),
        ("exclusiveMinimum", {"type": "number", "exclusiveMinimum": 0}),
        ("uniqueItems", {"type": "array", "items": {"type": "string"}, "uniqueItems": True}),
        ("contains", {"type": "array", "contains": {"type": "string"}}),
        ("const", {"const": "fixed"}),
        ("patternProperties", {"type": "object", "patternProperties": {"^x": {}}}),
        ("dependentRequired", {"type": "object", "dependentRequired": {"a": ["b"]}}),
    ],
)
def test_unsupported_keyword_raises_naming_it(keyword, schema):
    with pytest.raises(UnsupportedSchemaError) as excinfo:
        to_gemini_schema(schema)
    assert keyword in str(excinfo.value)


def test_non_dict_schema_rejected():
    with pytest.raises(UnsupportedSchemaError, match="object"):
        to_gemini_schema(["type", "object"])


# ---------------------------------------------------------------------------
# Native video extraction (mocked)
# ---------------------------------------------------------------------------


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_native_video_happy_path(sdk, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    result = _run(ext.extract(make_request(video_path=str(video))))
    assert result.data == {"ok": True}
    assert result.raw_text is None
    assert result.evidence == []
    assert result.usage == {}


def test_upload_delete_called_on_success(sdk, tmp_path, monkeypatch):
    files = FakeFiles()
    (genai_ns, http), _ = fake_sdk(files=files, models=FakeModels(response=make_response()))
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    _run(ext.extract(make_request(video_path=str(video))))
    assert files.uploaded == [str(video)]
    assert files.deleted == ["files/fake123"]


def test_upload_deleted_on_generate_failure(sdk, tmp_path, monkeypatch):
    files = FakeFiles()
    (genai_ns, http), _ = fake_sdk(
        files=files,
        models=FakeModels(error=APIError(500, {"error": {"message": "boom"}})),
    )
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    with pytest.raises(ProviderRequestError):
        _run(ext.extract(make_request(video_path=str(video))))
    assert files.deleted == ["files/fake123"]


def test_missing_video_file_raises_unsupported_media(sdk, tmp_path):
    ext = GeminiExtractor(api_key="sk-test")
    with pytest.raises(UnsupportedMediaError, match="not found"):
        _run(ext.extract(make_request(video_path=str(tmp_path / "nope.mp4"))))


def test_no_video_path_raises_invalid_input(sdk):
    ext = GeminiExtractor(api_key="sk-test")
    with pytest.raises(InvalidInputError, match="video_path"):
        _run(ext.extract(make_request(video_path=None)))


def test_file_over_options_limit_raises_unsupported_media(sdk, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 1024)
    ext = GeminiExtractor(api_key="sk-test")
    options = ExtractionOptions(max_file_bytes=100)
    with pytest.raises(UnsupportedMediaError, match="exceeds"):
        _run(ext.extract(make_request(video_path=str(video), options=options)))


def test_unknown_strategy_rejected(sdk):
    ext = GeminiExtractor(api_key="sk-test")
    with pytest.raises(UnsupportedStrategyError):
        _run(ext.extract(make_request(strategy="telepathy")))


def test_auto_resolves_to_native_video(sdk, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    result = _run(ext.extract(make_request(video_path=str(video), strategy="auto")))
    assert result.data == {"ok": True}
    assert any("native_video" in w for w in result.warnings)


def test_file_processing_failed_surfaces_error(sdk, tmp_path, monkeypatch):
    files = FakeFiles(states=["PROCESSING", "FAILED"])
    (genai_ns, http), _ = fake_sdk(files=files, models=FakeModels(response=make_response()))
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    with pytest.raises(ProviderRequestError, match="processing failed"):
        _run(ext.extract(make_request(video_path=str(video))))
    assert files.deleted == ["files/fake123"]


def test_processing_timeout_is_bounded(sdk, tmp_path, monkeypatch):
    files = FakeFiles(states=["PROCESSING"])  # never becomes ACTIVE
    (genai_ns, http), _ = fake_sdk(files=files, models=FakeModels(response=make_response()))
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    monkeypatch.setattr("suvix.adapters.gemini._POLL_INTERVAL_SECONDS", 0.01)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    options = ExtractionOptions(per_call_timeout_seconds=0.2)
    with pytest.raises(ProviderTimeoutError):
        _run(ext.extract(make_request(video_path=str(video), options=options)))
    assert files.deleted == ["files/fake123"]


# ---------------------------------------------------------------------------
# Selected frames extraction (mocked)
# ---------------------------------------------------------------------------


def test_selected_frames_sends_image_parts(sdk, monkeypatch):
    (genai_ns, http), created = fake_sdk(models=FakeModels(response=make_response()))
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    ext = GeminiExtractor(api_key="sk-test")
    frames = [
        FrameInput(frame_id="f1", timestamp_seconds=1.0, image_bytes=b"jpeg1"),
        FrameInput(frame_id="f2", timestamp_seconds=2.5, image_bytes=b"jpeg2"),
    ]
    result = _run(
        ext.extract(make_request(video_path=None, frames=frames, strategy="selected_frames"))
    )
    assert result.data == {"ok": True}
    call = created[0].models.calls[0]
    contents = call["contents"]
    image_parts = [p for p in contents if hasattr(p, "inline_data") and p.inline_data]
    assert len(image_parts) == 2
    assert image_parts[0].inline_data.data == b"jpeg1"


def test_selected_frames_without_frames_rejected(sdk):
    ext = GeminiExtractor(api_key="sk-test")
    with pytest.raises(InvalidInputError, match="frames"):
        _run(ext.extract(make_request(video_path=None, frames=None, strategy="selected_frames")))


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _extract_with_error(monkeypatch, tmp_path, error):
    files = FakeFiles()
    (genai_ns, http), _ = fake_sdk(files=files, models=FakeModels(error=error))
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    return ext, make_request(video_path=str(video))


def test_429_maps_to_rate_limit(monkeypatch, tmp_path):
    ext, req = _extract_with_error(
        monkeypatch, tmp_path, APIError(429, {"error": {"message": "quota"}})
    )
    with pytest.raises(RateLimitError):
        _run(ext.extract(req))


def test_5xx_maps_to_provider_request_error_with_cause(monkeypatch, tmp_path):
    cause = APIError(503, {"error": {"message": "overloaded"}})
    ext, req = _extract_with_error(monkeypatch, tmp_path, cause)
    with pytest.raises(ProviderRequestError) as excinfo:
        _run(ext.extract(req))
    assert excinfo.value.__cause__ is cause


def test_sdk_timeout_maps_to_provider_timeout(monkeypatch, tmp_path):
    cause = httpx.TimeoutException("timed out")
    ext, req = _extract_with_error(monkeypatch, tmp_path, cause)
    with pytest.raises(ProviderTimeoutError):
        _run(ext.extract(req))


# ---------------------------------------------------------------------------
# Response normalization: usage, evidence, raw text
# ---------------------------------------------------------------------------


def test_usage_metadata_mapped(monkeypatch, tmp_path):
    usage = SimpleNamespace(
        prompt_token_count=100,
        response_token_count=20,
        total_token_count=120,
        cached_content_token_count=None,
    )
    files = FakeFiles()
    (genai_ns, http), _ = fake_sdk(
        files=files, models=FakeModels(response=make_response(usage=usage))
    )
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    result = _run(ext.extract(make_request(video_path=str(video))))
    assert result.usage == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


def test_usage_never_invented_when_missing(monkeypatch, tmp_path):
    files = FakeFiles()
    (genai_ns, http), _ = fake_sdk(
        files=files, models=FakeModels(response=make_response(usage=None))
    )
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    result = _run(ext.extract(make_request(video_path=str(video))))
    assert result.usage == {}


def test_provider_timestamps_become_provider_reported_evidence(monkeypatch, tmp_path):
    text = (
        '{"events": ['
        '{"timestamp_seconds": 12.5, "description": "goal"},'
        '{"start_seconds": 40.0, "end_seconds": 44.5, "description": "foul"}'
        "]}"
    )
    files = FakeFiles()
    (genai_ns, http), _ = fake_sdk(
        files=files, models=FakeModels(response=make_response(text=text))
    )
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    result = _run(ext.extract(make_request(video_path=str(video))))
    assert len(result.evidence) == 2
    assert all(e.ref_type == "provider_reported" for e in result.evidence)
    by_ts = {e.timestamp_seconds for e in result.evidence if e.timestamp_seconds is not None}
    assert by_ts == {12.5}
    segments = [e for e in result.evidence if e.start_seconds is not None]
    assert len(segments) == 1 and segments[0].end_seconds == 44.5


def test_non_json_text_surfaces_as_raw_text_with_warning(monkeypatch, tmp_path):
    files = FakeFiles()
    (genai_ns, http), _ = fake_sdk(
        files=files, models=FakeModels(response=make_response(text="not json at all"))
    )
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    result = _run(ext.extract(make_request(video_path=str(video))))
    assert result.data is None
    assert result.raw_text == "not json at all"
    assert result.warnings


def test_no_candidates_warns_without_data(monkeypatch, tmp_path):
    resp = SimpleNamespace(text=None, candidates=[], usage_metadata=None)
    files = FakeFiles()
    (genai_ns, http), _ = fake_sdk(files=files, models=FakeModels(response=resp))
    monkeypatch.setattr("suvix.adapters.gemini._load_sdk", lambda: (genai_ns, http))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    ext = GeminiExtractor(api_key="sk-test")
    result = _run(ext.extract(make_request(video_path=str(video))))
    assert result.data is None
    assert any("no candidates" in w for w in result.warnings)
