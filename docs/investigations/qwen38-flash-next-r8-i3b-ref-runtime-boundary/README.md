# R8-I3B — reference runtime-boundary localization (Issue #250)

Option-1 follow-up to the accepted Issue #248 terminal
`R8I3_REF_NONDETERMINISM_UNRESOLVED` (merged PR #249, main authority
`bc71774`; result head `a2cf9f33d1a056f2eef062b4186c078262e66f63`,
adjudication comment `5838156612`, retained external 534-row SHA256SUMS
self-digest `af9dfd0f08e9d3c4cbeb8fe164f781bc64b488ad4aba23954f5893ac980ab3bc`).
STATUS: **Phase 0 complete; V0 AMD screen COMPLETE (dispatch 5868617068
at head c5cc132: CROSS_VENDOR_DISAGREEMENT_STOP_BLOCKED, maintainer
stop); V0n NVIDIA current-window leg prepared by AMENDMENT-007 and
AWAITING fresh exact-head maintainer review + dispatch; no physical
work is authorized here.** The first v1
Arm-A attempt failed and is retained read-only; no physical execution
under this correction is authorized by issue creation or these docs.

Contents:

- `METHODOLOGY.md` — frozen prospectively BEFORE any physical work:
  discriminator arms A (Vulkan-necessity via the PROVEN `-dev none`
  CPU-only control), B (fresh-process vs proven-equivalent
  same-process repeats via `id_slot` pinning + `cache_prompt=false`
  full reset), C (`-t 1 -tb 1` serial CPU regime vs the default
  14-thread regime), D (predeclared length ladder 1024/1536/2048/2304/
  2560/3072), terminal vocabulary, and the hard prohibitions.
- `METHODOLOGY-AMENDMENT-001.md` — correction pass 4 (NO-GO
  5851078451): attributed tokenizer-server process authority
  (blocker 2), Arm-D predicate vocabulary (blocker 3:
  `midstream_ubatch_split` retired; `indexer_top_k_boundary`
  re-bound to the source-proven selection-width threshold
  2048+4-1=2051 KV cells), Arm-B drift-prefix durable custody
  (blocker 1). Dated amendment; the frozen text is preserved.
  §B's boundary sides were later corrected at equality by
  AMENDMENT-002 (2051 is all-cells, not selective).
- `METHODOLOGY-AMENDMENT-002.md` — correction pass 5 (NO-GO
  5852014883): exact execution-boundary semantics for
  `indexer_top_k_boundary` — width = min(n_kv, 2051) covers the
  full population through 2051 cells (all-cells side,
  n_kv <= 2051); selection becomes genuinely selective only from
  2052 cells (selective side, n_kv >= 2052); equality controls
  at 2050/2051/2052. Dated amendment; frozen text preserved.
- `METHODOLOGY-AMENDMENT-003.md` — correction pass 6 (two defects
  exposed by the retained failed v1 Arm-A execution): the global
  1200 s HTTP timeout is RETIRED in favor of the per-arm/unit
  timeout-budget authority (scripts/issue250_timeout.py; frozen
  rates incl. the retained ~2.25 tok/s CPU-only measurement);
  a frozen prospective COST GATE (12 h deterministic-proof
  ceiling) classifies the old ~5.3 h/unit serial Arm-C regime as
  NOT auto-reachable; Arm C is amended to the bounded C1
  reduced-parallelism probe (`-t 4 -tb 4`, namespace d250-arm-c1)
  with the serial `-t 1 -tb 1` regime retained ONLY behind the
  separate d250-arm-c2 maintainer gate; evidence generation
  identifiers frozen (v1 root retained read-only as the defect
  record under gen-1-v1-timeout-defect; canonical reruns use
  gen-2-pass6); dispatch comment 5852485456 is bound to
  1c86e97 and mechanically stale at any moved head. Dated
  amendment; frozen text preserved. Its §3 claim that deterministic
  C1 alone can LOCALIZE and that only variable C1 can access C2 is
  historical and expressly superseded by AMENDMENT-004.
- `METHODOLOGY-AMENDMENT-004.md` — prior Issue #250 prospective
  ordering/authority clarification plus Arm-C terminal
  contract: C1 (four threads) is informative but never terminal on its
  own; completed C1 deterministic **or** variable with no separately
  authorized serial C2 is BLOCKED. Only actual default-vs-single-thread
  comparison can LOCALIZE at C2; C2 variation permits D. Dedicated
  exact-head C2 authority, completed-C1 gate record with both dispatch
  digests, and cost control remain mandatory. Producer cost admission
  checks the entire retained `cost-planning-record.json` against the frozen
  recomputed projection and its canonical SHA-256 before any runner starts;
  a longer HTTP timeout does not grant spend authority. This does not
  authorize execution or rewrite the frozen methodology/earlier amendments.
  The maintainer's V0-first issue amendment supersedes CPU-first ordering
  only: V0 precedes A–D when freshly reviewed/dispatched; the existing A–D
  controls remain fallback, not replaced or loosened. V0 is non-terminal and
  diagnostic only, does not promote AMD (or NVIDIA) as GPU/reference authority,
  and its AMD 2-then-3 screen and stop law remain bounded to that population.
  Every physical leg still needs exact-head dispatch; cost admission is a
  separate gate, not dispatch authority. Its original V0 adapter stop claim
  is historical and superseded only by AMENDMENT-005; C1/C2 and V0 reduction
  laws remain unchanged.
