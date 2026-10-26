# Suvix

**Schema-guided video data extraction.** Suvix turns video into accurate, validated,
developer-defined structured data: you provide a video, a JSON Schema, instructions,
and an explicitly chosen provider — Suvix handles the extraction workflow, validation,
evidence references, and execution metadata.

> **Status: v0.1.0 released (Milestone 9 done).** The public API, core contracts,
> media layer, selected-frame extraction with bounded coarse-to-fine, full
> validation and selective recovery, three real providers (Gemini, OpenRouter,
> TwelveLabs), a local Streamlit playground, and the benchmark suite
> (baselines A–E) are implemented and tested — 343 tests. All provider
> capabilities are verified against official docs — see `docs/providers/`.
> See [STATUS.md](STATUS.md) for the live timeline and [CHANGELOG.md](CHANGELOG.md)
> for release notes. Nothing in this README describes behavior that does not
> exist yet.

## What Suvix is (and is not)

Suvix **is**: a small Python library (Python + uv) that orchestrates video → structured
data extraction with local JSON Schema validation, honest evidence references
(timestamps and real frame references), and observable usage/cost metadata.

Suvix **is not**: a cache, a database, a hosted service, an agent framework, a model
router, or a training pipeline. Persistent storage and caching belong to the calling
application — Suvix deliberately has none. See [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md)
for the full product contract.

## Installation

