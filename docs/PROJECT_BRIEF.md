# PROJECT BRIEF — Suvix

Full project context in one file. Written to be handed to another AI for
planning, ideation, or implementation. Last updated: 2026-10-15.

## One-liner

Suvix is an open-source Python library that converts video into accurate,
validated, developer-defined structured data — the developer provides the video,
a JSON Schema, instructions, and an explicitly chosen provider; Suvix handles
the extraction workflow, validation, evidence references, and execution metadata.

## The bet (central research question)

Can an orchestration/extraction layer improve quality, cost, latency, or developer
experience of video→structured-data tasks compared with calling video-capable
models directly? **The answer must come from benchmarks, never from assumptions.**
Suvix does not assume frame sampling is cheaper, native video is more accurate,
or multi-stage workflows beat single model calls. The architecture must support
strategy comparisons and make trade-offs measurable.

## Product constraints (frozen in Milestone 0)

1. Schema first — the developer defines the data structure (JSON Schema).
2. Explicit provider selection — the developer chooses provider + model; Suvix
   never silently replaces that choice.
3. Evidence-aware output — traceable timestamps and frame references where the
   strategy supports them; provider-reported vs. verified evidence is distinguished.
4. Provider-neutral core — provider specifics stay inside adapters.
5. Bounded execution — sampling, retries, file size, duration all have explicit limits.
6. Honest uncertainty — missing information is never fabricated.
7. Measurable performance — accuracy, latency, usage, cost are observable.
8. No implicit persistence — **no cache, no database, no storage. Ever.** The
   application developer owns caching and retention.
9. Low integration friction — fits into an existing Python app without new infrastructure.

## Non-goals (explicit)

No persistent caching, database, hosted service, queue/workers, automatic model
router, fine-tuning, custom vision model, embeddings/vectors, agent framework,
LLM-based planner, video editor, web app, auth/billing, automatic cost
optimization without evidence, or proprietary storage formats.

## MVP task families

1. Temporal events and actions (event type, start/end timestamps, description, evidence).
2. Objects, counts, and visible attributes.
3. Visible text and on-screen information.

## Target developer experience

```python
from pydantic import BaseModel
from suvix import Suvix
from suvix.adapters.gemini import GeminiExtractor

class Event(BaseModel):
    timestamp_seconds: float
    event_type: str
    evidence: str

class Extraction(BaseModel):
    events: list[Event]

extractor = GeminiExtractor()
suvix = Suvix()
result = await suvix.extract(
    video="sample.mp4",
    schema=Extraction.model_json_schema(),
    instructions="Identify each visible event of interest.",
    extractor=extractor,
)
print(result.data, result.evidence, result.validation.valid, result.usage)
```

Result contract: `data` (schema-defined) is separate from `evidence`, `validation`,
`usage`, and `execution` metadata.

## Architecture

Pipeline: request + schema validation → adapter capability inspection → strategy
selection (`auto` / `native_video` / `selected_frames`) → video/frame preparation →
provider extraction → output normalization → structural + semantic validation →
bounded selective recovery → final result → temp-resource cleanup.

- Core orchestration depends on an abstract adapter protocol (`VideoExtractor`).
- Adapters in order: **Gemini** (official `google-genai` SDK), **OpenRouter**
  (OpenAI-compatible API), **TwelveLabs** (native API/SDK).
- Media: ffprobe-based metadata, deterministic uniform frame sampling first,
  precise timestamps (float seconds, actual presentation timestamps where available).
- Validation: local structural validation against the original schema plus
  deterministic semantic checks (timestamps in range, frame refs valid, intervals sane).
- Recovery: selective, bounded, budget-counted; never switches providers silently.
- Strategies: `native_video`, `selected_frames`, `auto` (small rule-based planner,
  no LLM), `coarse_to_fine` (bounded, optional).
- Playground: optional local Streamlit app (`playground` extra), never imported by core.

## Benchmarking

The benchmark suite compares: (A) direct native-provider call, (B) Suvix native
mode, (C) Suvix selected-frame mode, (D) Suvix coarse-to-fine, (E) optional direct
selected-frame call — same video, same model where possible, same instructions,
same schema, same criteria. Metrics: structural quality (parse/schema pass rates),
semantic quality (precision/recall/F1, timestamp error), operational (latency,
request counts, frames), economic (provider usage, billed cost where available,
clearly-labeled estimates). Negative results are retained and reported.

## Stack and repo conventions

- Python ≥ 3.10, **uv only** (`uv sync`, deps in `pyproject.toml`, `uv.lock` committed).
- src/ layout, hatchling build. Runtime deps minimal: `pydantic`, `jsonschema`.
  Provider SDKs and Streamlit are optional extras.
- Ruff lint clean; pytest (asyncio auto mode); integration tests opt-in
  (`SUVIX_RUN_INTEGRATION_TESTS=1`).
- GitHub: `SRogDev/suvix` (public). PR workflow absolute: one PR = one logical
  change, squash-merge, agents merge their own PRs, never push directly to `main`.
- README ships a touch-up with every significant change (Roger's rule).
- Milestones: M0 foundation → M1 contracts → M2 media → M3 Gemini → M4 playground
  → M5 selected-frame/coarse-to-fine → M6 validation/recovery → M7 OpenRouter/TwelveLabs
  → M8 benchmarks → M9 release.

## Key files

- `SUVIX_PLAN.md` — the full implementation specification (25 sections).
- `STATUS.md` — live timeline of done / in progress / next.
- `AGENTS.md` — working agreement for coding agents.
- `docs/decisions/` — architecture decision records.
- Full spec: `~/workspace/suvix/SUVIX_PLAN.md` (local workspace copy).
