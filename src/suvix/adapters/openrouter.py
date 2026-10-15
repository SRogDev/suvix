"""OpenRouter adapter: schema-guided extraction via the OpenAI-compatible API.

Strategy: ``selected_frames``. The adapter sends locally-extracted frames as
``image_url`` data-URI parts in a ``/chat/completions`` request and asks for
strict JSON Schema structured output. Native video is rejected explicitly —
OpenRouter documents that video support varies by model, endpoint, and the
provider behind the gateway, so this adapter never claims it.

Verified behavior is recorded in ``docs/providers/openrouter.md`` (§7.4).
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from suvix.adapters.base import (
    AdapterRequest,
    ExtractorCapabilities,
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
    UnsupportedSchemaError,
    UnsupportedStrategyError,
)

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_SCHEMA_NAME = "suvix_extraction"


class OpenRouterExtractor:
    """Extract structured data via OpenRouter's OpenAI-compatible endpoint.

    The developer explicitly selects the model (e.g. ``"openai/gpt-4o-mini"``);
    the adapter never substitutes another one. Only ``selected_frames`` is
    supported: frames are sent as base64 ``image_url`` parts.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        try:
            openai = importlib.import_module("openai")
        except ImportError as exc:
            raise ProviderConfigError(
                "The 'openai' package is required for the OpenRouter adapter. "
                "Install it with: pip install suvix[openrouter]"
            ) from exc

        key = api_key or _env_api_key()
        if not key:
            raise ProviderConfigError(
                "OpenRouter API key missing. Pass api_key= or set OPENROUTER_API_KEY."
            )
        self._openai = openai
        self._model = model
        self._api_key = key
        # Blocking SDK client; calls are offloaded with asyncio.to_thread.
        self._client = openai.OpenAI(api_key=key, base_url=base_url)

    # -- VideoExtractor protocol -----------------------------------------

    @property
    def name(self) -> str:
        return f"openrouter/{self._model}"

    @property
    def capabilities(self) -> ExtractorCapabilities:
        return ExtractorCapabilities(
            provider="openrouter",
            model=self._model,
            native_video=False,
            image_input=True,
            multi_image=True,
            structured_output=True,
            json_schema_notes=(
                "response_format json_schema (strict) on /chat/completions; "
                "the request pins provider.require_parameters=true so OpenRouter "
                "only routes to endpoints that support structured output. "
                "Exact enforcement is per-endpoint — see docs/providers/openrouter.md."
            ),
            usage_metadata=True,
            notes=(
                "Native video is NOT claimed: OpenRouter documents that video "
                "support varies by model, endpoint, and upstream provider. "
                "Use selected_frames with a vision-capable model chosen by the "
                "developer. Usage token counts come from the model's native "
                "tokenizer (see usage-accounting docs)."
            ),
        )

    async def extract(self, request: AdapterRequest) -> ProviderExtraction:
        if request.strategy != "selected_frames":
            raise UnsupportedStrategyError(
                f"OpenRouterExtractor does not support strategy "
                f"'{request.strategy}'. Use 'selected_frames' with a "
                f"vision-capable model (native video support varies by model "
                f"behind the gateway and is not claimed by this adapter)."
            )
        if not request.frames:
            raise InvalidInputError(
                "The 'selected_frames' strategy requires request.frames."
            )
        response_format = self._response_format(request.json_schema)

        text_part = (
            f"{request.instructions}\n\n"
            "Return ONLY a JSON object that conforms to this JSON Schema:\n"
            f"{json.dumps(request.json_schema)}"
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": text_part}]
        for frame in request.frames:
            data_uri = (
                f"data:{frame.mime_type};base64,"
                f"{base64.b64encode(frame.image_bytes).decode('ascii')}"
            )
            content.append(
                {"type": "image_url", "image_url": {"url": data_uri}}
            )

        call_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": content}],
            "response_format": response_format,
            # Route only to endpoints that honor the structured-output params.
            "extra_body": {"provider": {"require_parameters": True}},
        }

        timeout = self._timeout_seconds(request)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._client.chat.completions.create, **call_kwargs),
                timeout,
            )
        except Exception as exc:
            raise self._map_error(exc) from exc

        return self._to_extraction(request, response)

    # -- internals ---------------------------------------------------------

    def _timeout_seconds(self, request: AdapterRequest) -> float | None:
        return request.options.per_call_timeout_seconds

    def _response_format(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Translate the caller's JSON Schema to OpenRouter's response_format.

        Schemas that cannot be represented are rejected loudly — keywords are
        never silently dropped.
        """
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise UnsupportedSchemaError(
                f"Invalid JSON Schema for structured output: {exc.message}",
                details={"schema_error": exc.message},
            ) from exc
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise UnsupportedSchemaError(
                "OpenRouter structured output requires a root schema with "
                '"type": "object". Refactor the schema so the top level is an '
                "object.",
                details={"root_type": schema.get("type") if isinstance(schema, dict) else None},
            )
        return {
            "type": "json_schema",
            "json_schema": {
                "name": _SCHEMA_NAME,
                "strict": True,
                "schema": schema,
            },
        }

    def _to_extraction(
        self, request: AdapterRequest, response: Any
    ) -> ProviderExtraction:
        content = ""
        try:
            content = response.choices[0].message.content or ""
        except (AttributeError, IndexError):
            content = ""

        data: dict[str, Any] | None = None
        raw_text: str | None = None
        warnings: list[str] = []
        if content.strip():
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                raw_text = content
                warnings.append(
                    "Provider returned non-JSON content despite structured "
                    "output; surfaced as raw_text."
                )
            else:
                if isinstance(parsed, dict):
                    data = parsed
                else:
                    raw_text = content
                    warnings.append(
                        "Provider returned JSON that is not an object; "
                        "surfaced as raw_text."
                    )
        else:
            raw_text = content
            warnings.append("Provider returned empty content.")

        evidence = [
            EvidenceRef(
                ref_type="frame",
                frame_id=frame.frame_id,
                timestamp_seconds=frame.timestamp_seconds,
            )
            for frame in request.frames or []
        ]

        usage: dict[str, Any] = {}
        resp_usage = getattr(response, "usage", None)
        if resp_usage is not None:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost"):
                value = getattr(resp_usage, key, None)
                if value is not None:
                    usage[key] = value

        return ProviderExtraction(
            data=data, raw_text=raw_text, evidence=evidence,
            usage=usage, warnings=warnings,
        )

    def _map_error(self, exc: BaseException) -> SuvixError:
        """Map SDK/transport failures to the Suvix error contract.

        The API key is redacted from every message and never lands in details.
        """
        if isinstance(exc, SuvixError):
            return exc
        message = self._redact(str(exc))
        details: dict[str, Any] = {"provider": "openrouter"}
        mod = self._openai

        timeout_cls = getattr(mod, "APITimeoutError", ())
        if isinstance(exc, asyncio.TimeoutError) or (
            timeout_cls and isinstance(exc, timeout_cls)
        ):
            return ProviderTimeoutError(message, details=details)

        status_cls = getattr(mod, "APIStatusError", ())
        if (
            status_cls
            and isinstance(exc, status_cls)
            and getattr(exc, "status_code", None) == 429
        ):
            details["status_code"] = 429
            return RateLimitError(message, details=details)

        openai_error = getattr(mod, "OpenAIError", Exception)
        if isinstance(exc, openai_error):
            status_code = getattr(exc, "status_code", None)
            if status_code is not None:
                details["status_code"] = status_code
            return ProviderRequestError(message, details=details)

        details["error_type"] = type(exc).__name__
        return ProviderRequestError(message, details=details)

    def _redact(self, text: str) -> str:
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "[REDACTED]")
        return text


def _env_api_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY")
