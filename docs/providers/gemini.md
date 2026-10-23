# Gemini provider — verification record (§7.4)

**Verification date:** 2026-10-15 (pricing, video tokenization, and Files API
limits re-verified 2026-10-23 — see "Re-verification 2026-10-23" below)
**Verified by:** Agent D (Suvix Milestone 3)
**SDK verified:** `google-genai` **2.31.0** (`from google import genai`; `genai.Client(api_key=...)`)
**Adapter:** `src/suvix/adapters/gemini.py` (`GeminiExtractor`)

Every claim below is labeled **VERIFIED** (official docs or the installed SDK
surface) or **UNVERIFIED** (inferred, assumed, or from unofficial sources).
Nothing in `ExtractorCapabilities` goes beyond VERIFIED items.

## Official documentation URLs

- Structured output: https://ai.google.dev/gemini-api/docs/structured-output
  (page last updated 2026-10-13 UTC per page footer — very fresh)
- Pricing: https://ai.google.dev/gemini-api/docs/pricing
- Video understanding: https://ai.google.dev/gemini-api/docs/video-understanding
- Files API: https://ai.google.dev/gemini-api/docs/files
- Image understanding (multi-image): https://ai.google.dev/gemini-api/docs/vision
- Interactions API (newer surface; NOT used by this adapter):
  https://ai.google.dev/gemini-api/docs/interactions-overview

Note: the docs now default their examples to the new **Interactions API**
(`client.interactions.create`, `google-genai` ≥ 2.3.0). This adapter deliberately
uses the classic **`models.generate_content`** API because the plan's spec
names it, it remains fully supported, and the Interactions page itself lists
features that exist in `generateContent` but not (yet) in Interactions
(Batch API, Python automatic function calling, explicit caching, safety
settings). If Google deprecates `generateContent`, revisit.

## Re-verification 2026-10-23 (pricing, tokenization, Files API)

Source for every figure in this section: https://ai.google.dev/gemini-api/docs/pricing
(pricing), https://ai.google.dev/gemini-api/docs/video-understanding
(tokenization), https://ai.google.dev/gemini-api/docs/files (Files API) —
all fetched and verified 2026-10-23. These figures supersede any older
recorded prices.

### Pricing (VERIFIED 2026-10-23) — paid tier, Standard, per 1M tokens (USD)

| Model | Input | Output |
|---|---|---|
| `gemini-2.5-flash` | $0.30 (text/image/video); $1.00 (audio) | $2.50 |
| `gemini-2.5-pro` | $1.25 (prompts ≤ 200k tokens); $2.50 (> 200k) | $10.00 (≤ 200k); $15.00 (> 200k) |
| `gemini-2.5-flash-lite` | $0.10 (text/image/video); $0.30 (audio) | $0.40 |

- The prices recorded earlier in this project ($0.15/$0.60 for Flash,
  $1.25/$5.00 flat for Pro) are **stale** — do not use them.
- `suvix.evaluation.cost.load_verified_pricing_snapshot()` registers the
  text/image/video rates above (per-1k conversions: Flash 0.0003/0.0025,
  Pro 0.00125/0.01, Flash-Lite 0.0001/0.0004). **Tier limitation:** the
  flat per-1k table can only hold the Pro ≤200k tier — estimates above
  200k prompt tokens understate Pro cost. Audio input rates are likewise
  not represented in the flat table.

### Video tokenization (VERIFIED 2026-10-23)

Static mode (video-understanding doc, page last updated 2026-10-13 UTC):
frames are sampled at 1 FPS and tokenized at **258 tokens per frame** at
default resolution, or **66 tokens per frame** when `media_resolution`
is low; audio is 32 tokens/second. Totals: ~300 tokens/second of video
at high resolution, ~100 tokens/second at default (low) media
resolution.

### Files API (re-confirmed VERIFIED 2026-10-23)

- **20 GB of files per project, per-file maximum 2 GB** (Files API doc);
  files are stored for 48 hours. (The video-understanding doc's input
  table refines the per-file limit by tier: 20 GB paid / 2 GB free.)
- The docs state files are automatically deleted after 48 hours and
  offer a manual `files.delete` call, but they give **no deletion
  guarantee** — nothing promises when a deletion actually purges the
  data. Suvix therefore claims only that it *requests* deletion (see
  "File retention and deletion" below), never that deletion is proven.

