# STATUS.md — Suvix

Single source of truth for where the project stands. Updated with every milestone.

## Done

- **2026-10-15 — Milestone 0: repository audit & design freeze.**
  - Repo `SRogDev/suvix` created (public). Empty before foundation.
  - PyPI name `suvix` verified available (404 on 2026-10-15).
  - Toolchain: Python 3.12.3, uv 0.12.19 (`~/.local/bin/uv`), ffmpeg/ffprobe present
    locally (treated as optional external dependency with graceful error).
  - Current SDK versions recorded (2026-10-15): `google-genai` 2.31.0,
    `openai` 3.31.0, `twelvelabs` 1.3.6, `streamlit` 1.66.0, `jsonschema` 4.26.0,
    `pydantic` 2.14.1, `httpx` 0.28.1.
  - Provider doc hubs verified live (2026-10-15): ai.google.dev/gemini-api/docs,
    openrouter.ai/docs, docs.twelvelabs.io.
  - Design freeze decisions recorded in `docs/decisions/ADR-001.md`.
  - Target: `requires-python >= 3.10`; src/ layout; hatchling build.

- **2026-10-15 — PR #1: foundation (this change).**
  - `pyproject.toml` (uv, src layout, optional extras: gemini / openrouter /
    twelvelabs / playground / dev), `uv.lock`, `.python-version`, `.gitignore`.
  - `src/suvix/__init__.py` (version only; public API lands in M1).
  - `README.md`, `LICENSE` (MIT — Roger's portfolio default, changeable),
    `AGENTS.md`, `STATUS.md`, `docs/PROJECT_BRIEF.md`, `docs/decisions/ADR-001.md`.
  - `SUVIX_PLAN.md` — the full implementation specification (source of truth).
  - `tests/test_import.py` — foundation test (TDD RED→GREEN evidence below).

- **2026-10-15 — PR #2: Milestone 1 — core contracts + fake adapter.**
  - `src/suvix/`: `api.py` (`Suvix.extract`), `contracts.py` (ExtractionResult /
    EvidenceRef / ValidationReport / UsageReport / ExecutionMetadata),
    `options.py` (ExtractionOptions, conservative defaults), `errors.py`
    (SuvixError hierarchy), `planner.py` (rule-based auto strategy planner),
    `extraction.py` (pipeline), `validation.py` (Draft 2020-12 local validation),
    `recovery.py` (bounded repair, same extractor/model/strategy), `evidence.py`
    (timestamp sanity), `usage.py`, `pricing.py`, `adapters/base.py`
    (VideoExtractor Protocol + ExtractorCapabilities), `adapters/fake.py`
    (scripted offline test double).
  - `docs/architecture.md` — pipeline + dependency boundaries as built.
  - 60 tests green, ruff clean; README example executed against the fake adapter.

- **2026-10-15 — PR #3: Milestone 2 — media metadata + selected-frame foundation.**
  - `src/suvix/media/`: `metadata.py` (`inspect_video` via ffprobe),
    `frames.py` (`extract_frames_at`, `SampledFrame`, `FrameRegistry`,
    PTS-honest timestamps), `segments.py` (segment math + offsets).
  - `src/suvix/sampling/`: `uniform.py` (deterministic), `base.py` (Sampler protocol).
  - 105 tests green (incl. real VFR clip test), ruff clean.
- **2026-10-15 — PR #4: Milestone 3 — first real provider: Gemini.**
  - `src/suvix/adapters/gemini.py`: `GeminiExtractor` (Files API upload +
    bounded ACTIVE poll + `generate_content` with translated
    `response_json_schema`; selected frames as labeled multi-image parts;
    upload deleted in `finally`; lazy SDK import; key never logged).
  - `docs/providers/gemini.md`: §7.4 verification record (VERIFIED vs
    UNVERIFIED separated; default model `gemini-3.8-flash` per current docs).
  - Shared contract tests pass (mocked SDK); 51 adapter unit tests; 1 opt-in
    integration test (`SUVIX_RUN_INTEGRATION_TESTS=1` + `GEMINI_API_KEY`).
  - 156 tests green with the gemini extra (105 + 3 skips without it), ruff clean.
  - Integration note: provider test modules now `importorskip` their SDK so the
    default `--extra dev` suite stays green without optional extras.

- **2026-10-15 — PR #5: Milestone 4 — end-to-end Streamlit playground.**
  - `playground/app.py` (public API only): upload (no auto provider call),
    instructions, schema editor, provider radio (fake always; installed adapters
    light up automatically — Gemini verified live), strategy radio with the M5
    gap labeled, bounded options, 5 result tabs, explicit JSON export.
  - Secrets via env vars (set/not set only); uploads capped + deleted per run.
  - Headless AppTest verified: boot, provider discovery, full fake-adapter run
    (valid data, 5 tabs, validation passed). 159 tests green, ruff clean.

- **2026-10-15 — PR #6: Milestone 5 — selected-frame extraction + coarse-to-fine.**
  - `src/suvix/extraction.py`: real `selected_frames` branch — `inspect_video`
    → bounded `uniform_timestamps` → `extract_frames_at` with a `FrameRegistry`
    → single pass or bounded coarse-to-fine; provider frame-ids validated
    against the registry (unknown → dropped + warning); shared `_finalize`
    tail (native path behavior unchanged).
  - `src/suvix/sampling/coarse_to_fine.py`: one coarse pass (internal
    `COARSE_SCHEMA`, never leaked) + up to `max_refinement_rounds` fine rounds;
    interval validation/expansion/merging, no re-sampling, total frames ≤
    `max_frames`; documented non-exhaustiveness.
  - 178 tests green (19 new, all against REAL ffmpeg media — incl. a 40s clip
    for multi-round refinement), ruff clean.

- **2026-10-15 — PR #7: Milestone 6 — validation + selective recovery.**
  - `validation.py`: `SemanticContext`, `iter_time_fields`, `validate_semantics`
    (finite/non-negative/ordered time values, duration + tolerance bounds,
    resolvable frame refs; ranges only, never semantic truth).
  - `evidence.py`: `validate_evidence` (duration bounds, frame resolution,
    duplicate warnings).
  - `recovery.py`: `classify_issues`; `is_recoverable` no longer burns budget
    on warnings-only reports; repair instructions grouped by field with a
    no-fabrication line.
  - Pipeline wiring (integrator): semantic + full evidence validation run in
    `_validate_extraction` with media context (incl. coarse-to-fine rounds);
    `require_evidence=True` now raises `MissingEvidenceError` instead of being
    silently ignored.
  - 216 tests green (38 new), ruff clean.

- **2026-10-15 — PR #8: Milestone 7 — OpenRouter + TwelveLabs adapters.**
  - `adapters/openrouter.py`: `OpenRouterExtractor` (model required, explicit;
    `selected_frames` only — native video refused loudly since support varies
    per endpoint behind the gateway); frames as `image_url` data URIs;
    strict `response_format` json_schema + `require_parameters` routing;
    evidence = one `frame` ref per sent frame; usage incl. `cost` as reported;
    key redaction in error mapping.
  - `adapters/twelvelabs.py`: `TwelveLabsExtractor` (native video + selected
    frames): upload → bounded poll until `ready` → sync analyze (Pegasus) with
    `json_schema` response format → asset deleted in `finally`; image path
    ≤20 images, Pegasus 1.6 enforced; evidence honestly `provider_reported`;
    `structured_output=True` verified in SDK 1.3.6 (better than the plan's
    expectation).
  - `docs/providers/openrouter.md`, `docs/providers/twelvelabs.md`: §7.4
    verification records (doc URLs, SDK versions, VERIFIED vs UNVERIFIED).
  - 274 tests green (58 new, all SDK-mocked; 2 integrator env-robustness fixes
    by integrator), ruff clean. No paid API calls; integration tests opt-in
    and skipped (no keys on this machine).

- **2026-10-15 — PR #9: Milestone 8 — benchmark suite.**
  - `src/suvix/evaluation/`: 15 pure metric functions (`metrics.py`; rates are
    `float | None`, never zeroed), baseline runner (`runner.py`: A–E, §16.2),
    pricing registry (`cost.py`: empty by design — no invented prices).
  - Baselines C/D/E wired for real at integration (builder shipped them as
    "unavailable" placeholders): C = single-pass selected frames
    (`max_refinement_rounds=0`, isolated from D), D = coarse-to-fine
    (`max_refinement_rounds=2`), E = locally sampled frames submitted directly
    to the adapter (image-input mirror of A; honest skip without image input).
    `_run_a`'s measurement tail factored into a shared `_wrap_direct_extraction`.
  - `benchmarks/tasks/*.json` (3 hand-annotated tasks), `benchmarks/fixtures/`
    `generate.py` (videos gitignored; sha256-verified reproducibility),
    `docs/benchmarking.md`.
  - Integrator smoke run (real generated fixture, scripted fakes): all 5
    baselines green — A:1req/0f, B:1req/0f, C:1req/2f, D:2req/5f, E:1req/2f;
    f1=1.0 everywhere (perfect fakes validate the harness, not providers).
    This caught a real confound: C initially inherited the default
    `max_refinement_rounds=2`, making it identical to D — fixed and pinned.
  - 343 tests green (69 new), ruff clean.

- **2026-10-15 — PR #10: Milestone 9 — release readiness (v0.1.0).**
  - Public API review: `suvix/__init__.py` exports `Suvix`, `ExtractionOptions`,
    result contracts, and the full error hierarchy; adapters stay behind
    `suvix.adapters.*`; `suvix.evaluation` is a separate subpackage.
  - Docs: README quickstart rewritten (was stale, spoke of M3/M7 as future);
    new "Known limitations" section (§21.1); new `docs/privacy.md` (§21.4);
    CHANGELOG.md with v0.1.0 release notes.
  - Packaging: `uv build` → wheel + sdist; clean-env venv installs the wheel
    and runs `examples/basic_extraction.py`; `suvix[gemini]` extra resolves
    and installs from the wheel (google-genai present, adapter importable).
  - Examples: `examples/basic_extraction.py` (offline fake), `examples/`
    `custom_extractor.py` (hand-written `VideoExtractor`) — both run.
  - Security: no `print()` in library code; API keys redacted from all mapped
    error text (uniform `_redact` added to the Gemini adapter to match the
    other two); keys via arg-or-env only.
  - License: MIT file present, matches pyproject.
  - CI: `.github/workflows/ci.yml` prepared but NOT pushed — the automation
    credential lacks the `workflows` scope (GitHub API refuses). Roger must
    push it with a full-scope token or local git remote (instructions in the
    file header).
  - 343 tests green, ruff clean.

## Experiment branches (local, unmerged)

- **2026-10-23 — `feat/oracle-benchmark-pack`** (based on v0.1.0 `main`,
  local only): proves the benchmark machinery tells the truth + research-
  justified metric extensions (TGB matching-standard sensitivity,
  Video-MME-V2 two-axis reporting, TVBench shortcut-defeating tasks,
  Charades-STA tolerance reporting).
  - Metrics: `timestamp_bias` (signed mean error over greedy matched
    pairs — drift vs noise, which MAE cannot distinguish) and
    `event_metrics_by_tolerance` (P/R/F1 sweep over tolerances), exported
    from `suvix.evaluation`; runner records `timestamp_bias` per run.
    Two-axis reporting needed no new field: runner results already record
    `provider_requests` / `sampled_frames` / `latency_seconds` /
    `estimated_cost_usd` per run — documented in `docs/benchmarking.md`.
  - Fixtures: `changing_counts` (2→4 squares at t=4s), `changing_text`
    (ALPHA→BRAVO), `rapid_events` (0.3s flashes ~1s apart, 0.5s
    tolerance), `negative_control` (empty expected events). Expectations
    from generation parameters only; pixel-verified frames
    (5000 vs 10000 red px); pre-existing fixture sha256s reproduce
    exactly on regeneration.
  - Oracle pack (`tests/unit/test_oracle_benchmark.py`): test-local
    oracle adapter through the real runner recovers known values exactly
    (perfect → P=R=F1=1, MAE=bias=0, schema=1; +0.3s jitter → MAE=bias=
    +0.3; drop-half → recall 0.5; duplicate-all → dup rate 0.5; +2
    hallucinations → precision 2/4; missing required field →
    schema_pass_rate 0.5 over 2 results). Greedy-vs-optimal divergence
    measured: greedy recall 0.5 vs brute-force-optimal 1.0 on the crafted
    case — documented as a known matching limitation.
  - Evidence: RED (20 failed / 54 passed on the two target test files)
    → GREEN; full suite 367 passed, 3 skipped with all provider extras
    (343 v0.1.0 baseline + 24 new; with `--extra dev` only: 316 passed,
    5 skipped — the 2 Gemini modules skip at import without the SDK).
    Ruff clean. **Offline pipeline validation only — no provider
    accuracy is claimed anywhere.**

## In progress

All 10 milestones complete. v0.1.0 released on `main`.

## Experiment branches (local, unmerged — 2026-10-23 improvement experiment)

- `feat/oracle-benchmark-pack` — offline proof that the benchmark machinery
  tells the truth: `timestamp_bias` (signed drift diagnostic) and
  `event_metrics_by_tolerance` (tolerance sensitivity) metrics; four new
  synthetic ground-truth tasks (`changing_counts`, `changing_text`,
  `rapid_events`, `negative_control`); an oracle-adapter test suite that
  asserts the metrics recover exactly known values under controlled noise;
  the greedy-vs-optimal matching divergence measured and documented in
  `docs/benchmarking.md`; run entries now record `frames_sampled`
  (two-axis reporting). Research basis: `docs/research/EXPERIMENT_RESEARCH.md`
  (TGB, Video-MME-V2, TVBench). Validates the evaluation pipeline only —
  no provider accuracy claim. Local branch only (GitHub suspended); PR-ready.

## Pending Roger's action (not blocking the release)

- **CI workflow**: `.github/workflows/ci.yml` is written but could not be
  pushed — the automation credential lacks the `workflows` scope. Push it
  with a full-scope token or from a local git remote (instructions in the
  file header).
- **Provider API keys**: `GEMINI_API_KEY`, `OPENROUTER_API_KEY`,
  `TWELVELABS_API_KEY` — integration tests (`SUVIX_RUN_INTEGRATION_TESTS=1`)
  and real benchmark runs need them; no paid calls were made during development.
- **PyPI publish**: `uv build` artifacts verified locally; the
  `uv add "suvix[gemini]"` downstream command can only be verified after
  publication.
- **Real benchmark runs**: the suite is ready (baselines A–E); running it
  against real providers is the experiment that answers the central research
  question.

## Next (milestones)

| # | Milestone | PR | Status |
|---|-----------|----|--------|
| 1 | Core contracts + fake adapter | #2 | ✅ done 2026-10-15 |
| 2 | Media metadata + selected-frame foundation | #3 | ✅ done 2026-10-15 |
| 3 | First real provider: Gemini | #4 | ✅ done 2026-10-15 |
| 4 | End-to-end Streamlit playground | #5 | ✅ done 2026-10-15 |
| 5 | Selected-frame extraction + coarse-to-fine | #6 | ✅ done 2026-10-15 |
| 6 | Validation + selective recovery | #7 | ✅ done 2026-10-15 |
| 7 | OpenRouter + TwelveLabs adapters | #8 | ✅ done 2026-10-15 |
| 8 | Benchmark suite | #9 | ✅ done 2026-10-15 |
| 9 | Release readiness | #10 | ✅ done 2026-10-15 |

Full milestone definitions: [SUVIX_PLAN.md](SUVIX_PLAN.md) §22.
Definition of done: [SUVIX_PLAN.md](SUVIX_PLAN.md) §24.

## Verification evidence (PR #10 — Milestone 9)

- `uv run pytest` → 343 passed, 3 skipped (opt-in provider integration tests).
- `uv run ruff check src tests` → clean.
- `uv build` → `dist/suvix-0.1.0.tar.gz` + `dist/suvix-0.1.0-py3-none-any.whl`.
- Clean venv: wheel installs; `import suvix` OK; `examples/basic_extraction.py`
  and `examples/custom_extractor.py` run end to end.
- `suvix[gemini]` extra installs from the wheel in a clean venv
  (google-genai present, adapter importable).
- Security grep: no `print()` in `src/`; no SDK imports outside
  `src/suvix/adapters/`; API-key redaction uniform across all three adapters.
- §24 Definition of Done reviewed item by item — see the coordinator's final
  report for the two items that need Roger's action (CI push, PyPI publish)
  and the one that needs keys + budget (live provider verification).

## Verification evidence (PR #9 — Milestone 8)

- `uv run pytest` → 343 passed, 3 skipped (274 baseline + 69 new: metrics +
  runner; skips are the 3 opt-in provider integration tests).
- `uv run ruff check src tests` → clean.
- Builder's tests: metrics suite copied as-is (pure functions); C/D/E
  "unavailable" tests rewritten for real behavior (real 40s clip fixture).
- Integrator end-to-end smoke (real generated fixtures, scripted fakes):
  A–E all green with differentiated request/frame counts (see Done entry).
- Fixture reproducibility: regenerated `temporal_flashes.mp4` sha256 matches
  the task JSON's recorded hash.

## Verification evidence (PR #8 — Milestone 7)

- `uv run pytest` → 274 passed, 3 skipped (216 baseline + 58 new; skips are the
  three opt-in provider integration tests — no keys on this machine, no paid
  calls made).
- `uv run ruff check src tests` → clean (2 import-sort issues fixed at integration).
- Integrator fixes: the two `test_missing_api_key_raises_config_error` tests now
  patch the fake SDK first — the adapter checks the SDK before the key, so on a
  bare env (no optional SDKs) the missing-SDK error fired instead of the
  missing-key error. Same adapter behavior, deterministic tests.
- Test-import convention: `tests/` is now a package (`__init__.py` per dir);
  existing bare cross-test imports converted to `tests.unit.*` / `tests.contract.*`.
- §7.4 provider records verified in `docs/providers/{openrouter,twelvelabs}.md`.

## Verification evidence (PR #7 — Milestone 6)

- `uv run pytest` → 216 passed, 1 skipped (178 baseline + 38 new: 36 builder
  unit tests + 2 integrator `require_evidence` pipeline tests).
- `uv run ruff check src tests` → clean.
- TDD: RED (collection ImportErrors on the new names) → GREEN, no regressions.
- Wiring verified: semantic/out-of-range evidence issues now fail validation
  and can trigger bounded recovery; warnings-only reports skip recovery.

## Verification evidence (PR #6 — Milestone 5)

- `uv run pytest` → 178 passed, 1 skipped (159 baseline + 19 new, all against
  REAL ffmpeg media: 4s clip for single-pass, module-scoped 40s clip for
  multi-round coarse-to-fine).
- `uv run ruff check src tests` → clean.
- Builder's stub-based tests were rewritten for real media at integration.

## Verification evidence (PR #5 — Milestone 4)

- `uv run pytest` → 159 passed, 1 skipped; `ruff check src tests playground`
  → clean.
- Headless AppTest (integrator): clean boot, provider discovery (fake + gemini
  lit, others honestly "not installed"), full fake-adapter run → 5 tabs, valid
  data, validation passed, stages recorded.

## Verification evidence (PR #4 — Milestone 3)

- `uv run pytest` → 156 passed, 1 skipped (gemini extra installed); 105 passed,
  3 skipped without it (provider test modules `importorskip` their SDK).
- `uv run ruff check src tests` → clean.
- TDD: RED (3 collection errors) → GREEN; one real bug caught (schema property
  names misclassified as keywords → special-cased `properties` keys).
- `docs/providers/gemini.md`: §7.4 verification record, VERIFIED vs UNVERIFIED
  separated. No paid API calls; integration test written but skipped (no keys here).

## Verification evidence (PR #3 — Milestone 2)

- `uv run pytest` → 105 passed (60 baseline + 45 new), incl. a real VFR clip test
  (2s@30fps + 2s@10fps; container claims 30fps; parsed PTS asserted at t=2.5).
- `uv run ruff check src tests` → clean.
- ffmpeg/ffprobe-dependent tests skip cleanly when the binaries are absent.
- TDD evidence per builder: RED (collection errors) → GREEN; one real behavioral
  failure root-caused (`-v error` suppresses showinfo; fixed with `-copyts`).
- No network, no API keys. No scene-change sampling, no remote URLs, no caching.

## Verification evidence (PR #2 — Milestone 1)

- `uv run pytest` → 60 passed (was 8 collection errors before implementation: RED→GREEN).
- `uv run ruff check src tests` → clean.
- README example (fake adapter) executed: returns schema-valid data,
  `validation.valid=True`, strategy `native_video`, 1 provider call.
- No network, no API keys used. `selected_frames` raises documented
  `UnsupportedStrategyError` (gap labeled for M5, not hidden).

## Verification evidence (PR #1)

- `uv sync --extra dev` → resolved + installed (incl. `uv.lock` committed).
- `uv run pytest` → 1 passed (test_import.py).
- `uv run ruff check src tests` → clean.
- `uv build` → sdist + wheel built (foundation package).
