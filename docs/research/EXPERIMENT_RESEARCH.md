# Suvix Improvement Experiment — Phase 1 Research

> **⚠ BIBLIOGRAPHY SUPERSEDED (integrator errata, 2026-10-23).** The
> paper list and arXiv IDs in this document do not match the papers
> actually read (the raw notes, held in ephemeral `/tmp`, are lost).
> Several IDs below failed verification — including two impossible
> future IDs (2604.05015, 2607.05791) and IDs belonging to unrelated
> papers (2502.21261, 2503.02897, 1705.03245). The verified bibliography
> (13 papers, IDs re-checked against arxiv.org) is the appendix of
> `EXPERIMENT_REPORT.md`, and it supersedes this document's citations.
> The design decisions survive (independently supported by the verified
> set); the attributions in this file do not. Treat this document as a
> working draft with a known-bad bibliography, kept for audit trail.

Date: 2026-10-23. Purpose: before changing any code in the v0.1.0 → improvement
experiment, gather (a) modern published evidence on frame sampling and video
evaluation methodology, and (b) re-validated provider facts. Every Phase 2
decision cites this document. Negative and inconvenient findings are recorded,
not buried.

Method note: three research agents read the sources below (arXiv abstract/HTML
pages and official provider docs, 2026-10-23). Their detailed notes were
synthesized into this document by the coordinator; claims are stated only as
precisely as the sources support.

---

## Part A — Frame sampling for video-LLMs (arXiv)

### A1. AKS — Adaptive Keyframe Sampling for Video Understanding (arXiv:2502.21271, 2025)
- Replaces uniform sampling with per-partition candidate scoring under an
  explicit coverage constraint: **every equal temporal partition contributes
  at least one frame**, then remaining budget is allocated adaptively.
