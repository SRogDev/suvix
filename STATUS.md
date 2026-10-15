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

## In progress

**Milestone 6: validation + selective recovery** (PR #7) — builder done; integrating next.

## Next (milestones)

| # | Milestone | PR | Status |
|---|-----------|----|--------|
| 1 | Core contracts + fake adapter | #2 | ✅ done 2026-10-15 |
| 2 | Media metadata + selected-frame foundation | #3 | ✅ done 2026-10-15 |
| 3 | First real provider: Gemini | #4 | ✅ done 2026-10-15 |
| 4 | End-to-end Streamlit playground | #5 | ✅ done 2026-10-15 |
| 5 | Selected-frame extraction + coarse-to-fine | #6 | ✅ done 2026-10-15 |
| 6 | Validation + selective recovery | #7 | next |
| 7 | OpenRouter + TwelveLabs adapters | #8 |
| 8 | Benchmark suite | #9 |
| 9 | Release readiness | #10 |

Full milestone definitions: [SUVIX_PLAN.md](SUVIX_PLAN.md) §22.
Definition of done: [SUVIX_PLAN.md](SUVIX_PLAN.md) §24.

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