- `METHODOLOGY-AMENDMENT-006.md` — current narrow correction after the
  failed physical V0 attempt at head `028dce94` under dispatch `5862772797`:
  the two-index physical preflight succeeded (zero AMD completion units
  executed), but the canonical freeze failed closed on a JSON key-type
  defect — `_v0_observe_device()` emitted integer device-map keys while
  the retained binding carries JSON string keys, and the validator
  compared raw dicts. No substrate drift occurred. The correction makes
  the runtime identity JSON-canonical at a single seam (string keys
  "0"/"1"; int 0/1 accepted only at the raw-input boundary; exactly the
  two devices with all identity-bearing fields; booleans/floats/aliases/
  collisions/extra indices rejected fail-closed), keeps the serialized
  identity inside the canonical digest law, and covers every retained
  consumer with no freeze-only exception. The old evidence root
  `/home/hermes/is250-campaign/evidence/` is retained read-only as
  historical failed-at-freeze evidence; dispatch `5862772797` is stale
  at any later head. The next physical attempt requires a fresh sibling
  evidence root (`evidence-v0-<NEW_HEAD_SHORT>` or equivalent), fresh
  exact-head review, and a new dispatch.
- `METHODOLOGY-AMENDMENT-005.md` — prior narrow repository-only V0 AMD
  adapter correction. Reuses #243 RADV + `GGML_VK_VISIBLE_DEVICES` binding
  on inferswarm05 and the exact #250 comparator observer binary; #250 Phase-0
  pinned-source law supplies ngl=1 output-vs-embedding placement while fresh
  selector/BDF + selected/excluded-die VRAM evidence supplies physical-device
  attribution. Binary `--help` succeeded unchanged on inferswarm05 but no
  model load or V0 population occurred. The two-index load-only preflight
  establishes the two candidate selector-to-BDF bindings; exactly ONE
  validated selector/BDF is then frozen for the V0 AMD screening population
  by an append-only retained record before the first unit. Every consumer
  independently re-derives the lexicographically-smallest selected BDF from
  both authenticated preflight mappings and refuses a re-signed freeze on the
  other valid sibling entry, even before unit 1; a named rule or a valid mapping
  entry alone is not authority. Only process freshness changes between AMD
  screening repeats — mixed-die or all-sibling populations are invalid V0
  evidence and cannot influence A reachability. Future
  load-only binding and V0 units still require independent fresh exact-head
  dispatch and retained cost/model authority. No `--device VulkanN` or
  per-tensor log observer is invented.
- `METHODOLOGY-AMENDMENT-007.md` — prospective current-window NVIDIA
  RTX 3060 Vulkan `ngl=1` comparison leg (V0n, namespace
  `d250-arm-v0n-nvidia` / arm `V0n-nvidia-vulkan-current`), frozen
  BEFORE any NVIDIA execution following the completed AMD V0 screen
  (three byte-identical fresh-process AMD rows ≠ both retained #248
  NVIDIA Vulkan rows → CROSS_VENDOR_DISAGREEMENT_STOP_BLOCKED).
  Distinguishes current NVIDIA variability from stable cross-vendor
  Vulkan difference before any CPU Arm A spend. The comparison subject
  is EXACTLY the accepted #248 Arm-B reference GPU (UUID
  `GPU-d5c05739…`, BDF `00000000:03:00.0`, driver `610.57.04`,
  NVIDIA ICD, Vulkan UUID/API/driver), bound through an append-only
  V0n screen-identity freeze derived from FRESH
  `issue248_identity.observe_arm_identity("B")` with zero identity
  problems — #248 identity machinery reused verbatim, no V0n-local
  schema, and vendor/device/driver-ID alone is never physical
  identity. Every unit reobserves the complete identity BEFORE launch
  and AFTER execution, requiring exact equality with the freeze; any
  drift rejects the unit before it becomes numerical evidence, and
  the retained population must share one freeze digest and one
  physical subject (mixed-identity/mixed-freeze populations are
  invalid). GPU residency is measured by a targeted nvidia-smi query
  selecting exactly one row matching BOTH accepted UUID and BDF.
  Vulkan-only (NVIDIA
  ICD + `GGML_VK_VISIBLE_DEVICES=0` + `CUDA_VISIBLE_DEVICES=-1` +
  link-family CUDA exclusion); same model/prompt/request/binary/seam/
  placement as V0; same 2-then-conditional-third screen law; four
  prospective states (CURRENT_NVIDIA_VARIABLE_STOP /
  CURRENT_CROSS_VENDOR_CONCORDANCE_STOP /
  CURRENT_CROSS_VENDOR_STABLE_DISAGREEMENT_STOP /
  CURRENT_NVIDIA_INVALID_BLOCKED), none a terminal, none A-eligibility.
  Retains the mechanical proof that the consumed #248 rows are NVIDIA
  Vulkan `ngl=1` evidence (nvidia ICD env + CUDA removed + `-ngl 1` +
  comparator SHA), never CUDA rows. Stale dispatches 5852485456,
  5862772797, and the completed AMD 5868617068 are hard-refused.
  Future evidence root: `evidence-v0n-nvidia-<HEAD_SHORT>/` sibling.
  Authorizes nothing; repository-only.
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
`issue250_diagnostic.py` (frozen arm plans, exact-head dispatch, V0 screening
states), `issue250_physical.py` (future per-unit custody and launch gates),
`issue250_terminal.py` (retained-byte reduction and V0-first reachability),
`issue250_timeout.py` (separate prospective V0/A–D costs and timeouts), and
focused CPU-only `tests/test_issue250_*`. These repository-only tests use
fixtures; they do not run the case-3072 model or authorize physical work.

Accepted terminals unchanged and read-only: #241
`R8I3_COMPARATOR_V2_BLOCKED`; #248
`R8I3_REF_NONDETERMINISM_UNRESOLVED`.
