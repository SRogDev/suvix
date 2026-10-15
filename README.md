# Suvix

**Schema-guided video data extraction.** Suvix turns video into accurate, validated,
developer-defined structured data: you provide a video, a JSON Schema, instructions,
and an explicitly chosen provider — Suvix handles the extraction workflow, validation,
evidence references, and execution metadata.

> **Status: Milestone 3 done (v0.1.0).** The public API, core contracts, media layer,
> and the **first real provider (Gemini)** are implemented and tested — 156 tests
> (51 for the Gemini adapter, mocked; 1 opt-in integration test requiring
> `SUVIX_RUN_INTEGRATION_TESTS=1` and `GEMINI_API_KEY`). Provider capabilities are
> verified against official docs, not assumed — see `docs/providers/gemini.md`.
> OpenRouter/TwelveLabs arrive in **Milestone 7**, selected-frame extraction in
> **Milestone 5**. See [STATUS.md](STATUS.md) for the live timeline. Nothing in this
> README describes behavior that does not exist yet.

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
- `suvix.media.split_into_segments(...)` / `to_global_seconds(...)` — segment math
  with correct offset handling for the coarse-to-fine workflow (Milestone 5).

## Providers

| Provider | Extra | Strategies | Structured output | Verification |
|---|---|---|---|---|
| Gemini | `suvix[gemini]` | native video, selected frames | Verified JSON Schema subset (see below) | [`docs/providers/gemini.md`](docs/providers/gemini.md) |
| OpenRouter | `suvix[openrouter]` | Milestone 7 | — | — |
| TwelveLabs | `suvix[twelvelabs]` | Milestone 7 | — | — |

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

## Developer experience (Milestone 1 — works today with the fake adapter)

The public API is implemented. Real provider adapters land in Milestones 3/7;
until then, `suvix.adapters.fake.FakeExtractor` exercises the whole pipeline
offline with scripted responses:

```python
import asyncio
from pydantic import BaseModel

from suvix import Suvix
from suvix.adapters.fake import FakeExtractor  # offline stand-in; real adapters in M3/M7


class Event(BaseModel):
    timestamp_seconds: float
    event_type: str
    evidence: str


class Extraction(BaseModel):
    events: list[Event]


extractor = FakeExtractor(script=[{"data": {"events": [
    {"timestamp_seconds": 1.5, "event_type": "goal", "evidence": "crowd roars"}]}}])
suvix = Suvix()

result = asyncio.run(suvix.extract(
    video="sample.mp4",
    schema=Extraction.model_json_schema(),
    instructions="Identify each visible event of interest.",
    extractor=extractor,
))

print(result.data)              # schema-validated extracted data
print(result.evidence)          # traceable timestamps / frame references
print(result.validation.valid)  # local validation outcome
print(result.usage)             # provider-reported usage and cost estimates
```

## Extraction strategies

- **native_video** — send the video through the provider's native video interface.
- **selected_frames** — planned for Milestone 5. Requesting it today raises a
  documented `UnsupportedStrategyError`; Suvix will not silently substitute another
  strategy.
- **auto** — a small, explainable, rule-based planner picks between them (no LLM call,
  no silent provider switching; the choice and its reason are recorded in the result).
- **coarse-to-fine** (Milestone 5) — bounded refinement over candidate intervals.

No strategy is assumed cheaper or more accurate. The **benchmark suite (Milestone 8)**
measures correctness, schema compliance, timestamp accuracy, latency, and cost per
strategy against direct-provider baselines, and negative results are reported.

## Documentation

- [SUVIX_PLAN.md](SUVIX_PLAN.md) — the full implementation specification.
- [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md) — project context for handoff to another AI.
- [docs/decisions/](docs/decisions/) — architecture decision records.
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
follows [uv](https://docs.astral.sh/uv/) + [Ruff](https://docs.astral.sh/ruff/);
TypeScript/UI (playground aside) prefers Biome. See [AGENTS.md](AGENTS.md).

## License

MIT — see [LICENSE](LICENSE).
