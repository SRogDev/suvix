# Suvix architecture

Source of truth: [SUVIX_PLAN.md](../SUVIX_PLAN.md) (§6). This document records
the pipeline and dependency boundaries as implemented.

## Pipeline (Milestone 1)

```
Developer Request
       |
       v
Normalize + validate inputs        (extraction._normalize_video, validation.validate_schema)
       |
       v
Adapter capability inspection      (extractor.capabilities)
       |
       v
Strategy selection                 (planner.select_strategy → StrategyDecision)
       |
       v
Provider extraction                (adapters/<provider>.py via VideoExtractor)
       |
       v
Normalize JSON output              (extraction._normalize_output; fences tolerated)
       |
       v
Structural + evidence-sanity checks (validation.validate_data, evidence.validate_evidence_timestamps)
       |
       v
Bounded selective recovery        (recovery.build_repair_request; same extractor/model/strategy)
       |
       v
ExtractionResult                   (data / evidence / validation / usage / execution)
```

`selected_frames` strategy: planned, not implemented until Milestone 5.
Requesting it raises `UnsupportedStrategyError` with that explanation —
Suvix never silently substitutes another strategy.

## Dependency direction

```
suvix.api (Suvix.extract)
   → suvix.extraction (pipeline)
      → suvix.contracts, suvix.options, suvix.errors      (no external deps beyond pydantic)
      → suvix.planner, suvix.validation, suvix.evidence,
        suvix.recovery, suvix.usage, suvix.pricing         (provider-neutral)
      → suvix.adapters.base (VideoExtractor Protocol)     (abstract only)
   → suvix.adapters.fake  (tests) / suvix.adapters.gemini (M3) / ...
```

Rules (enforced by review; M9 adds an import-lint check):

- Core modules never import provider SDKs or Streamlit.
- Validation has no provider dependencies.
- Media/sampling (M2) stay provider-neutral.
- Benchmarks (M8) and the playground (M4) consume only the public API.

## Contracts

- **Schema**: JSON Schema Draft 2020-12, validated locally with `jsonschema`
  before any provider call and after extraction.
- **Result**: `ExtractionResult{data, evidence, validation, usage, execution}` —
  business data is never mixed with execution metadata.
- **Evidence**: `EvidenceRef` with an honest `ref_type`
  (`provider_reported` | `frame` | `segment` | `description`).
- **Adapter**: `VideoExtractor` Protocol (`name`, `capabilities`, `extract`).
  Shared contract tests: `tests/contract/test_adapter_contract.py`.
- **Errors**: `SuvixError` base; provider failures under `ProviderRequestError`.
  Cancellation propagates as `asyncio.CancelledError`, never converted.

## Decisions

Frozen decisions: [decisions/ADR-001.md](decisions/ADR-001.md).
Per-adapter verification records: `docs/providers/<provider>.md` (M3, M7).