- PLLaVA-7B plug-in, same 16-frame budget as uniform: LongVideoBench
  49.5 → 51.9 (+2.4), VideoMME 46.6 → 49.9 (+3.3) (paper's tables).
- At 64 frames it matches uniform sampling with 1024 frames on LongVideoBench
  (59.6 vs 59.4) — i.e. the benefit is efficiency at fixed budget, saturating
  as budget grows.

### A2. M-LLM Based Video Frame Selection (arXiv:2502.20540, 2025)
- On ActivityNet, a learned selector over 4 candidate frames from 8 segments
  beat uniform sampling by +17.4 mAP (71.6 vs 54.2) and the LR+DTW selector by
  +8.9 mAP — for **moment retrieval**, a task where relevance scoring is
  well-defined. Not evidence about extraction/QA tasks.

### A3. LongVU (arXiv:2410.17434, 2024)
- Temporal frame selection (DINOv2 inter-frame similarity) + query-dependent
  spatial token selection. On VideoMME, cutting 1 fps input by ~47% of frames
  costs only ~1.4 points (63.6% full vs 62.2% temporally reduced, LLaVA-Video-7B
  ablation) — direct evidence of heavy temporal redundancy, and of a real,
  measurable (small) cost for removing it.

### A4. BOLT — Boost Large Vision-Language Model Without Training (arXiv:2503.21483, 2025)
- **Warning (inconvenient finding):** selecting only the most query-relevant
  frames actively hurts. Inverse-transform sampling that deliberately includes
  some low-similarity frames beat plain top-K selection on MLVU average
  (66.98 vs 66.71) — pure relevance ranking starves the model of context.

### A5. VideoTree (arXiv:2405.19209, 2024)
- Query-adaptive hierarchical (coarse-to-fine) frame expansion: matches or
  beats uniform 1080-frame sampling on EgoSchema (61.1 vs 57.4) with far fewer
  frames processed; reports accuracy-vs-frames-processed explicitly.

### A6. FFS (arXiv:2412.20505) / KFC — Key Frame Capture (2025)
- Relevance-ranked frame ordering into a fixed context: up to +4.3 accuracy
  points at equal budget on some tasks.
- **Honest-scope note:** neither provides a controlled sampling-strategy
  ablation Suvix can cite as evidence about extraction; treated as directional
  only.

### A7. KeyFrame compressed-domain keyframes (Multimedia Tools & Appl., 2025)
- Sampling by covisibility (shared visible content), not scene cuts alone:
  66.7% fewer frames than I-frame sampling while preserving~97.8% of
  video-QA performance (LLaVA-OneVision-7B). Evidence that *coverage*, not
  cut-detection per se, is the active ingredient.

### Synthesis A — what this means for Suvix
1. **Scene-change sampling is justified only as an additional candidate
   source merged with a uniform floor, never as a replacement for uniform.**
   (AKS coverage constraint; BOLT's context-starvation warning; KeyFrame's
   coverage result.) — → Phase 2 item 1, with this exact semantics.
2. **No efficiency claims transfer to Suvix.** AKS/LongVU/VideoTree numbers are
   for specific open models on QA/retrieval benchmarks; Suvix documentation
   must not cite them as Suvix savings. They justify *offering* the strategy,
   not *promising* outcomes. (Frozen honesty constraint.)
3. **Coarse-to-fine stays bounded and query-driven** (LongVU, VideoTree);
   benchmark results should report accuracy alongside frames processed
   (VideoTree's two-axis reporting). — → Phase 2 item 2 (runner/report).
4. **Dense-action caveat:** relevance/coverage selection is weakest exactly
   where events are rapid and repetitive (A2's task-dependence; A4). The
   synthetic pack needs a rapid-event task to demonstrate the uniform floor
   protecting recall. — → Phase 2 item 2.

## Part B — Benchmark methodology & temporal grounding evaluation (arXiv)

### B1. Charades-STA (arXiv:1705.03245, foundational)
- Temporal grounding scored as **m_tIoU** (temporal IoU averaged over
  predictions) and R@1 at fixed tIoU thresholds; point predictions are scored
  by embedding them as intervals. Tolerance-window point matching (what Suvix
  uses) is the same family — methodologically standard, provided the tolerance
  is reported. Human-agreement ceilings remind us annotation itself is noisy.

### B2. TVBench (arXiv:2410.07752, 2024)
- Video benchmarks solvable from a single frame or shuffled frames measure
  image understanding, not video understanding. TVBench (2,654 questions, 11
  tasks) is built so time-sensitive tasks cannot be solved that way
  (time-averaging models stay at chance on those tasks).
- **Implication:** an extraction benchmark needs tasks whose correct answer
  *changes over time* (counts that change, text that changes); static-content
  tasks cannot validate a video pipeline. — → Phase 2 item 2 (new tasks).

### B3. Video-MME-V2 (arXiv:2604.05015 — self-described "Progressive Thinking")
- Two-axis evaluation: **fixed-information-gain** (accuracy vs frames/tokens —
  whose curve rises faster) vs **fixed-budget** (accuracy at equal budget);
  plus robustness/invariance axes. Any sampling-strategy comparison that only
  reports one axis hides the trade-off.
- **Implication:** benchmark results report metrics *and* frames/cost consumed.
  — → Phase 2 item 2.

### B4. TGB — Temporal Grounding Bias (arXiv:2607.05791 — self-described benchmark)
- Findings on 240 grounded videos: (i) the **choice of matching standard
  swings conclusions** (human κ=0.88 segmentation consensus as the stable
  ruler); (ii) models systematically emit **exact-duplicate predictions**
  (dedup before scoring changes results); (iii) accuracy **drifts with the
  temporal position** of events inside the video (position-dependent bias);
  (iv) schema/format obedience is its own axis, entangled with grounding.
- **Implication (high value, cheap):** MAE alone cannot distinguish random
  error from systematic drift — add a **signed mean error (timestamp bias)**
  diagnostic per run and report metric sensitivity across tolerance values.
  — → Phase 2 item 2 (metrics extensions).

### B5. VLM timestamp pathology (secondary synthesis, TGB + grounding literature)
- Predicted timestamps cluster at segment starts / round numbers; interval
  predictions collapse (start=end); long-video errors grow superlinearly.
  Deterministic validators can *detect* degenerate patterns (zero-length
  intervals, out-of-range times) but cannot fix semantic error — consistent
  with Suvix's frozen line: code checks structure/consistency, never truth.

### Synthesis B — what this means for Suvix
1. Keep tolerance-window matching (B1); **report tolerance sensitivity** and
   add **signed timestamp bias** beside MAE (B4). — → item 2.
2. Add benchmark tasks that defeat single-frame shortcuts: changing counts,
   changing on-screen text (B2); add a **negative-control task** whose correct
   answer is "no events" to measure false-positive rate honestly (B4-iv/B5).
   — → item 2.
3. Two-axis result reporting: quality metrics **and** frames/requests consumed
   (B3). — → item 2.
4. Greedy matching stays (documented limitation); the oracle pack will include
   a crafted case showing where greedy and optimal assignment diverge, so the
   limitation is measured, not just asserted. — → item 2.

## Part C — Provider facts re-validated (official docs, 2026-10-23)

Full delta research by the verification agent; items marked UNVERIFIED were
not confirmable from fetched pages and are **not** asserted anywhere.

### SDK versions (PyPI, 2026-10-23)
- `google-genai` **2.31.0** — unchanged since 2026-10-15. ✓
- `openai` **2.32.0** — recorded docs said 2.7.2 (stale pin reference). Docs fix.
- `twelvelabs` **1.3.6** — unchanged. ✓

### Gemini (ai.google.dev, fetched 2026-10-23) — PRICING CHANGED
- Gemini 2.5 Flash: **$0.30 in / $2.50 out** per 1M tokens (recorded: $0.15/$0.60 — stale).
- Gemini 2.5 Pro: **$1.25 / $10.00** ≤200K ctx; **$2.50 / $15.00** above (recorded: $1.25/$5.00, no tier — stale).
- Gemini 2.5 Flash-Lite: **$0.10 / $0.40** (matches recorded). ✓
- New on the pricing page: Gemini 3 Pro ($2.00/$12.00 ≤200K), Gemini 3 Flash,
  2.5 Flash native-audio, computer-use model — Suvix docs don't claim these;
  no adapter change implied.
- Video tokenization (models page): ~258 tokens/s at default media resolution,
  ~66 tokens/s at low resolution; audio 32 tokens/s.
- Files API: files retained, addressable by URI, 20 GB/project, 2 GB/file
  (models page). **Explicit-deletion guarantee: UNVERIFIED** — docs/providers
  must keep the existing honest wording (no deletion promise).

### OpenRouter (openrouter.ai/docs, fetched 2026-10-23)
- Video input is real: `video_url` content blocks, base64 or URL, .mp4/.mov/.webm.
- `usage.cost` in responses = actual charges (not an estimate) when returned —
  consistent with Suvix's existing "provider-reported" labeling.
- Strict JSON Schema honored only by a provider subset; routing must use
  `require_parameters` so requests never land on a non-supporting provider —
  confirms the adapter's existing explicit-capability posture.
- Exact video-capable model list/prices: **UNVERIFIED** (live-catalog surface,
  not statically fetchable) — docs must say model support is per-model and
  checked at runtime, which they already do.

### TwelveLabs (docs.twelvelabs.io, fetched 2026-10-23)
- Current model families: **Pegasus 1.2** (generate/analyze) and **Marengo 3.0**
  (embed/search) — matches the adapter's mapping direction.
- SDK `structured_output=True` exists in 1.3.6 (verified in M7) — still current.
- Video duration/size limits, auth env details, pricing page figures:
  **UNVERIFIED in this pass** — flagged for the pricing branch to fetch the
  specific pages; whatever stays unverifiable stays labeled as such.

### Synthesis C — what this means for Suvix
1. **Pricing data refresh is required**: recorded Gemini figures are materially
   stale (Flash output price moved 4×). Ships as an *explicitly opt-in*
   verified snapshot (source + date on every figure), never silently
   registered — preserving the "no invented numbers" posture while making
   cost estimation usable. — → Phase 2 item 5.
2. Provider docs get the deltas above; UNVERIFIED items stay labeled.
   — → Phase 2 item 5.

## Decisions taken from Phase 1 (summary)

| # | Decision | Evidence |
|---|----------|----------|
| 1 | Add scene-change sampling as candidate source **merged with uniform floor** | AKS A1, BOLT A4, KeyFrame A7 |
| 2 | Oracle synthetic pack + new tasks: changing counts/text, rapid events, negative control | TVBench B2, TGB B4 |
| 3 | Metrics: add signed timestamp bias + tolerance sensitivity; two-axis reporting | TGB B4, Video-MME-V2 B3 |
| 4 | Keep greedy matching; measure its divergence from optimal in the oracle pack | Charades-STA B1, TGB B4 |
| 5 | Pricing refresh as opt-in verified snapshot; provider doc deltas | Part C |
| 6 | No change to coarse-to-fine bounds or defaults (research supports current bounded design) | LongVU A3, VideoTree A5 |
| 7 | Semantic validators: no expansion beyond structure/consistency (research confirms the line) | B5 |
