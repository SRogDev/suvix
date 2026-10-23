# Suvix Improvement Experiment — Final Report

Date: 2026-10-23. Mandate (Roger): take Suvix from v0.1.0 and improve it
autonomously — own tests, validation against real external information,
several modern arXiv papers consulted — and deliver a list of everything
done, explained, with the reason for each decision.

Constraints honored throughout: **zero GitHub contact** (account suspended;
all work is local, one branch per improvement, PR-ready, `main` untouched at
`2569ed2`); **no provider API keys, no paid calls** (all validation is
offline: synthetic ground truth, deterministic oracles, official docs);
frozen contracts intact (no cache/DB/persistence, explicit provider
selection, JSON Schema contract, honest evidence, bounded recovery, no
cost/accuracy claims without measured evidence).

**How to read the evidence:** every test count below was re-run and verified
by the coordinator on the final branch HEADs (all-extras environment), not
copied from builder reports. Where a builder's claim did not survive
verification, this report says so.

---

## 1. Research (Phase 1) — `docs/research/EXPERIMENT_RESEARCH.md`

Eleven papers read (arXiv, 2024–2026 unless foundational) plus official
provider documentation re-fetched on 2026-10-23. Decision-relevant findings:

**Sampling.** AKS (2502.21261): adaptive keyframe selection only helps under
an explicit *coverage constraint* — every temporal partition contributes
frames. BOLT (2503.02897): selecting only top-relevance frames *hurts* —
context starvation is real. KeyFrame (2025): coverage (covisibility), not
cut-detection, is the active ingredient. LongVU (2410.17434) and VideoTree
(2405.19209): temporal redundancy is high and bounded query-adaptive
refinement works; report accuracy *against frames consumed*.
→ **Decision:** scene-change sampling ships only as candidates **merged
with a uniform floor**, never as a replacement; no efficiency/accuracy
claims were imported from these papers (their numbers are for specific
open models on QA/retrieval benchmarks, not for Suvix).

**Evaluation.** TGB (temporal grounding bias study): the matching standard
swings conclusions; predictors drift with temporal position; duplicate
emissions distort scores. Video-MME-V2: two-axis reporting (quality *and*
resources consumed). TVBench (2410.07752): benchmarks solvable from one
frame measure image understanding, not video. Charades-STA (1705.03245):
tolerance-window matching is standard *when the tolerance is reported*.
→ **Decisions:** add a signed **timestamp bias** diagnostic and
**tolerance-sensitivity** reporting; add tasks that defeat single-frame
shortcuts and a **negative control**; keep greedy matching but *measure*
its divergence from optimal assignment instead of asserting it.

**Providers (official docs, 2026-10-23).** Recorded Gemini prices were
materially stale: 2.5 Flash output moved $0.60 → **$2.50**/1M; 2.5 Pro is
$1.25/$10.00 ≤200K context and $2.50/$15.00 above (recorded: $5.00 flat).
SDKs: google-genai 2.31.0 (unchanged), openai **2.32.0** (docs cited
2.7.2), twelvelabs 1.3.6 (unchanged). TwelveLabs: Pegasus 1.2 / Marengo 3.0
current. **Unverifiable and left labeled as such:** TwelveLabs pricing and
numeric video limits (JS-rendered/login-walled surfaces), OpenRouter's
live video-model catalog, any Gemini Files API deletion guarantee.

## 2. Improvements (Phase 2) — one local branch each

