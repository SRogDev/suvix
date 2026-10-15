# TwelveLabs — §7.4 provider verification record

**Verification date:** 2026-10-15
**Adapter:** `src/suvix/adapters/twelvelabs.py` (`TwelveLabsExtractor`)
**SDK verified:** `twelvelabs` 1.3.6, introspected locally (class/method signatures,
type models, and `ApiError(status_code=...)` shape confirmed against the installed
package — primary evidence alongside the docs)
**API version:** v1.3 (`https://api.twelvelabs.io/v1.3`)
**Status of this record:** treat as time-sensitive; re-verify before M8 benchmarks.

## Official documentation (verified live 2026-10-15)

- Docs hub: https://docs.twelvelabs.io (v1.3)
- Sync analysis API reference: https://docs.twelvelabs.io/v1.3/api-reference/analyze-videos/analyze
- Analyze videos quickstart: https://docs.twelvelabs.io/v1.3/docs/get-started/quickstart/analyze-videos
- Analyze videos and images quickstart: https://docs.twelvelabs.io/v1.3/docs/get-started/quickstart/analyze-videos-and-images
- Async analysis (videos > 1h, segmentation): `POST /analyze/tasks` (referenced from
  the sync analysis page; not used by this adapter — see limitations)

## VERIFIED

- **Auth:** API key passed as the `x-api-key` header; the SDK takes it as
  `TwelveLabs(api_key=...)`. Keys are managed on the API Keys page; default expiry
  is 12 months (configurable). The adapter reads `TWELVELABS_API_KEY` from the
  environment unless `api_key=` is passed explicitly.
- **Workflow (upload → analyze):** assets are created with `client.assets.create`
  (`method="url"` for direct video URLs, `method="direct"` with file bytes for local
  files up to 200 MB; multipart uploads support larger files), then polled with
  `client.assets.retrieve(asset_id)` until `status == "ready"` (`"failed"` means the
  asset is unusable). Analysis needs no index: `client.analyze(...)` operates
  directly on the asset.
- **Sync analysis input modes:**
  - Video: 1 second – 1 hour, FFmpeg-supported formats, 360×360 to 5184×2160 px,
    aspect ratio between 1:1 and 2.4:1 (either orientation).
  - Images: **1–20 per request**, JPEG/PNG/WebP/GIF/BMP, ≤ 20 MB and ≤ 16,777,216 px
    each, **requires Pegasus 1.6** (any other model returns `parameter_invalid`).
    Exactly one of `video` / `image` per request; `prompt` (not `prompt_v2`) is
    required with images.
- **Models (verified enum in SDK 1.3.6):** `pegasus1.5` (documented API default),
  `pegasus1.6`. The adapter defaults to `pegasus1.5` for video and `pegasus1.6` for
  image input; an explicit `model=` is passed through verbatim.
- **Structured output:** verified — the sync endpoint accepts `response_format`,
  and **only the `json_schema` type is supported** for synchronous analysis. The
  adapter always requests
  `SyncResponseFormat(type="json_schema",
  json_schema=TextResponseFormatJsonSchema(name=..., strict=True, schema_=...))`.
- **Usage reporting:** verified — the non-streamed analyze response carries
  `usage` with `input_tokens` and `output_tokens` (SDK type `TokenUsage`;
  `usage.input_tokens` is also documented in the API reference). The adapter maps
  both when present and leaves `usage` empty otherwise — never zero-filled.
