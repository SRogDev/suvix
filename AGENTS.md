# AGENTS.md — Suvix working agreement

You are implementing **Suvix**, a schema-guided video data extraction library
(Python + uv). The full specification is [SUVIX_PLAN.md](SUVIX_PLAN.md) —
25 sections, 10 milestones (M0–M9). Read the plan sections relevant to your task
before writing code; this file is the working agreement, not a duplicate of the spec.

## Non-negotiable product constraints

- **No cache. No database. No persistence.** Temporary files for media processing
  or provider SDKs are allowed but must be cleaned up on success, failure, and
  cancellation; never expose temp paths in public results.
- **Explicit provider selection.** The developer chooses the provider and model.
  Never silently switch providers, models, strategies, or validation policies.
- **JSON Schema is the public schema contract.** Validate locally with `jsonschema`
  (Draft 2020-12); never invent provider capabilities or schema support.
- **Honest evidence.** Distinguish provider-reported timestamps from verified
  local frame references. Never fabricate frame identifiers.
- **No cost/accuracy claims without benchmark evidence.** Negative benchmark
  results are retained and reported.
- **Bounded execution.** Sampling, retries, refinement rounds, timeouts, and
  temp disk usage always have explicit limits with conservative defaults.

## Engineering discipline (user's standing rules)

- **uv only**: `uv venv`, deps in `pyproject.toml [project]`, `uv sync`, commit `uv.lock`.
  Never `python -m venv` + pip, never bare `requirements.txt`.
- **TDD with evidence**: write the failing test first, implement, refactor while
  green. Report RED→GREEN evidence, not just "tests pass".
- **Ruff** (configured in `pyproject.toml`) must be clean before delivery.
- **mypy** (configured in `pyproject.toml`): `uv run mypy src/suvix` must
  report no issues before delivery.
- **Reviewable units**: one focused change per commit; PRs are one logical change.
- **Conventional commits** (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, …).
- **PR workflow is absolute**: every change ships as a PR against `main`,
  one PR = one logical change, squash-merge, agents merge their own PRs,
  never push directly to `main`.
- **README rule**: every significant change ships a README touch-up in the same PR.
- No dead code, no TODOs masquerading as finished work. Stubs are labeled or not shipped.
- Never commit secrets (`.env` gitignored; provider keys via environment variables).

## Architecture boundaries

- `src/suvix/` is the library. Core modules must never import provider SDKs
  (they live behind `suvix/adapters/`) and must never import Streamlit.
- Dependency direction: public API → core contracts → adapter protocols;
  media/sampling utilities stay provider-neutral; validation has no provider deps.
- Async-first public API. Offload blocking media work (ffprobe/ffmpeg) to threads.
- Public result separates `data` (schema-defined) from `evidence`, `validation`,
  `usage`, and `execution` metadata.

## Test policy

- Default suite (`uv run pytest`) runs with **no network and no API keys**.
- Real-provider tests are opt-in via `SUVIX_RUN_INTEGRATION_TESTS=1`.
- Use fake adapters for deterministic orchestration tests.
- Every major public behavior gets a success case and its failure cases.

## Milestones

M0 audit → M1 contracts + fake adapter → M2 media → M3 Gemini → M4 playground →
M5 selected-frame + coarse-to-fine → M6 validation + recovery → M7 OpenRouter +
TwelveLabs → M8 benchmarks → M9 release. See [STATUS.md](STATUS.md) and the plan
(§22). Parallel agents only after M0/M1 contracts are stable.