## Supported input modes (VERIFIED)

| Mode | Mechanism | Status |
|---|---|---|
| Native video | Files API upload → poll `state == ACTIVE` → `Part.from_uri(file_uri, mime_type)` in `generate_content` | VERIFIED (video-understanding + files docs) |
| Single image | `Part.from_bytes(data=..., mime_type=...)` inline in `contents` | VERIFIED (vision docs) |
| Multiple images | Multiple image parts in one `contents` array ("Prompting with multiple images") | VERIFIED (vision docs) |

The `selected_frames` strategy sends frames as inline image parts in
chronological order, each preceded by a `"Frame <id> at <t>s:"` text label.

## Structured output — JSON Schema subset (VERIFIED)

Configured via `GenerateContentConfig(response_mime_type="application/json",
response_json_schema={...})` — field names verified in the installed SDK's
`GenerateContentConfig` model. Official docs (updated 2026-10-13) support:

- **Types:** `string`, `number`, `integer`, `boolean`, `object`, `array`,
  `null` (nullable via type arrays, e.g. `{"type": ["string", "null"]}`).
- **Object:** `properties`, `required`, `additionalProperties`
  (boolean or schema).
- **String:** `enum`, `format` (e.g. `date-time`, `date`, `time`).
- **Number/integer:** `enum`, `minimum`, `maximum`.
- **Array:** `items`, `prefixItems`, `minItems`, `maxItems`.
- **Descriptive:** `title`, `description`.
- **Also demonstrated in official examples:** `anyOf` (conditional schemas),
  `"$ref": "#"` (recursive root reference).

The adapter's `to_gemini_schema()` passes exactly these through, inlines
`$defs`/`definitions` (lossless — constraints preserved, no silent drops),
and raises `UnsupportedSchemaError` naming the keyword for everything else,
including: `oneOf`, `allOf`, `not`, `if`/`then`/`else`, `pattern`,
`minLength`, `maxLength`, `multipleOf`, `exclusiveMinimum`,
`exclusiveMaximum`, `uniqueItems`, `contains`, `const`, `patternProperties`,
`dependentRequired`, and non-root/non-`$defs` `$ref` values. Benign metadata
(`$schema`, `$id`, `$comment`, `default`, `examples`, `readOnly`,
`writeOnly`, `deprecated`) passes through unchanged.

Limitations (VERIFIED, from the docs): "Very large or deeply nested schemas
may be rejected." Output is guaranteed syntactically valid JSON matching the
schema — **not** semantically correct values; suvix always validates locally.

## Media limits (VERIFIED — only what docs state)

- **File API upload size:** per-file maximum **2 GB** (Files API doc);
  the video-understanding doc's table refines this to **20 GB (paid) /
  2 GB (free)**. Tier-dependent → `capabilities.max_file_bytes` is `None`
  (not enforceable uniformly); document, don't guess the caller's tier.
- **Total project storage:** 20 GB (Files API doc).
- **Video duration:** models with a 1M-token context window process up to
  **~3 hours at default (low) media resolution**, ~1 hour at high resolution
  (video-understanding doc). `capabilities.max_duration_seconds = 10800`.
- **Static processing mode (default for all models):** frames extracted at
  **1 FPS** with per-second timestamps; audio at 32 tokens/sec
  (~100 tok/s at low resolution, ~300 tok/s at high). UNVERIFIED: which exact
  frames the model "uses" — the response never exposes sampled frame ids, so
  `exposes_sampled_frames=False` and all evidence is `provider_reported`.
- **Agentic video mode** (Gemini 3.5 Flash Lite and later) exists but is NOT
  used by this adapter (UNVERIFIED behavior for structured extraction).

## Usage reporting (VERIFIED)

`GenerateContentResponse.usage_metadata` fields (verified in SDK 2.31.0):
`prompt_token_count`, **`response_token_count`**, `total_token_count`,
`cached_content_token_count`, `thoughts_token_count`, plus details dicts.

> Naming note: the v1 API/SDK called the output field
> `candidates_token_count`; the v2 SDK (installed) renamed it to
> `response_token_count`. The adapter accepts both (tries `response_…`
> first) and maps to `{"input_tokens", "output_tokens", "total_tokens"}`.
> Missing values are omitted, never invented.