- **Timestamps:** verified — the API accepts `start_time`/`end_time` analysis
  windows (absolute seconds from the video's internal metadata), and Pegasus
  analysis output routinely contains timestamps. The adapter harvests numeric
  timestamp-like fields from the model's own JSON output as
  `EvidenceRef(ref_type="provider_reported")`, bounded to 64 refs. The provider
  does not disclose which frames it inspected (`exposes_sampled_frames=False`).
- **Deletion API:** verified at SDK level — `client.assets.delete(asset_id,
  force=None) -> None` exists in 1.3.6 (deleting a referenced asset returns
  409 unless `force=true`, per the platform's deletion safeguards — the adapter
  never indexes, so its assets are unreferenced). The adapter deletes every asset
  it created in a `finally` block, even when analysis fails; deletion failures are
  surfaced as warnings, never raised.
- **Free plan:** verified — 600 minutes (10 hours) per month shared across
  indexing, analysis, and segmentation. The endpoint is rate-limited (HTTP 429
  documented).

## UNVERIFIED / explicitly not claimed

- **Retention schedule:** no official retention/deletion-policy page was found
  during verification. Assets are deleted by the adapter after each run, but the
  platform-side purge timing after `DELETE` is **unverified** — do not assume
  immediate disappearance. Recorded here as a known unknown.
- **Async analysis** (`/analyze/tasks`: videos up to 2 h, segmentation with custom
  definitions): documented but **not implemented** by this adapter. Videos over
  1 hour are outside the sync path (`max_duration_seconds=3600` in capabilities);
  the core's media module owns duration gating.
- **Per-model image-analysis enforcement of `json_schema`:** the endpoint-level
  statement covers sync analysis generally; behavior with image input specifically
  is exercised only in the opt-in integration test.

## Credential configuration

| Variable            | Required | Purpose                  |
|---------------------|----------|--------------------------|
| `TWELVELABS_API_KEY` | yes     | `x-api-key` header value |

No other credentials. The key is never logged and is redacted from error messages.

## Supported models / strategies

- **Models:** `model=` is optional. `None` → documented default (`pegasus1.5` for
  video, `pegasus1.6` for images). An explicit value is never silently replaced;
  image input with any model other than `pegasus1.6` raises `UnsupportedStrategyError`
  (the API would reject it with `parameter_invalid`).
- **Strategies:** `native_video` (provider ingests the video) and `selected_frames`
  (each frame is uploaded as an image asset, ≤ 20, analyzed with Pegasus 1.6).
  Anything else raises `UnsupportedStrategyError`.

## Schema constraints

- The caller's JSON Schema is forwarded verbatim into `TextResponseFormatJsonSchema`
  (`strict=True`); nothing is translated or dropped. Local Draft 2020-12 validation
  of extracted data happens downstream (M6).
- With image input the schema travels in the same `response_format` object; the
  prompt is plain `prompt` (the API forbids `prompt_v2` alongside `image`).

## Media restrictions

- Local video files: direct upload ≤ 200 MB (`max_file_bytes=209_715_200` in
  capabilities). Larger local files need the multipart upload path (documented,
  not implemented — raises via provider error, not silently).
- Public URLs: up to 2 GB, must be direct links to raw media (video-hosting or
  cloud-storage share links are not supported by the platform).
- Sync analysis: 1 s – 1 h video. Image path: ≤ 20 images per request.

## Usage reporting

Mapped from the analyze response `usage`: `input_tokens`, `output_tokens`
(when present). Billing/credit accounting beyond per-call tokens is not reported
by this endpoint; the Free-plan 600 min/month quota is account-level.

## Known limitations

1. No frame-level evidence from the provider: Pegasus does not disclose which
   frames it inspected; timestamps in output are `provider_reported`, never
   verified by Suvix.
2. Selected-frames uploads one image asset per frame and polls each to `ready`;
   bounded by `asset_ready_timeout_seconds` (default 300 s) and the overall
   `per_call_timeout_seconds` from `ExtractionOptions` (default 120 s) — raise the
   latter for long videos.
3. No retries: one analyze call per `extract()`; the core owns retry/recovery.
4. Blocking SDK calls run via `asyncio.to_thread`; cancellation during the thread
   hop does not abort the in-flight HTTP request.
5. Retention after `DELETE` is unverified (see above).

## Minimal working request

```python
import asyncio
from suvix.adapters.twelvelabs import TwelveLabsExtractor
from suvix.adapters.base import AdapterRequest
from suvix.options import ExtractionOptions

async def main():
    ex = TwelveLabsExtractor()  # needs TWELVELABS_API_KEY
    req = AdapterRequest(
        video_path="clip.mp4",  # or "https://.../clip.mp4"
        schema={"type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"]},
        instructions="Summarize the video.",
        options=ExtractionOptions(per_call_timeout_seconds=300.0),
        strategy="native_video",
    )
    out = await ex.extract(req)
    print(out.data, out.usage, out.warnings)

asyncio.run(main())
```

## Integration-test procedure

`tests/integration/test_twelvelabs.py` is skipped by default. To run it (billable,
consumes Free-plan minutes; the fixture is a 2-second ffmpeg-rendered black MP4):

```bash
SUVIX_RUN_INTEGRATION_TESTS=1 TWELVELABS_API_KEY=tlk_... \
  uv run pytest tests/integration/test_twelvelabs.py -q
# optional: SUVIX_TWELVELABS_MODEL=pegasus1.6
```

Without the env flag the test skips; with the flag but no key it **fails loudly**
instead of silently passing. Requires `ffmpeg` for the fixture. Not run in CI.
Not executed during M7 development (recorded here as written-but-skipped).
