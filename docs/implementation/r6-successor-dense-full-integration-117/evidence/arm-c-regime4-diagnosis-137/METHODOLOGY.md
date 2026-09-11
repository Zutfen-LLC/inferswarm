# Issue #137 diagnostic methodology — Arm-C regime-4 semantic divergence

DIAGNOSTIC_ONLY. This issue diagnoses the accepted #133 terminal
`ISSUE117_ARM_C_ORDINARY_SERVING_FAIL` (18/24 equality, six regime-4
committed-token divergences). It does not reopen #133, does not retry
Arm-C, does not tune, does not touch holdout material, and does not
unblock Arm D.

## Accepted baseline (bound, not re-derived here)

- PR #136 merge `1b83bcab0a5e682a438ca0554f71dd0ace15be55` (origin/main
  at campaign start; verified).
- Frozen producer `924cd22ea081f6d4ed471016faf01d427fc5b0d2` deployed
  read-only and clean on inferswarm01/03 (re-verified pre-probe; GPUs
  idle).
- Subject `google/gemma-4-12B-it` @ `707f0a3b…`, checkpoint sha256
  `5a84cb31…ff18d`, qualification subject `c6b9fe72…4ffd`, geometry
  01/gpu-0 `[0,16)` + 01/gpu-1 `[16,32)` + 03/gpu-0 `[32,48)` —
  unchanged from the accepted #133 campaign.
- The six accepted divergent cases and first-divergence positions
  (4/0/2/3/0/0) are re-derived from raw committed-id lists by the
  Phase-1 inventory tool; authored verdict fields are not authority.

## Phase ordering (as executed)

1. Phase 0 — repository truth synchronized (branch off the #136 merge;
   status paragraphs updated in the diagnosis PR only).
2. Phase 1 — CPU-only causal inventory from retained bytes, BEFORE any
   diagnostic GPU execution (`scripts/issue137_phase1_inventory.py`,
   output `phase1-inventory.json`). The inventory derived the
   chunk-partition fact (all six divergent cases are the only
   prompt_len > PREFILL_CHUNK=64 cases), the four-observation
   cross-campaign matrix, and the hypothesis matrix, and selected the
   minimum discriminating probes from them.
3. Phase 2 — diagnostic capture strategy with no serving-semantic
   change: the frozen producer's own op-gated capture surface
   (#71 `ARM_CAPTURE` / `--localization-capture` / wire `capture_step`)
   is used; ZERO producer code changes; the probe driver lives in the
   coordination repo and composes the frozen runtime API only.
   Off-by-default is proven by the producer's own construction (the
   `_emit` no-op without an armed sink) and by the control probes
   reproducing accepted committed tokens byte-exactly.
4. Phase 3 — DIAGNOSTIC_ONLY physical probes, fresh run identity
   `i137-diag-*`, one factor per probe:
   - A  fresh-realization repeatability (5 realizations, position-0
     case; 4 realizations on the other five cases and on one stable
     control case);
   - A2 within-realization repeats (6 repeats, one realization);
   - B  history sensitivity (fresh vs after-stable-history vs
     after-divergent-history, 3 realizations);
   - C  chunk-partition intervention (stable 53-token case, canonical
     single chunk vs synthetic 32+21 two chunks, 4 realizations);
   - D  cross-realization boundary localization (stage outputs hashed
     per chunk, 3 realizations);
   - D2 within-realization layer bisection (capture after global
     layers 0/1/2/4/8/12 + embedding + boundary, 6 repeats, one
     realization; second run adds layer 0).
5. Phase 4 — conclusions reducer (`scripts/issue137_conclusions.py`),
   CPU-only, fail-closed, terminal derived from measured conditions.

## Determinism / perturbation controls retained

- Software identity: probe records retain python/torch/cuda versions
  from the executing venv; producer sha asserted clean at start.
- No deterministic-algorithm flag was enabled anywhere; no global mode
  changed; all probes run the frozen serving path unmodified.
- Every probe record is marked DIAGNOSTIC_ONLY and carries the input
  sha256s (fixture, chain plan, environment, accepted direct run).
- Control probe: the driver reproduced the accepted committed token for
  stable case c109-01-01-045 (818) in 4/4 fresh realizations — the
  probe machinery itself is proven non-perturbative on the stable
  population.
- No h109-* material was opened, generated, copied, or used.

## Non-claims

- No claim that the six cases are "flaky" without mechanism: the
  mechanism is measured (per-execution nondeterminism in the
  small-extend-chunk prefill path), and the partition is exact.
- No behavioral fix is landed; the remediation hypothesis is recorded
  for a separate remediation authority.
- Nothing here re-qualifies Arm-C or unblocks Arm D.