## File retention and deletion (VERIFIED)

- Files are **automatically deleted after 48 hours** (Files API doc;
  re-confirmed 2026-10-23). The docs give **no deletion guarantee**
  about purge timing — see "Re-verification 2026-10-23".
- Documented manual deletion: `client.files.delete(name=myfile.name)`
  (Python). The adapter calls this in a `finally` block after every
  native-video extraction — on success, on provider failure, and on timeout.
  A deletion failure is recorded as a warning, never masks the result.
- File state lifecycle: `PROCESSING` → `ACTIVE` (or `FAILED`).
  `FileState` enum in SDK 2.31.0: `STATE_UNSPECIFIED, PROCESSING, ACTIVE,
  FAILED`. The adapter polls `files.get(name=...)` every 2s until `ACTIVE`,
  raises `ProviderRequestError` on `FAILED`, and the whole extraction is
  bounded by `options.per_call_timeout_seconds` (default 120s).

## Error mapping (VERIFIED SDK surface)

- `google.genai.errors.APIError` with `.code == 429` → `RateLimitError`.
- Other `APIError` (4xx/5xx) → `ProviderRequestError` (original kept as
  `__cause__`; message contains only code/status/details, never the key).
- `httpx.TimeoutException` or `asyncio.TimeoutError` (outer `wait_for`
  bound) → `ProviderTimeoutError`. UNVERIFIED: the SDK has no dedicated
  timeout error class; mapping relies on the httpx transport behavior.

## Credential configuration

`GeminiExtractor(api_key=...)`, else the `GEMINI_API_KEY` environment
variable. Missing → `ProviderConfigError` at construction (never at import
time, so the core stays light). The key is stored only inside the SDK
client; it is never logged, never interpolated into exceptions, and never
placed in `details`.

## Supported models and strategies

- Default model: **`gemini-3.8-flash`** — the stable Flash model used as the
  default in all current official docs examples (VERIFIED 2026-10-15);
  `gemini-2.5-flash` remains a stable alternative (VERIFIED). Any model id
  can be passed explicitly; the developer chooses, the adapter never
  switches.
- Strategies: `native_video` (default; `auto` resolves to it with a recorded
  warning), `selected_frames`.

## Known unsupported / limitations

- No provider-exposed sampled-frame ids → evidence is always
  `provider_reported`, never `frame`-verified.
- Schema keywords outside the verified subset raise `UnsupportedSchemaError`
  (strict by design; see translation table above).
- No local media inspection: the adapter does not run ffprobe; duration/size
  guards beyond `options.max_file_bytes` belong to the core/media milestone.
- YouTube URLs, Cloud Storage URIs, and inline base64 video are documented
  input modes but are NOT implemented (local file path only, per plan §8.1).

## Minimal working request

```python
import asyncio
from google import genai
from google.genai import types

client = genai.Client()  # reads GEMINI_API_KEY

uploaded = client.files.upload(file="clip.mp4")
while (s := client.files.get(name=uploaded.name).state.name) != "ACTIVE":
    assert s != "FAILED"
    await asyncio.sleep(2)

response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=[
        types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
        "List each visible event with its timestamp in seconds.",
    ],
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema={
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "timestamp_seconds": {"type": "number", "minimum": 0},
                            "description": {"type": "string"},
                        },
                        "required": ["timestamp_seconds", "description"],
                    },
                }
            },
            "required": ["events"],
        },
    ),
)
print(response.text)
print(response.usage_metadata)
client.files.delete(name=uploaded.name)
```

(Snippet assembled from the verified calls above; not executed — no API key
in this environment.)

## Integration-test procedure

```bash
SUVIX_RUN_INTEGRATION_TESTS=1 GEMINI_API_KEY=... \
    uv run pytest tests/integration/test_gemini.py -v
```

The test generates a 1.5s synthetic video with ffmpeg (`testsrc` +
`sine`), runs a real `native_video` extraction, and asserts parsed `data`,
integer `total_tokens` usage, and `provider_reported`-only evidence. It is
skipped unless both env vars are set, and fails clearly (skip reason) when
credentials are missing. Cost is minimal by construction (tiny fixture);
never run it against long videos without adjusting the fixture.
