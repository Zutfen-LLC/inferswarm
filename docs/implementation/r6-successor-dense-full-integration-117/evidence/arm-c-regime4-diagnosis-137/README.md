# Issue #137 — Arm-C regime-4 semantic divergence diagnosis

CORRECTED (PR #138 correction pass). Status:
`ISSUE117_ARM_C_REGIME4_DIAGNOSIS_PARTIAL` (derived by the corrected
`scripts/issue137_conclusions.py` v2 from the retained probe records
under the corrected methodology; zero problems; every load-bearing
terminal requirement except one is satisfied — per-case instability is
demonstrated for three of the six cases only, so a single identical
numerical mechanism for all six is NOT established). DIAGNOSTIC_ONLY.
The accepted #133 terminal `ISSUE117_ARM_C_ORDINARY_SERVING_FAIL` is
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
4. Probe C — RETIRED as causal evidence (correction): both arms ran
   cumulatively in one realization in a fixed order; the retained
   bytes (single 1509 in 4/4; two-chunk 238631/1509/9259/236777) are
   kept as an INFORMATIONAL observation only.
4b. Probe C2 (corrected one-variable intervention, run
   i137-diag-C2-1789141057): stable case c109-03-04-003 (53 tokens);
   per trial TWO fresh equivalent substrates, the target call FIRST
   on each, arm launch order counterbalanced by trial parity; chunk
   partition is the only changed factor. Single-chunk arm: 1509 in
   6/6 trials (deterministic, equals the accepted stable value).
   Two-chunk (32+21) arm: 9259/116130/9259/236777/9259/9259 — three
   distinct values in six trials. CONCLUSION: multi-chunk
   extend-prefill execution is SUFFICIENT for committed-token
   instability on an otherwise stable input; the single-chunk path is
   bit-deterministic. This is the corrected causal evidence
   (freshness bound by per-arm stage pids; remote last-stage launches
   101-113 retained in remote-last-stage-ledger-c2/).
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
   realizations; the cumulative after-divergent-history arm produced
   ONE differing value (100 vs fresh 107, realization 0) — retained
   and NOT interpreted away. Corrected conclusion: prior request
   history is NOT NECESSARY for divergence (fresh-first calls vary —
   probe A); history having no causal influence is NOT established
   (a single mismatch under demonstrated per-execution
   nondeterminism cannot decide it).

### Demonstrated causal conclusions

- Earliest divergence: model execution, stage 1 (inferswarm01 gpu-0),
  second prefill chunk — after a deterministic embedding, inside the
  owned decoder layers, at/before global layer 1, on the small-extend
  (1–3 query rows over a 64-row resident prefix) path.
- Determinism structure: per-execution nondeterminism (not a stable
  per-realization state), mode-stabilizing with repeated same-shape
  execution; single-chunk executions are bit-deterministic across
  realizations and repeats.
- Causal factor (corrected, probe C2): executing a prefill as
  MULTIPLE chunks (second chunk with sub-64 rows through the extend
  path) is SUFFICIENT for instability on a stable input — proven
  under the corrected one-variable design — and the multi-chunk
  population is exactly the divergent population (shared NECESSARY
  path for all six cases).
- One mechanism for all six: NOT established. Three cases
  (04-01-026, 04-02-047, 04-05-043) vary in-session on fresh
  substrates; three (04-03-040, 04-04-024, 04-06-074) are
  session-stable while matching NO accepted value (cross-session
  drift). Layer-level localization (D/D2) covers c109-04-02-047
  only. Path selection is common; earliest observed divergence and
  the hypothesized kernel defect are demonstrated for one case.
  Per-case rows in diagnostic-conclusions.json.

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
- `i137-diag-*.json` — probe records (A/A2/B/C/C2/D/D2), each
  DIAGNOSTIC_ONLY, producer-pinned, inputs sha256-bound; v2 records
  (C2) additionally carry the full accepted-authority binding block
  (per-module producer pins, interpreter, torch numerical-mode flags,
  GPU geometry, driver sha + invocation, per-substrate realization
  identities).
- `remote-last-stage-ledger-c2/` — inferswarm03 last-stage launch
  ledger (ready-*.json + launcher loop log) for the corrected C2 run;
  each entry binds pid/launch-counter/gpu-uuid/frozen producer.
- `manifest-*-d2b.json` — per-layer capture manifests (stage 1 and
  stage 2) for the final D2 bisection run; the raw `.pt` capture
  bundles are byte-hashed in these manifests
  (`bundle_sha256`) and retained immutably node-local at
  inferswarm01 `/srv/inferswarm/state/issue137/diag/
  i137-diag-D2-1789130625-captures/` (out-of-repo by size; identity
  and role verifiable from the manifests).
- `diagnostic-conclusions.json` — fail-closed terminal derivation.
- `MANIFEST.sha256` — immutable bundle-local coverage of this evidence,
  its exact producers, reducers, verifiers, and tests. It deliberately excludes
  living status/CI files and the mutable working-tree parent manifest.

## Reproduce

- Phase 1: `python3 scripts/issue137_phase1_inventory.py --repo . --out <path>` (v2: authority-pinned inputs + runtime/lifecycle inventory)
- Conclusions: `python3 scripts/issue137_conclusions.py --evidence-dir
  <this dir> --out <path>` (requires the probe records present).
- Manifest: `python3 scripts/issue137_manifest.py --check` (use `--write`
  only while assembling this bundle, after every authored and derived file is
  final).
- Tests: `python -m unittest discover -s tests -p "test_issue137*"`
