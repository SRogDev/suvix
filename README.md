# Suvix

**Schema-guided video data extraction.** Suvix turns video into accurate, validated,
developer-defined structured data: you provide a video, a JSON Schema, instructions,
and an explicitly chosen provider — Suvix handles the extraction workflow, validation,
evidence references, and execution metadata.

> **Status: foundation (v0.1.0).** The repository scaffolding, packaging, and working
> docs are in place. The public extraction API (`Suvix.extract`) arrives in
> **Milestone 1** and providers in **Milestones 3/7**. See [STATUS.md](STATUS.md) for
> the live timeline. Nothing in this README describes behavior that does not exist yet.

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

## Target developer experience

This is the API the milestones are converging on (Milestone 1 implements it):

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

print(result.data)              # schema-validated extracted data
print(result.evidence)          # traceable timestamps / frame references
print(result.validation.valid)  # local validation outcome
print(result.usage)             # provider-reported usage and cost estimates
```

## Extraction strategies

- **native_video** — send the video through the provider's native video interface.
- **selected_frames** — Suvix samples a bounded set of frames with explicit timestamps.
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

Unit tests never require network access or provider keys. Real-provider integration
tests are opt-in (see the implementation plan, §17.3).

## Contributing

One PR = one logical change, squash-merged against `main`; never push directly to
`main`. Every significant change ships a README touch-up in the same PR. Python work
follows [uv](https://docs.astral.sh/uv/) + [Ruff](https://docs.astral.sh/ruff/);
TypeScript/UI (playground aside) prefers Biome. See [AGENTS.md](AGENTS.md).

## License

MIT — see [LICENSE](LICENSE).
