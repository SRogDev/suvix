# Changelog

All notable changes to Suvix are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[SemVer](https://semver.org/). `main` stays linear — one squash-merged PR per
change (see `git log`).

## [0.1.0] — 2026-10-15

First public release. Schema-guided video data extraction: turn video into
accurate, validated, developer-defined structured data.

### Added

- **Public API** (`suvix.Suvix.extract`, async): video path + JSON Schema
  (Draft 2020-12) + instructions + explicit extractor → `ExtractionResult`
  with separated `data`, `evidence`, `validation`, `usage`, `execution`.
- **Adapter protocol** (`suvix.adapters.base.VideoExtractor`): capabilities
  discovery, `AdapterRequest`/`ProviderExtraction`, documented error mapping.
- **Strategies**: `native_video`, `selected_frames` (bounded local sampling
  with PTS-honest frame ids), `auto` (rule-based planner, no silent
  substitution), and bounded coarse-to-fine refinement
  (`max_refinement_rounds`, budget never exceeded across rounds).
- **Validation**: structural (JSON Schema) + deterministic semantic checks
  (finite/ordered/in-range timestamps, resolvable frame refs) + evidence
  validation. Bounded selective recovery (same provider/model/strategy).
- **Providers**: Gemini (`suvix[gemini]`, native video + selected frames),
  OpenRouter (`suvix[openrouter]`, selected frames), TwelveLabs
  (`suvix[twelvelabs]`, native video + selected frames). Capabilities verified
  against official docs — see `docs/providers/`.
- **Media layer**: ffprobe inspection, PTS-honest frame extraction,
  `FrameRegistry`, uniform sampling. ffmpeg/ffprobe are optional external
  dependencies with clear errors.
- **Playground**: local Streamlit app (`suvix[playground]`) — upload, schema
  editor, provider/strategy selection, 5 result tabs, JSON export.
- **Benchmark suite** (`suvix.evaluation`): baselines A–E (plan §16.2), 15
  pure metric functions, empty-by-design pricing registry, 3 hand-annotated
  tasks with regenerable synthetic fixtures. No cost/accuracy claims ship
  with the library.
- **Examples**: `examples/basic_extraction.py`, `examples/custom_extractor.py`.

### Verification

- 343 tests green (`uv run pytest`, default suite: no network, no API keys);
  `ruff check src tests` clean.
- Provider integration tests are opt-in (`SUVIX_RUN_INTEGRATION_TESTS=1`)
  and require real API keys — not run in CI.
- No paid API calls were made during development.

### Known limitations

See README "Known limitations". Headline items: coarse-to-fine is not
exhaustive; semantic validation checks ranges, not truth; provider-reported
evidence is labeled, not verified; no verified prices are bundled.
