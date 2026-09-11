# Issue #137 — Arm-C regime-4 semantic divergence diagnosis

Status: `ISSUE117_ARM_C_REGIME4_DIAGNOSIS_LOCALIZED` (derived by
`scripts/issue137_conclusions.py` from the retained probe records; all
seven terminal conditions true, zero problems). DIAGNOSTIC_ONLY. The
accepted #133 terminal `ISSUE117_ARM_C_ORDINARY_SERVING_FAIL` is
unchanged historical evidence. Arm D remains blocked.

## Fact classes (kept strictly separated)

### Accepted #133/#117 facts (input, not re-derived)

- 18/24 direct-vs-ordinary equality; six regime-4 committed-token
  divergences at positions 4/0/2/3/0/0 with complete model-execution
  input equivalence through each first divergent call.
- Frozen producer 924cd22e…, subject/geometry/identities as accepted.

### Newly observed diagnostic facts (this issue, DIAGNOSTIC_ONLY)

All from probe records in this directory; every probe re-derivable
from its retained inputs (sha256-pinned in each record).

1. Phase-1 (CPU-only, retained bytes): the six divergent cases are
   exactly the prompt_len > 64 population (PREFILL_CHUNK = 64); all
   four cross-campaign observations (historical direct/ordinary, retry
   direct/ordinary) are pairwise distinct for every divergent case and
   byte-identical for all 18 stable cases.
2. Probe A (fresh realizations, exact first-divergent call): position-0
   case c109-04-02-047 produced committed step-0 tokens
   107/818/3771/1437/107 across 5 realizations of byte-identical
   input; later-divergence case c109-04-01-026 (pos 4) produced
   140/100/106/140. Stable control c109-01-01-045 produced the
   accepted token 818 in 4/4 realizations.
3. Probe A2 (within ONE realization, 6 repeats): 107/9366/2918/107/107/
   107 — per-EXECUTION nondeterminism, tending to stabilize on a mode
   after repeated execution of the same shape.
4. Probe C (intervention): stable case c109-03-04-003 (53 tokens)
   driven as a single chunk: 1509 in 4/4 realizations (bit-stable);
   the SAME input driven as 32+21 chunks: 238631/1509/9259/236777 —
   the two-chunk extend path is causal INDEPENDENT of prompt length.
5. Probe D (cross-realization boundaries): chunk-1 (64-row) stage-1
   and stage-2 outputs byte-identical across realizations; the 3-row
   chunk-2 stage-1 output differs in every realization.
6. Probe D2 (within-realization layer bisection, 6 repeats):
   embedding output byte-identical in all repeats; the FIRST varying
   checkpoint is inside the stage-1 decoder stack at or before global
   layer 1 (after_layer_0 varies: 64ba…/8005…; second manifest with
   layer 0 retained). Stage-2 shows the same per-execution variance
   downstream; repeats with IDENTICAL stage-1+2 boundary bytes still
   produced different final tokens (818 vs 3771) — the last stage's
   small-extend execution varies too.
7. Probe B (history): fresh == after-stable-history in 3/3
   realizations; request history is not causal.

### Demonstrated causal conclusions

- Earliest divergence: model execution, stage 1 (inferswarm01 gpu-0),
  second prefill chunk — after a deterministic embedding, inside the
  owned decoder layers, at/before global layer 1, on the small-extend
  (1–3 query rows over a 64-row resident prefix) path.
- Determinism structure: per-execution nondeterminism (not a stable
  per-realization state), mode-stabilizing with repeated same-shape
  execution; single-chunk executions are bit-deterministic across
  realizations and repeats.
- Causal/necessary factor: executing a prefill as MULTIPLE chunks
  (second chunk with sub-64 rows through the extend path) — proven
  sufficient on a stable input (probe C) and present in every
  divergent case (all six are the >64 population).
- One mechanism explains all six cases: same partition, same probe
  behavior (in-session variance or cross-session drift from every
  accepted observation), same localization. Per-case mode structure
  retained in diagnostic-conclusions.json (per_case rows).

### Inference / hypotheses (NOT conclusions)

- The recurring digest families and tail stabilization suggest an
  uninitialized-or-recycled scratch/reduction buffer (or a
  data-dependent reduction order) in the small-extend attention path
  (extend_paged_attention with 1–3 query rows) on these RTX 3060
  devices; kernel-level confirmation is out of scope here.

### Remediation ideas (NOT authorized here)

- Separate remediation issue: standalone kernel harness reproducing
  the layer-0 chunk-2 variance; then deterministic scratch
  initialization or a deterministic sub-tile extend path, followed by
  full-cascade requalification under a new authority. Arm D stays
  blocked until a remediation + requalification authority explicitly
  unblocks it.

## Directory contents

- `METHODOLOGY.md` — phase ordering, controls, non-claims.
- `phase1-inventory.json` — CPU-only causal inventory + hypothesis
  matrix (re-derives the six divergences and the chunk partition from
  raw retained bytes).
- `i137-diag-*.json` — probe records (A/A2/B/C/D/D2), each
  DIAGNOSTIC_ONLY, producer-pinned, inputs sha256-bound.
- `manifest-*-d2b.json` — per-layer capture manifests (stage 1 and
  stage 2) for the final D2 bisection run; the raw `.pt` capture
  bundles are byte-hashed in these manifests
  (`bundle_sha256`) and retained immutably node-local at
  inferswarm01 `/srv/inferswarm/state/issue137/diag/
  i137-diag-D2-1789130625-captures/` (out-of-repo by size; identity
  and role verifiable from the manifests).
- `diagnostic-conclusions.json` — fail-closed terminal derivation.

## Reproduce

- Phase 1: `python3 scripts/issue137_phase1_inventory.py --repo . --out <path>`
- Conclusions: `python3 scripts/issue137_conclusions.py --evidence-dir
  <this dir> --out <path>` (requires the probe records present).
- Tests: `python -m unittest discover -s tests -p "test_issue137*"`