### 2.1 `feat/scene-change-sampling` — 5 commits, HEAD `938f086`
**What:** `suvix/sampling/scene_changes.py` — ffmpeg scene-transition
detection (`select='gt(scene,T)',metadata=print`, pts_time parsing),
`merge_with_uniform_floor()` (reserves `ceil(max_frames × floor_fraction)`
for uniform samples; scene candidates fill only the remaining budget;
0.05s dedupe, uniform wins; deterministic evenly-spaced subsetting), and
`make_scene_sampler()` (Sampler protocol). Wired behind the explicit
`ExtractionOptions(sampling="scene_changes")` with `scene_threshold`
(0.4) and `scene_floor_fraction` (0.5) knobs; the planner flags
`requires_scene_sampling` on the decision (visible in the recorded reason)
and extraction runs detection via `asyncio.to_thread`. Defaults unchanged.
**Why:** plan §9.5's deferred option, with the research-mandated semantics
of §1 (floor-always) — BOLT/AKS/KeyFrame are the reason it is a merge, not
a switch. Semantics are stated honestly everywhere: a scene change is a
visual transition, not a semantic event; **no accuracy claim is made**.
**Real-world subtlety found and documented:** libx264's scene score is
codec/content-dependent — solid-color hard cuts can score ≈0.01 (below any
sane threshold), textured segments score clearly; the 0.4 default was
calibrated on generated textured content and the limitation is written
into the module and README.
**Evidence (coordinator-verified):** 373 passed, 3 skipped (baseline 343 +
30 new: 24 sampler tests incl. real generated cut clips, options/planner
validation, one end-to-end extraction asserting the 5.0s cut reaches the
adapter while all floor frames are kept). Ruff clean.
*History note:* the branch contains two adjacent commits with the same
message (the builder's original commit and the coordinator's recovery
commit) — an artifact of the environment's delayed persistence during
this experiment; the tree at HEAD is the verified one.

### 2.2 `feat/oracle-benchmark-pack` — 4 commits, HEAD `7415309`
**What:** (a) Metrics: `timestamp_bias` (signed mean error over matched
pairs — distinguishes systematic drift from noise, which MAE cannot) and
`event_metrics_by_tolerance` (P/R/F1 swept over tolerances), exported from
`suvix.evaluation`. (b) Four new synthetic ground-truth tasks with
generator support: `changing_counts` (count changes 2→4 mid-video),
`changing_text` (ALPHA→BRAVO), `rapid_events` (0.25s flashes ≈1s apart),
`negative_control` (static video, expected `events: []` — any prediction
is definitionally a false positive). All fixtures regenerate
byte-identically (sha256 pinned in task files). (c) An oracle test suite:
a deterministic adapter returning ground truth verbatim scores exactly
P=R=F1=1.0, MAE=0.0, bias=0.0, schema pass=1.0; controlled-noise variants
recover *exactly* the known distortion (uniform +0.3s jitter → MAE 0.3,
bias +0.3; drop-half → recall 0.5; duplicate-all → duplicate rate 1.0 and
precision 0.5; known hallucinations → exact precision fraction; missing
required field → exact schema-pass drop). (d) Runner entries now record
`frames_sampled` per baseline (two-axis reporting).
**Why:** the benchmark suite is Suvix's reason to exist, but nothing
proved its numbers were *right*. This is the strongest validation possible
without API keys: the evaluation machinery is now proven against known
truth. It validates the pipeline only — **not** any provider's accuracy.
**Measured limitation (not just asserted):** greedy matching scores 0.5
P/R where optimal assignment scores 1.0 on a crafted dense cluster
(predictions 1.4/1.6 vs expected 1.0/2.0, tolerance 0.55) — documented in
`docs/benchmarking.md` as "dense-cluster scores are lower bounds".
**Evidence:** 367 passed, 3 skipped (343 + 24 new). Ruff clean.

### 2.3 `test/property-based-tests` — 6 commits, HEAD `94c60d3`
**What:** hypothesis added to the dev extra; ~35 property tests over
sampling math, segment offsets, and evidence validation (sortedness,
budget, bounds, determinism, contiguity, registry membership, rejection
domains). Two real bugs found and fixed:
1. **Non-finite inputs passed validation** — `duration_seconds <= 0` is
   False for NaN, so NaN durations/intervals/segment lengths were silently
   accepted. Fixed with `math.isfinite` checks in `sampling/uniform.py`
   and `media/segments.py`, with regression tests. (`3972708`)
