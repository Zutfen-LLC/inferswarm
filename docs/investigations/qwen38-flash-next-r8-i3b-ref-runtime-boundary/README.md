# R8-I3B — reference runtime-boundary localization (Issue #250)

Option-1 follow-up to the accepted Issue #248 terminal
`R8I3_REF_NONDETERMINISM_UNRESOLVED` (merged PR #249, main authority
`bc71774`). STATUS: **Phase 0 complete + frozen tooling + CI green —
HALTED for maintainer exact-head dispatch.** No physical execution has
been performed under Issue #250 (and none is authorized by issue
creation; a later reviewed PR must receive explicit exact-head
dispatch).

Contents:

- `METHODOLOGY.md` — frozen prospectively BEFORE any physical work:
  discriminator arms A (Vulkan-necessity via the PROVEN `-dev none`
  CPU-only control), B (fresh-process vs proven-equivalent
  same-process repeats via `id_slot` pinning + `cache_prompt=false`
  full reset), C (`-t 1 -tb 1` serial CPU regime vs the default
  14-thread regime), D (predeclared length ladder 1024/1536/2048/2304/
  2560/3072), terminal vocabulary, and the hard prohibitions.
- `evidence/phase0/phase0-analysis.json` — machine-derived (stdlib,
  deterministic; re-run byte-identical, sha256 `02304214…`): authority
  verification, pinned-source reconstruction R1–R6 (prompt ingestion,
  first-generation-step provenance, threadpool/threading, CPU kernels,
  Vulkan-at-ngl=1 output-layer arithmetic, process-init state), the
  pinned-build CLI control proofs, and the predeclared hypothesis
  matrix H1–H5 with smallest discriminating probes.

Key phase-0 findings (all source-cited in the analysis JSON):

1. **Decision-0's row is a PREFILL product** — the last prompt ubatch
   — not a separate decode; d1–d7 are single-token eval decodes
   (`graphs reused = 7`).
2. **At every tested ngl rung (1/2/4/6/8) the OUTPUT layer is the
   GPU-resident layer** (`i_gpu_start = 48+1-ngl`), so the full-vocab
   projection feeding every decision row executes on Vulkan at every
   rung; the input embedding is always CPU. `#248`'s
   placement-invariance is consistent BOTH with output-layer origin
   AND with CPU-side prefill divergence upstream.
3. **`-ngl 0` is NOT a pure CPU control** in this pinned build (the
   Vulkan backend stays in the scheduler with op_offload/KV-offload
   possible); **`-dev none` IS** (no GPU backend at all). Arm A uses
   `-dev none`.
4. Default threading is 14 (OpenMP build; `hardware_concurrency()/2`
   on the 28-LPU E5-2683 v3), split `-t/-tb`, affinity/priority/poll/
   NUMA controls all proven from the pinned source + binary help.
5. The same-process reset seam is source-proven: `cache_prompt=false`
   forces `n_past=0` → `keep_first(0)` → full `seq_rm(0,-1)` wipe →
   full recompute; per-request `id_slot` pinning exists in the pinned
   server (Arm B's one DECLARED contract extension).

Tooling: `scripts/issue250_phase0.py` (analysis),
`scripts/issue250_diagnostic.py` (d250- namespaces, dispatch
authority, frozen arm plans, digest-only determinism, mechanical
terminal derivation), `tests/test_issue250_diagnostic.py` (44
CPU-only tests incl. mutation controls and direct reducer-invocation
terminal-tree tests).

Accepted terminals unchanged and read-only: #241
`R8I3_COMPARATOR_V2_BLOCKED`; #248
`R8I3_REF_NONDETERMINISM_UNRESOLVED`.