Requires Python ≥ 3.10. [`uv`](https://docs.astral.sh/uv/) is the package manager.

```bash
# Development install (from the repo root)
uv sync --extra dev

# Run the test suite
uv run pytest
```

Once published to PyPI, a consuming project installs the core with:

```bash
uv add suvix
```

and a provider-specific variant with, for example:

```bash
uv add "suvix[gemini]"
```

Provider SDKs are optional extras (`gemini`, `openrouter`, `twelvelabs`); the core
never imports them. The local Streamlit playground is another optional extra (`playground`).
Media processing shells out to the **optional external `ffmpeg`/`ffprobe` binaries** —
their absence raises a clear, actionable error instead of failing obscurely.

## Media layer (Milestone 2)

`suvix.media` is provider-neutral:

- `inspect_video(path)` — duration, dimensions, frame rate, codec, audio presence,
  file size, via ffprobe (async, offloaded to a thread).
- `extract_frames_at(path, timestamps)` — one JPEG per timestamp with accurate
  seeking; presentation timestamps are parsed from the container when possible
  (`pts_verified=True`) and clearly marked as requested-timestamp fallbacks otherwise.
  Temporary files are always cleaned up; results carry image bytes in memory.
- `suvix.sampling.uniform_timestamps(...)` — deterministic uniform sampling.
- `suvix.sampling.scene_change_timestamps(...)` / `make_scene_sampler(...)` —
  optional scene-change sampling (experiment branch): ffmpeg scene-transition
  candidates **merged with a uniform floor, never a replacement** for it,
  selected via `ExtractionOptions(sampling="scene_changes")`. A scene change
  is a visual transition, not a semantic event; no accuracy advantage over
  uniform sampling is claimed (no benchmark evidence exists either way).
- `suvix.media.split_into_segments(...)` / `to_global_seconds(...)` — segment math
  with correct offset handling for the coarse-to-fine workflow (Milestone 5).

## Providers

| Provider | Extra | Strategies | Structured output | Verification |
|---|---|---|---|---|
| Gemini | `suvix[gemini]` | native video, selected frames | Verified JSON Schema subset (see below) | [`docs/providers/gemini.md`](docs/providers/gemini.md) |
| OpenRouter | `suvix[openrouter]` | selected frames | `response_format` json_schema (strict) + `require_parameters`; strictness is per-endpoint, enforced by routing | [`docs/providers/openrouter.md`](docs/providers/openrouter.md) |
| TwelveLabs | `suvix[twelvelabs]` | native video, selected frames | `response_format` json_schema (sync analyze API); assets deleted after each call | [`docs/providers/twelvelabs.md`](docs/providers/twelvelabs.md) |

```python
from suvix import Suvix
from suvix.adapters.gemini import GeminiExtractor  # needs: uv add "suvix[gemini]"

extractor = GeminiExtractor()  # GEMINI_API_KEY env var
result = await Suvix().extract(
    video="sample.mp4",
    schema=Extraction.model_json_schema(),
    instructions="Identify each visible event of interest.",
    extractor=extractor,
)
```

Capability notes (all verified 2026-10-15 against official docs — nothing aspirational):
- Native video via the Files API; uploaded files are deleted after each extraction
  (auto-expiry 48h otherwise — see the provider doc for retention limits).
- Structured output supports a documented JSON Schema subset; unsupported keywords
  raise `UnsupportedSchemaError` naming the keyword instead of being silently dropped.
- Evidence timestamps are `provider_reported` — Gemini does not expose which frames
  it sampled, so Suvix does not claim frame-level verification.
- Usage comes from the provider's `usage_metadata`; missing values stay missing.

## Local playground (Milestone 4)

An optional Streamlit app for trying the library without building a frontend:

```bash
uv sync --extra playground --extra gemini   # gemini extra optional
uv run streamlit run playground/app.py
```

It uses **only the public API**: upload a video (nothing is sent anywhere until you
press *Run extraction*), enter instructions, edit the JSON Schema, pick a provider
(`fake` works offline; installed adapters light up automatically), choose a strategy,
tune the bounded options, and inspect the JSON / evidence / validation / usage /
execution tabs. Results export as JSON on explicit action.

Credentials come from environment variables (`GEMINI_API_KEY`, …) — shown as
set/not set, never displayed, logged, or exported. No accounts, no database, no
history. Uploads are capped and deleted after each run.

## Quickstart

Offline with the fake adapter (no network, no keys) — the whole pipeline,
validation, and recovery work end to end:

```python
import asyncio

from suvix import Suvix
from suvix.adapters.fake import FakeExtractor  # offline stand-in

extractor = FakeExtractor(script=[{"data": {"events": [
    {"timestamp_seconds": 1.5, "event_type": "goal"}]}}])

result = asyncio.run(Suvix().extract(
    video="sample.mp4",
    schema={
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "timestamp_seconds": {"type": "number"},
                        "event_type": {"type": "string"},
                    },
                    "required": ["timestamp_seconds", "event_type"],
                },
            }
        },
        "required": ["events"],
    },
    instructions="Identify each visible event of interest.",
    extractor=extractor,
))

print(result.data)              # schema-validated extracted data
print(result.evidence)          # traceable timestamps / frame references
print(result.validation.valid)  # local validation outcome
print(result.usage)             # provider-reported usage and cost basis
```

With a real provider (Gemini shown; needs `GEMINI_API_KEY`):

```python
from suvix.adapters.gemini import GeminiExtractor  # needs: uv add "suvix[gemini]"

extractor = GeminiExtractor()  # model="gemini-3.8-flash" by default
result = asyncio.run(Suvix().extract(
    video="sample.mp4",
    schema={...},               # your JSON Schema (Draft 2020-12)
    instructions="...",
    extractor=extractor,
))
```

See [`examples/`](examples/) for runnable scripts, including a custom adapter.

## Extraction strategies

- **native_video** — send the video through the provider's native video interface.
- **selected_frames** — Suvix inspects the video, samples a bounded set of frames
  with explicit timestamps (presentation timestamps parsed from the container when
  possible), and sends them to the adapter. Provider-referenced frame ids are
  validated against the local frame registry; unknown ids are dropped with a warning,
  never fabricated.
- **auto** — a small, explainable, rule-based planner picks between them (no LLM call,
  no silent provider switching; the choice and its reason are recorded in the result).
- **coarse-to-fine** — when `max_refinement_rounds > 0`, a bounded workflow runs one
  coarse pass (candidate intervals under an internal planning schema, never leaked
  into your data) followed by fine rounds that sample densely inside the expanded
  intervals. Total frames across all rounds never exceed `max_frames`. It is not
  exhaustive: the coarse pass can miss brief events, and the docs say so.

## Validation and recovery

Every extraction is validated **locally** — a provider's claim of structured output
never replaces it:

- **Structural** — the output must match your JSON Schema (Draft 2020-12).
- **Semantic (deterministic)** — time values must be finite, non-negative, ordered,
  and within the video duration (+ tolerance); `frame` references must resolve in
  the execution's frame registry. Code checks ranges, not whether the model truly
  saw the event.
- **Evidence** — timestamps within duration, frame ids verified, duplicates flagged.

When validation fails and recovery is enabled, Suvix makes a bounded number of
targeted repair calls (same provider, same model, same strategy — never a silent
switch), each naming the concrete issues. Exhaust the budget and you get a clear
`RecoveryExhaustedError`, never a silent empty result. `require_evidence=True`
rejects extractions that produce no evidence references.

No strategy is assumed cheaper or more accurate. The **benchmark suite**
(`suvix.evaluation`, `benchmarks/`) measures correctness, schema compliance,
timestamp accuracy (MAE **and** signed bias — drift is not noise), latency, and cost per strategy against direct-provider baselines — see [docs/benchmarking.md](docs/benchmarking.md). Seven synthetic tasks ship in `benchmarks/tasks/` (including a changing-count, a rapid-event, and a negative-control fixture), and an offline **oracle pack** (`tests/unit/test_oracle_benchmark.py`) proves the metrics recover known values exactly before any provider number is trusted; that is pipeline validation, not a provider accuracy claim. No pricing is registered by default, so cost figures stay unavailable until you register your own pricing or explicitly opt in to the one bundled verified snapshot (`suvix.evaluation.cost.load_verified_pricing_snapshot()` — Gemini prices verified 2026-10-23 against the official pricing page). Negative results are retained and reported.

## Known limitations

- **No cost/accuracy claims ship with this library.** Whether orchestration beats
  direct provider calls is answered only by running `suvix.evaluation` yourself;
  no pricing is registered by default (one opt-in verified snapshot aside).
- **Coarse-to-fine is not exhaustive.** The coarse pass can miss brief events;
  it narrows where to look, it does not guarantee finding everything.
- **Semantic validation checks ranges, not truth.** Timestamps are verified to be
  finite, ordered, and within the video — never that the model truly saw the event.
- **Provider-reported evidence is labeled, not verified.** For native video,
  Suvix does not know which frames the provider inspected; those refs stay
  `provider_reported`.
- **Structured-output strictness varies.** OpenRouter enforces it per endpoint,
  not per model; the adapter routes with `require_parameters` but cannot
  guarantee every endpoint.
- **TwelveLabs uploads leave the machine.** Assets are deleted after each call,
  but provider-side retention policies apply — see `docs/providers/twelvelabs.md`.
- **Benchmarks need keys and money.** The suite runs offline with fakes; real
  provider baselines make billable API calls and are opt-in.

## Documentation

- [SUVIX_PLAN.md](SUVIX_PLAN.md) — the full implementation specification.
- [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md) — project context for handoff to another AI.
- [docs/architecture.md](docs/architecture.md) — pipeline, adapter contract, boundaries.
- [docs/privacy.md](docs/privacy.md) — local processing, provider uploads, cleanup, no-cache.
- [docs/benchmarking.md](docs/benchmarking.md) — running the benchmark suite.
- [docs/providers/](docs/providers/) — per-provider verification records (§7.4).
- [docs/decisions/](docs/decisions/) — architecture decision records.
- [CHANGELOG.md](CHANGELOG.md) — release notes.
- Provider docs (`docs/providers/`) — added per provider, with verified capabilities only.

## Testing

```bash
uv sync --extra dev
uv run pytest
```

Unit tests never require network access or provider keys. Shared adapter contract
tests live in `tests/contract/` — every provider adapter (M3, M7) must pass them
against mocked SDK responses. Real-provider integration tests are opt-in (see the
implementation plan, §17.3).

Provider adapter unit tests skip cleanly when their optional extra is not
installed:

```bash
uv sync --extra dev          # core suite; provider tests skip without their extras
uv sync --extra dev --extra gemini --extra openrouter --extra twelvelabs --extra playground
uv run pytest                # full suite incl. mocked adapter tests
SUVIX_RUN_INTEGRATION_TESTS=1 GEMINI_API_KEY=... uv run pytest tests/integration
```

## Contributing

One PR = one logical change, squash-merged against `main`; never push directly to
`main`. Every significant change ships a README touch-up in the same PR. Python work
follows [uv](https://docs.astral.sh/uv/) + [Ruff](https://docs.astral.sh/ruff/) +
[mypy](https://mypy.readthedocs.io/) (`uv run ruff check src tests` and
`uv run mypy src/suvix` must both be clean);
TypeScript/UI (playground aside) prefers Biome. See [AGENTS.md](AGENTS.md).

## License

MIT — see [LICENSE](LICENSE).
