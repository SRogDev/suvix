# OpenRouter — §7.4 provider verification record

**Verification date:** 2026-10-15
**Adapter:** `src/suvix/adapters/openrouter.py` (`OpenRouterExtractor`)
**SDK verified:** `openai` 3.31.0 (repo extra `suvix[openrouter]` pins `openai>=1.40`; the
OpenAI-compatible client is the documented way to reach OpenRouter)
**Status of this record:** treat as time-sensitive; re-verify before M8 benchmarks.

## Official documentation (verified live 2026-10-15)

- Docs hub: https://openrouter.ai/docs
- Structured outputs: https://openrouter.ai/docs/guides/features/structured-outputs
- Image inputs: https://openrouter.ai/docs/guides/overview/multimodal/image-understanding
- Chat completion API reference: https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion
- Usage accounting: https://openrouter.ai/docs/cookbook/administration/usage-accounting
- Provider routing (`require_parameters`): https://openrouter.ai/docs/guides/routing/provider-selection

## VERIFIED

- **Endpoint:** `POST https://openrouter.ai/api/v1/chat/completions`, OpenAI-compatible.
  The adapter reaches it through the `openai` Python SDK with
  `base_url="https://openrouter.ai/api/v1"` (overridable).
- **Auth:** `Authorization: Bearer $OPENROUTER_API_KEY`. The adapter reads
  `OPENROUTER_API_KEY` from the environment unless `api_key=` is passed explicitly.
- **Structured output:** `response_format: {"type": "json_schema", "json_schema":
  {"name", "strict": true, "schema": {...}}}` is supported **for select models** —
  support is determined **per endpoint, not per model**, and can change over time.
  To force routing to a supporting endpoint, the adapter always sends
  `extra_body={"provider": {"require_parameters": true}}` (documented routing control).
- **Strict mode caveat (official):** "Enforcement varies by provider: some guarantee
  schema-conforming output, while others translate your schema into their own
  structured-output format or treat it as a strong hint, so exact compliance is not
  guaranteed on every endpoint. Strict modes may also restrict which JSON Schema
  features you can use." The adapter therefore still parses defensively and local
  validation happens downstream (M6).
- **Multi-image input:** verified. Images are sent as `image_url` content parts, either
  as URLs or base64 data URIs; **multiple images go in separate content-array entries**.
  The adapter sends `data:{mime};base64,...` URIs. OpenRouter recommends the text
  prompt first, then images — the adapter follows that order. The number of images
  allowed per request **varies by provider and model** (no universal documented limit).
- **Usage reporting:** verified. Every non-streaming response includes `usage` with
  `prompt_tokens`, `completion_tokens`, `total_tokens` — "token counts are calculated
  using the model's native tokenizer" (i.e. **not estimates**), plus `cost` in credits.
  The adapter maps these four fields when present. Async reconciliation via
  `GET /api/v1/generation?id=<generation-id>` exists but is not used by the adapter.
- **Error semantics:** HTTP 429 on rate limit (mapped to `RateLimitError`); other
  non-2xx statuses map to `ProviderRequestError`; SDK timeouts map to
  `ProviderTimeoutError`.

## UNVERIFIED / explicitly not claimed

- **Native video:** NOT verified for any specific model. OpenRouter documents that
  video support "may vary by model, endpoint, request format, and provider behind
  the gateway". The adapter sets `capabilities.native_video=False` and raises
  `UnsupportedStrategyError` for the `native_video` strategy with an actionable
  message. This is a deliberate honest default, not a gap to paper over.
- **Exact per-endpoint structured-output enforcement** for the developer's chosen
  model — verify on the model's page (`structured_outputs` in the Providers section)
  before relying on strict guarantees.
- **Image count limits** for a specific model — undocumented universally; the core's
  `max_frames` bound is the practical control.

## Credential configuration

| Variable             | Required | Purpose                        |
|----------------------|----------|--------------------------------|
| `OPENROUTER_API_KEY` | yes      | Bearer token for the API       |

No other credentials. The key is never logged and is redacted from error messages.

## Supported models / strategies

- **Models:** any OpenRouter model slug, explicitly chosen by the developer
  (`model=` is required). The adapter never substitutes models.
- **Strategies:** `selected_frames` only. `native_video` and anything else raise
  `UnsupportedStrategyError` — no silent substitution.

## Schema constraints (adapter policy)

- The schema must be valid JSON Schema (Draft 2020-12); invalid schemas raise
  `UnsupportedSchemaError`.
- The root must be `{"type": "object", ...}` — structured-output engines require an
  object root; anything else raises `UnsupportedSchemaError`.
- The schema is passed through **verbatim** with `strict: true`. Keywords are never
  silently dropped. Provider-side rejections (HTTP 400) surface as
  `ProviderRequestError`.
- The schema JSON is also embedded in the text part of the message as a hint for
  endpoints whose enforcement is weaker (documented token cost of doing so).

## Media restrictions

- Frames arrive from the core as `FrameInput` (bytes + MIME type); the adapter
  base64-encodes them into data URIs. No provider-side upload happens in this
  adapter (`provider_upload=False`, `file_reference=False`).
- Oversized images: OpenRouter may resize automatically per provider; not verified
  per model — keep frames modest (the core's sampling bounds apply).

## Usage reporting

Mapped from the response `usage` object: `prompt_tokens`, `completion_tokens`,
`total_tokens`, `cost` (when present). Absent fields are omitted, never zero-filled.

## Known limitations

1. No native video path — by design (see above).
2. Structured-output enforcement is per-endpoint; `require_parameters=true` routes
   around non-supporting endpoints but cannot upgrade a weak implementation.
3. Usage reflects the upstream provider's accounting as reported by OpenRouter.
4. No retries: one call per `extract()`; the core owns retry/recovery policy.

## Minimal working request

```python
import asyncio, os
from suvix.adapters.openrouter import OpenRouterExtractor
from suvix.adapters.base import AdapterRequest, FrameInput
from suvix.options import ExtractionOptions

async def main():
    ex = OpenRouterExtractor(model="openai/gpt-4o-mini")  # needs OPENROUTER_API_KEY
    with open("frame0.jpg", "rb") as fh:
        frame_bytes = fh.read()
    req = AdapterRequest(
        video_path=None,
        schema={"type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"]},
        instructions="Summarize what is visible.",
        options=ExtractionOptions(),
        frames=[FrameInput(frame_id="f0", timestamp_seconds=0.0,
                           image_bytes=frame_bytes, mime_type="image/jpeg")],
        strategy="selected_frames",
    )
    out = await ex.extract(req)
    print(out.data, out.usage)

asyncio.run(main())
```

## Integration-test procedure

`tests/integration/test_openrouter.py` is skipped by default. To run it (billable):

```bash
SUVIX_RUN_INTEGRATION_TESTS=1 OPENROUTER_API_KEY=sk-or-v1-... \
  uv run pytest tests/integration/test_openrouter.py -q
# optional: SUVIX_OPENROUTER_MODEL=<another slug>
```

Without the env flag the test skips; with the flag but no key it **fails loudly**
instead of silently passing. Not run in CI. Not executed during M7 development
(recorded here as written-but-skipped).
