"""TwelveLabs adapter: native video understanding via the Analyze API.

Workflow (verified 2026-10-15 against docs.twelvelabs.io and ``twelvelabs``
1.3.6): upload the video as an asset → poll until ``ready`` → run sync
analysis (Pegasus) with a ``json_schema`` response format → delete the asset
in a ``finally`` block. Selected frames are supported through the verified
image-analysis path (1–20 images, Pegasus 1.6 only).

Verified behavior is recorded in ``docs/providers/twelvelabs.md`` (§7.4).
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import time
from collections.abc import Callable
from typing import Any, cast

from suvix.adapters.base import (
    AdapterRequest,
    ExtractorCapabilities,
    FrameInput,
    ProviderExtraction,
)
from suvix.contracts import EvidenceRef
from suvix.errors import (
    InvalidInputError,
    ProviderConfigError,
    ProviderRequestError,
    ProviderTimeoutError,
    RateLimitError,
    SuvixError,
    UnsupportedMediaError,
    UnsupportedStrategyError,
)

_SCHEMA_NAME = "suvix_extraction"
_DEFAULT_VIDEO_MODEL = "pegasus1.5"  # documented API default
_IMAGE_MODEL = "pegasus1.6"  # image input requires Pegasus 1.6 (verified)
_MAX_IMAGES = 20  # verified: 1-20 images per sync analysis request
_MAX_EVIDENCE_REFS = 64  # bound on provider-reported timestamp harvesting
_POLL_INTERVAL_SECONDS = 2.0

# Keys the adapter recognizes as provider-reported timestamps when scanning
# the model's own JSON output. Everything found is labeled provider_reported.
_TIMESTAMP_KEYS = {
    "start_time", "start", "start_seconds", "timestamp", "timestamp_seconds",
    "begin", "from",
}
_END_KEYS = {"end_time", "end", "end_seconds", "to"}


class TwelveLabsExtractor:
    """Extract structured data with TwelveLabs' Pegasus Analyze API.

    ``model`` is optional: the adapter uses the documented API default
    (``pegasus1.5``) for native video and ``pegasus1.6`` for image input.
    An explicit model is passed through verbatim — except that image input
    with any model other than ``pegasus1.6`` is rejected loudly (the API
    returns ``parameter_invalid`` otherwise).
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        asset_ready_timeout_seconds: float = 300.0,
    ) -> None:
        try:
            twelvelabs = importlib.import_module("twelvelabs")
            types = importlib.import_module("twelvelabs.types")
        except ImportError as exc:
            raise ProviderConfigError(
                "The 'twelvelabs' package is required for the TwelveLabs adapter. "
                "Install it with: pip install suvix[twelvelabs]"
            ) from exc

        key = api_key or os.environ.get("TWELVELABS_API_KEY")
        if not key:
            raise ProviderConfigError(
                "TwelveLabs API key missing. Pass api_key= or set TWELVELABS_API_KEY."
            )
        self._model = model
        self._api_key = key
        self._types = types
        self._asset_ready_timeout = asset_ready_timeout_seconds
        # Blocking SDK client; calls are offloaded with asyncio.to_thread.
        self._client = twelvelabs.TwelveLabs(api_key=key)

    # -- VideoExtractor protocol -----------------------------------------

    @property
    def name(self) -> str:
        return f"twelvelabs/{self._model or 'default'}"

    @property
    def capabilities(self) -> ExtractorCapabilities:
        model_label = self._model or (
            f"{_DEFAULT_VIDEO_MODEL} for video, {_IMAGE_MODEL} for image input"
        )
        return ExtractorCapabilities(
            provider="twelvelabs",
            model=model_label,
            native_video=True,
            image_input=True,
            multi_image=True,
            structured_output=True,
            json_schema_notes=(
                "Sync analysis supports response_format with type json_schema "
                "(verified). The adapter always requests strict JSON Schema "
                "output and parses the text payload."
            ),
            provider_upload=True,
            file_reference=True,
            max_duration_seconds=3600.0,
            max_file_bytes=209_715_200,  # 200 MB direct local upload (verified)
            usage_metadata=True,
            timestamp_support=True,
            exposes_sampled_frames=False,
            notes=(
                "Pegasus ingests the video itself; Suvix does not know which "
                "frames were inspected, so evidence is provider_reported. "
                "Selected frames use the verified image path (1-20 images, "
                "Pegasus 1.6 only). Uploaded assets are deleted after analysis; "
                "see docs/providers/twelvelabs.md for retention caveats."
            ),
        )

    async def extract(self, request: AdapterRequest) -> ProviderExtraction:
        if request.strategy == "native_video":
            return await self._extract_native_video(request)
        if request.strategy == "selected_frames":
            return await self._extract_selected_frames(request)
        raise UnsupportedStrategyError(
            f"TwelveLabsExtractor does not support strategy '{request.strategy}'. "
            "Use 'native_video' (the provider ingests the video) or "
            "'selected_frames' (1-20 frames via the image path, Pegasus 1.6)."
        )

    # -- native video ------------------------------------------------------

    async def _extract_native_video(self, request: AdapterRequest) -> ProviderExtraction:
        if not request.video_path:
            raise InvalidInputError(
                "The 'native_video' strategy requires request.video_path."
            )
        created_assets: list[str] = []
        try:
            asset_id = await self._upload_video(request.video_path)
            created_assets.append(asset_id)
            await self._wait_until_ready(asset_id)

            model_name = self._model or _DEFAULT_VIDEO_MODEL
            response_format = self._response_format(request.json_schema)
            prompt = (
                f"{request.instructions}\n\n"
                "Respond with a single JSON object conforming to the provided "
                "JSON schema."
            )
            call_kwargs: dict[str, Any] = {
                "model_name": model_name,
                "video": self._types.VideoContext_AssetId(asset_id=asset_id),
                "prompt_v_2": self._types.AnalyzePromptV2(input_text=prompt),
                "response_format": response_format,
            }
            try:
                response = await self._call_with_timeout(
                    request, self._client.analyze, **call_kwargs
                )
            except Exception as exc:
                raise self._map_error(exc) from exc

            return self._to_extraction(
                response,
                evidence_factory=lambda data: self._provider_timestamp_evidence(data),
            )
        finally:
            await self._delete_assets(created_assets)

    # -- selected frames ---------------------------------------------------

    async def _extract_selected_frames(
        self, request: AdapterRequest
    ) -> ProviderExtraction:
        if not request.frames:
            raise InvalidInputError(
                "The 'selected_frames' strategy requires request.frames."
            )
        if len(request.frames) > _MAX_IMAGES:
            raise UnsupportedStrategyError(
                f"TwelveLabs image analysis accepts at most {_MAX_IMAGES} images "
                f"per request; got {len(request.frames)}. Reduce the frame count."
            )
        if self._model is not None and self._model != _IMAGE_MODEL:
            raise UnsupportedStrategyError(
                f"TwelveLabs image input requires model '{_IMAGE_MODEL}'; "
                f"got '{self._model}'. The API rejects other models with "
                "parameter_invalid."
            )
        model_name = self._model or _IMAGE_MODEL

        created_assets: list[str] = []
        try:
            images = []
            for frame in request.frames:
                asset_id = await self._upload_frame(frame)
                created_assets.append(asset_id)
                await self._wait_until_ready(asset_id)
                images.append(
                    self._types.AnalyzeImageInput(
                        name=f"frame_{frame.frame_id}", asset_id=asset_id
                    )
                )

            response_format = self._response_format(request.json_schema)
            prompt = (
                f"{request.instructions}\n\n"
                "Respond with a single JSON object conforming to the provided "
                "JSON schema."
            )
            try:
                response = await self._call_with_timeout(
                    request,
                    self._client.analyze,
                    model_name=model_name,
                    image=images,
                    prompt=prompt,  # required (not prompt_v2) for image input
                    response_format=response_format,
                )
            except Exception as exc:
                raise self._map_error(exc) from exc

            return self._to_extraction(
                response,
                evidence_factory=lambda data: [
                    EvidenceRef(
                        ref_type="frame",
                        frame_id=frame.frame_id,
                        timestamp_seconds=frame.timestamp_seconds,
                    )
                    for frame in request.frames or []
                ],
            )
        finally:
            await self._delete_assets(created_assets)

    # -- upload / lifecycle --------------------------------------------------

    def _is_url(self, video_path: str) -> bool:
        return video_path.startswith(("http://", "https://"))

    async def _upload_video(self, video_path: str) -> str:
        """Upload the video and return the asset id."""
        try:
            if self._is_url(video_path):
                asset = await asyncio.to_thread(
                    self._client.assets.create, method="url", url=video_path
                )
            else:
                try:
                    with open(video_path, "rb") as fh:
                        video_bytes = fh.read()
                except OSError as exc:
                    raise UnsupportedMediaError(
                        f"Cannot read video file for upload: {video_path}",
                        details={"video_path": video_path},
                    ) from exc
                asset = await asyncio.to_thread(
                    self._client.assets.create, method="direct", file=video_bytes
                )
        except SuvixError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc
        # SDK asset objects are untyped (Any); their id is the asset string.
        return cast(str, asset.id)

    async def _upload_frame(self, frame: FrameInput) -> str:
        """Upload one frame as an image asset; return the asset id."""
        try:
            asset = await asyncio.to_thread(
                self._client.assets.create,
                method="direct",
                file=frame.image_bytes,
                filename=f"{frame.frame_id}.jpg",
            )
        except Exception as exc:
            raise self._map_error(exc) from exc
        # SDK asset objects are untyped (Any); their id is the asset string.
        return cast(str, asset.id)

    async def _wait_until_ready(self, asset_id: str) -> None:
        """Poll the asset until ready (bounded)."""
        deadline = time.monotonic() + self._asset_ready_timeout
        while True:
            try:
                asset = await asyncio.to_thread(
                    self._client.assets.retrieve, asset_id
                )
            except Exception as exc:
                raise self._map_error(exc) from exc
            status = getattr(asset, "status", None)
            if status == "ready":
                return
            if status == "failed":
                raise ProviderRequestError(
                    f"TwelveLabs asset processing failed for asset {asset_id}.",
                    details={"provider": "twelvelabs", "asset_id": asset_id},
                )
            if time.monotonic() >= deadline:
                raise ProviderTimeoutError(
                    f"Timed out waiting for TwelveLabs asset {asset_id} to be ready.",
                    details={"provider": "twelvelabs", "asset_id": asset_id},
                )
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def _delete_assets(self, asset_ids: list[str]) -> list[str]:
        """Best-effort deletion of uploaded assets. Returns warnings."""
        warnings: list[str] = []
        for asset_id in asset_ids:
            try:
                await asyncio.to_thread(self._client.assets.delete, asset_id)
            except Exception as exc:  # noqa: BLE001 - cleanup must not mask results
                warnings.append(
                    f"Failed to delete TwelveLabs asset {asset_id}: "
                    f"{self._redact(str(exc))}"
                )
        return warnings

    async def _call_with_timeout(
        self, request: AdapterRequest, func: Callable[..., Any], **kwargs: Any
    ) -> Any:
        timeout = request.options.per_call_timeout_seconds
        return await asyncio.wait_for(asyncio.to_thread(func, **kwargs), timeout)

    # -- response handling ---------------------------------------------------

    def _response_format(self, schema: dict[str, Any]) -> Any:
        return self._types.SyncResponseFormat(
            type="json_schema",
            json_schema=self._types.TextResponseFormatJsonSchema(
                name=_SCHEMA_NAME,
                strict=True,
                schema_=schema,
                description="Schema-guided video extraction result.",
            ),
        )

    def _to_extraction(
        self,
        response: Any,
        *,
        evidence_factory: Callable[[dict[str, Any]], list[EvidenceRef]],
    ) -> ProviderExtraction:
        text = getattr(response, "data", None)
        data: dict[str, Any] | None = None
        raw_text: str | None = None
        warnings: list[str] = []
        if isinstance(text, str) and text.strip():
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                raw_text = text
                warnings.append(
                    "Provider returned non-JSON text; surfaced as raw_text."
                )
            else:
                if isinstance(parsed, dict):
                    data = parsed
                else:
                    raw_text = text
                    warnings.append(
                        "Provider returned JSON that is not an object; "
                        "surfaced as raw_text."
                    )
        else:
            raw_text = text if isinstance(text, str) else None
            warnings.append("Provider returned empty analysis text.")

        usage: dict[str, Any] = {}
        resp_usage = getattr(response, "usage", None)
        if resp_usage is not None:
            for key in ("input_tokens", "output_tokens"):
                value = getattr(resp_usage, key, None)
                if value is not None:
                    usage[key] = value

        return ProviderExtraction(
            data=data,
            raw_text=raw_text,
            evidence=evidence_factory(data) if data is not None else [],
            usage=usage,
            warnings=warnings,
        )

    def _provider_timestamp_evidence(self, data: dict[str, Any]) -> list[EvidenceRef]:
        """Harvest provider-reported timestamps from the model's JSON output.

        Every hit is labeled ``provider_reported`` — Suvix did not verify which
        frames Pegasus inspected. Bounded to ``_MAX_EVIDENCE_REFS`` hits.
        """
        refs: list[EvidenceRef] = []

        def visit(node: Any) -> None:
            if len(refs) >= _MAX_EVIDENCE_REFS:
                return
            if isinstance(node, dict):
                start = _first_number(node, _TIMESTAMP_KEYS)
                if start is not None:
                    end = _first_number(node, _END_KEYS)
                    if end is not None and end < start:
                        end = None
                    refs.append(
                        EvidenceRef(
                            ref_type="provider_reported",
                            start_seconds=float(start),
                            end_seconds=float(end) if end is not None else None,
                            note="Timestamp reported by the provider in its output.",
                        )
                    )
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(data)
        return refs

    # -- error mapping ---------------------------------------------------------

    def _map_error(self, exc: BaseException) -> SuvixError:
        if isinstance(exc, SuvixError):
            return exc
        message = self._redact(str(exc))
        details: dict[str, Any] = {"provider": "twelvelabs"}
        if isinstance(exc, asyncio.TimeoutError) or (
            "timeout" in type(exc).__name__.lower()
        ):
            return ProviderTimeoutError(message, details=details)
        if getattr(exc, "status_code", None) == 429:
            details["status_code"] = 429
            return RateLimitError(message, details=details)
        details["error_type"] = type(exc).__name__
        return ProviderRequestError(message, details=details)

    def _redact(self, text: str) -> str:
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "[REDACTED]")
        return text


def _first_number(mapping: dict[str, Any], keys: set[str]) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None