2. **Interval timestamps drifted off-grid** — `uniform_timestamps`
   accumulated `t += interval`; for duration 1.0s / interval 0.1 the sum
   reached 0.9999999999999999 at i=10 and emitted a spurious 11th
   timestamp. Fixed by index multiplication (`i * interval`), matching
   count mode. (`1564fe9`) *Honesty note:* an early claim that this also
   guarantees every pairwise gap ≥ interval did **not** survive the
   coordinator's measurement (gaps can sit one ulp below the interval —
   0.1 is not exactly representable); the pinned contract is the grid
   values, and the regression test says exactly that.
3. A third finding was in a *test*, not the code: the segment-count
   property's lower bound ignored that `fl(duration/length)` can round up
   across an integer (the splitter tiles exactly with one fewer segment).
   Bound widened ±1 with the reasoning recorded; surfaced by the
   integration run (§4), fixed in `94c60d3`.
**Why:** timestamp math is where Suvix's honesty claims live; example-based
tests had covered the happy grid, properties cover the space.
**Evidence:** 384 passed, 3 skipped (343 + 41 new). Ruff clean. Suite cost
of the properties ≈ +2s.

### 2.4 `docs/pricing-refresh` — 2 commits, HEAD `fe06331`
**What:** `suvix.evaluation.cost.load_verified_pricing_snapshot()` — an
explicitly opt-in loader registering the Gemini figures the builder
personally re-fetched from the official pricing page on 2026-10-23
(Flash $0.30/$2.50, Pro $1.25/$10.00, Flash-Lite $0.10/$0.40 per 1M), each
with source URL + date. Default behavior unchanged (no table until called;
unknown `as_of` dates raise instead of serving unverified numbers). The
docstring states what the flat table *cannot* represent: Pro's >200K tier
(estimates there understate) and per-modality audio rates.
`docs/providers/*.md` updated with all §1 deltas.
**Why:** the recorded prices were materially stale (Flash output 4× off) —
cost estimates built on them would have been wrong while looking precise.
Opt-in (not auto-registered) preserves the "no silent numbers" posture.
**Deliberately NOT imported:** Gemini Batch-tier prices into the snapshot
(the fetched page's tier presentation didn't support a clean flat
mapping) and all TwelveLabs prices (unverifiable — page is JS-rendered;
left labeled UNVERIFIED with the date).
**Evidence:** 351 passed, 3 skipped (343 + 8 new). Ruff clean.

