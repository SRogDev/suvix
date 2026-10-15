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

## In progress

Nothing yet — next is **Milestone 1: core contracts + fake adapter** (PR #2).

## Next (milestones)

| # | Milestone | PR |
|---|-----------|----|
| 1 | Core contracts + fake adapter | #2 |
| 2 | Media metadata + selected-frame foundation | #3 |
| 3 | First real provider: Gemini | #4 |
| 4 | End-to-end Streamlit playground | #5 |
| 5 | Selected-frame extraction + coarse-to-fine | #6 |
| 6 | Validation + selective recovery | #7 |
| 7 | OpenRouter + TwelveLabs adapters | #8 |
| 8 | Benchmark suite | #9 |
| 9 | Release readiness | #10 |

Full milestone definitions: [SUVIX_PLAN.md](SUVIX_PLAN.md) §22.
Definition of done: [SUVIX_PLAN.md](SUVIX_PLAN.md) §24.

## Verification evidence (PR #1)

- `uv sync --extra dev` → resolved + installed (incl. `uv.lock` committed).
- `uv run pytest` → 1 passed (test_import.py).
- `uv run ruff check src tests` → clean.
- `uv build` → sdist + wheel built (foundation package).
