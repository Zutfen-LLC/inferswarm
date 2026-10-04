# R8-I6 — V340L comparator/2 physical-authority gate (Issue #270)

**Status: REPOSITORY/CPU-ONLY — tooling and tests complete; STOP for
maintainer exact-head review before any physical execution.**

Campaign: `issue270-r8i6-v340-comparator2`.
Base: `4c6df96cd03e50fbb990256507eb859769536aad` (post-#269 main).

## Scope

Qualify ONE exact V340L Vega10 die on inferswarm05 as a comparator/2
physical subject against the accepted RTX 3060 Vulkan reference on
inferswarm01, using the accepted continuous comparator/2 semantics
UNCHANGED and the historical-excluded fixture ladder ONLY
(case-256 / case-1024 / case-3072; `top_k=1`, seed 0, `n_predict=8`).

The campaign product is an authority record for a future maintainer
decision. It performs NO predictive calibration, derives NO threshold,
and grants NO R8-J execution. `case-4096` and every `c237-*` /
`h237-*` / `p237-*` predictive namespace are refused structurally.

## Authority consumed (never re-frozen)

- **#237** methodology authority: merge `3aa59aed…`, terminal
  `R8I_QWEN38_HETEROGENEOUS_VULKAN_METHODOLOGY_FROZEN` (acceptance
  comment 5774946656).
- **#241** comparator/2 execution: historical evidence only — PR #242
  was CLOSED UNMERGED, so nothing imports `issue241_*`; the accepted
  continuous comparator/2 semantics are re-declared locally in
  `scripts/issue270_comparator.py` and cross-verified by tests against
  the accepted main constants. Terminal `R8I3_COMPARATOR_V2_BLOCKED`
  (adjudication 5818984406).
- **#243** retained subject: candidate die identity DERIVED from the
  retained phase-1 census bytes on main
  (`docs/investigations/qwen38-flash-next-r8-i4-v340l-z440/retained/evidence/phase1/phase1-census.json`)
  and double-locked against an independently transcribed expectation.
  Accepted GO 5803559861 / closure 5803624698.
- **#248** reference arm: the accepted RTX 3060 identity is consumed
  read-only from `scripts/issue248_identity.py` (`frozen_identity("B")`),
  never re-frozen.
- **#250** tooling identity: comparator/canonical binary digests, the
  8 frozen observer libraries, model members, request contract, and the
  two-index selector-binding law are consumed from the accepted
  `issue250_diagnostic` / `issue250_physical` main modules.
- **#239 / #244** remain dispatch-blocked / open preparation; this
  campaign grants neither reachability.

## Phases

- **Phase 0 — authority + repository reconciliation**
  (`issue270_physical.phase0_reconciliation`): accepted-authority
  checklist, main-drift classification (reconcilable, recorded), and
  sealed-holdout presence (fail-closed; the holdout ciphertext stays
  sealed — no plaintext, decryption, or authorization commit).
- **Phase 1 — durable subject freeze** (`issue270_terminal.write_subject_freeze`):
  append-only, self-digest-carrying record binding the fresh host
  observation, the frozen candidate-die selection, runtime/model/binary
  identities, fixtures, and the live dispatch.
- **Phase 2 — platform/placement preflight**
  (`issue270_terminal.validate_selector_binding`): fresh two-index,
  two-die load-only binding (accepted #243/#250 law) with selected-die
  residency >= 64 MiB and excluded-die residency < 64 MiB per index;
  CUDA excluded mechanically (`CUDA_VISIBLE_DEVICES=-1`, RADV ICD
  only); the campaign die is then derived by the FROZEN rule
  `lexicographically-smallest-selected-bdf-of-validated-two-index-preflight`
  — never by enumeration order.
- **Phase 3 — historical-excluded comparator/2 execution** (thin
  executor, NOT in this pass; gated on maintainer dispatch at the
  merged head): per case, one continuous reference request + repeat on
  inferswarm01 and one continuous candidate request + repeat on
  inferswarm05; exactly 8 decisions, 8+8 full-vocab FP32 rows per arm;
  row capture BEFORE reference-token forcing; observer-inertness
  controls.
- **Phase 4 — validation** (`issue270_terminal.derive_terminal`): the
  SINGLE mechanical terminal from retained bytes. Row custody is
  byte-bound (fail-closed reader; independent SHA-256 must equal the
  claim before finiteness); repeat runs compare independently computed
  digests. Numerical deltas are retained as diagnostics only — a
  candidate/reference winner disagreement does NOT fail the gate, and
  NO threshold or placement guidance is derived. Terminals:
  `R8I6_V340_COMPARATOR2_PHYSICAL_AUTHORITY_PASS`,
  `R8I6_V340_COMPARATOR2_INFRASTRUCTURE_BLOCKED`,
  `R8I6_V340_COMPARATOR2_RUNTIME_BLOCKED`,
  `R8I6_V340_COMPARATOR2_AUTHORITY_BLOCKED`.

## Dispatch

Exact-head maintainer dispatch: a top-level OWNER/MEMBER comment whose
stripped lines are exactly

```
R8I6 PHYSICAL DISPATCH #270
head=<40-hex head of the merged PR>
namespace=c270-v340-comparator2
```

Stale heads, wrong namespaces, and non-maintainer authors fail closed.
There is no authority parameter anywhere.

## Hard prohibitions (structurally enforced)

No predictive calibration or `c237-*` execution; no R8-J threshold
work; no holdout plaintext/decrypt/access or authorization commit; no
mixed NVIDIA+AMD participants in one request (arms run on separate
hosts, one device each); no Vulkan RPC serving qualification; no second
V340L die in the correctness comparator; no coherent-16-GiB/cross-die
P2P/coherency claim; no placement optimization based on numerical
agreement; no resurrection of #241 as active authority; no generic
planner branch on model name, GPU vendor/model, backend string, PCIe
slot, hostname, or issue ID.

## Tooling and tests

- `scripts/issue270_authority.py` — frozen campaign constants and
  accepted-authority consumption (retained-bytes candidate derivation,
  reference consumption, fixture ladder, namespace/case discipline).
- `scripts/issue270_comparator.py` — self-contained comparator/2
  semantics re-declaration plus arm/pair/determinism/inertness
  validators (byte-bound row custody).
- `scripts/issue270_physical.py` — Phase-0 reconciliation, fresh host
  observation and drift fail-closed, live dispatch authority, binary/
  model authentication.
- `scripts/issue270_terminal.py` — Phase-1 freeze, Phase-2 selector
  binding, Phase-4 mechanical terminal reducer.
- `tests/test_issue270_authority.py` — 55 CPU-only offline tests:
  retained-bytes derivation both directions, main-constant cross-
  bindings, discipline probes, comparator mutation matrix, Phase-0/1/2
  fail-closed paths, dispatch authority, and the full terminal pipeline
  over synthetic-but-custody-real evidence.

```sh
.venv/bin/python -m unittest tests.test_issue270_authority -v
```

Tests exercise repository fixtures only and establish no physical
result; physical execution remains blocked until the maintainer
exact-head dispatch above.