### 2.5 `chore/typing-hardening` — 5 commits, HEAD `9c9da82`
**What:** mypy added to the dev extra and CI; baseline was **54 errors /
17 files → 0**, strictness `disallow_untyped_defs` + `warn_return_any` +
`warn_unused_configs`/`warn_unused_ignores`, `check_untyped_defs` off
(documented why). All but one fix are typing-only (missing annotations,
`ClassVar` for pydantic-resolved class attributes in the adapter registry,
`X | None` narrowing in extraction, generic `deque` in coarse-to-fine,
`exc_info` misuse in OpenRouter logging, missing `types-jsonschema`).
The gemini SDK's lazy/optional import is handled by a scoped mypy
override, so no runtime import guard was invented.
**The one behavior change:** benchmark Baseline E crashed on external
`video_ref` inputs; it now rejects them with a clear `ValueError`
(matching Baseline A's contract), with a regression test. (`6e971dc`)
**Why:** Roger's quality bar is formatter + linter + typecheck at zero;
v0.1.0 shipped with only two of the three wired.
**Evidence:** mypy "Success: no issues found in 30 source files";
344 passed, 3 skipped (343 + 1 regression). Ruff clean.

### 2.6 `docs/experiment-research` — this report + Phase 1 document
`docs/research/EXPERIMENT_RESEARCH.md` (sources, findings, decision map)
and this report. 2 commits.

## 3. Release checklist (§15.4) — executed 2026-10-23 on shipped v0.1.0

| Check | Result |
|---|---|
| Package name available/usable | `suvix` still free on PyPI (publish pending Roger's token — §5) |
| Metadata | name/version/MIT/Requires-Python ≥3.10 correct in wheel METADATA; LICENSE file included |
| Build sdist + wheel | ✓ (`uv build`, 34 wheel files / 93 sdist files) |
| Wheel installs in clean env | ✓ |
| Import without providers | ✓ — core imports with google-genai/openai/twelvelabs/streamlit all absent |
| Each extra independently | ✓ gemini / openrouter / twelvelabs / playground each install from the wheel and their adapter imports work |
| README install commands | ✓ `uv sync` workflow verified throughout; extra syntax verified against the local wheel (registry form awaits publish) |
| No secrets/fixtures in artifacts | ✓ — no `.env`/keys/media in wheel or sdist (only flagged item: the fixture *generator script* in the sdist — source code, not media) |
| License / dependency licenses | Suvix MIT; runtime deps pydantic + jsonschema (MIT) — permissive throughout |
| Python compatibility | ✓ wheel installs + imports on Python 3.10.21 and 3.12 |

Environment note: this VM's `/tmp` is a 512MB tmpfs — the first playground
install failed there with "No space left" on a large wheel member; redone
on the overlay disk, it installs fully (streamlit 1.66.1, pyarrow 26.0.0).
The failure was the VM, not the package.

## 4. Integration check (throwaway merge, deleted after verification)

All six branches merged in sequence into a scratch worktree. Conflicts
found — all mechanical, listed so the future PR order can anticipate them:
STATUS.md (every branch; trivial union), README.md (oracle × pricing
paragraphs; union), pyproject.toml + uv.lock (hypothesis × mypy dev deps;
union + `uv lock` regen), `evaluation/metrics.py` (oracle's new functions
× typing's `count_accuracy` signature widening; union). One real catch:
the segment-count property failure of §2.3(3) only appeared under the
integration run's hypothesis exploration.
**Integrated result: 447 passed, 3 skipped** (= 343 baseline + 30 + 24 +
41 + 8 + 1, exactly additive), ruff clean, mypy clean (31 files), wheel
builds. The scratch branch was deleted; the six branches above are the
deliverables.

## 5. Considered and rejected

- **Scene-change as a *replacement* sampler / relevance-ranked top-K** —
  refuted by BOLT (context starvation) and AKS (coverage constraint).
- **Expanding "semantic" validators toward content judgments** — the
  research (TGB/VLM-pathology synthesis) confirms the frozen line: code
  checks structure/consistency, never semantic truth. No change.
- **Replacing greedy event matching with optimal assignment** — would add
  a dependency (or a hand-rolled Hungarian) to fix a divergence that only
  bites on dense clusters; measured and documented instead (§2.2).
- **Auto-registering the pricing snapshot** — rejected: silently serving
  dated prices violates the "no silent numbers" posture. Opt-in only.
- **Importing TwelveLabs prices / Gemini Batch tier into the snapshot** —
  not verifiable from fetched pages; left labeled, not guessed.
- **Playground changes** — nothing in the research justified touching it.

## 6. What remains blocked (needs Roger)

1. **Live provider runs** — the integration tests and, above all, the real
   benchmark runs that answer Suvix's central research question need
   `GEMINI_API_KEY` / `OPENROUTER_API_KEY` / `TWELVELABS_API_KEY`. The
   machinery they'd exercise is now oracle-proven offline.
2. **PyPI publish** — needs Roger's PyPI account + API token (2FA). The
   name `suvix` was still free on 2026-10-23; the wheel is upload-ready.
3. **GitHub** — account suspended: these six branches become PRs when it
   is restored. Suggested merge order: typing → property → pricing →
   oracle → scene → research-docs (conflicts per §4 are trivial unions;
   regenerate `uv.lock` after the pyproject union). The CI workflow file
   (updated with the mypy step on the typing branch) still needs a
   workflows-scoped credential to push.

*No claim in this report rests on a model call, a paid API, or an
unverifiable source. Offline measurements measure the pipeline — they are
labeled as such wherever they appear.*
