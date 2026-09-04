# Heterogeneous greedy semantic-output contract (issue #83)

Status: **Proposed doctrine supplement** (research adjudication; adoption
pending maintainer acceptance of this issue's PR)

Date: 2026-09-04

Issue #83 defines the prospective strategy semantic-output contract for
deterministic greedy generation under qualified heterogeneous floating-point
variation, using issue #81 as immutable failed evidence. Nothing here
retroactively repairs #81, R6, #76, or #71, and nothing here derives a
threshold from observed #81 values.

Historical verdicts preserved verbatim:

- #81: `CALIBRATION_SEMANTIC_FAIL` — unchanged.
- R6: `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL` — unchanged.
- The #74/#81 holdout remains sealed (ciphertext sha256 `23311c55…`
  unchanged).

## 1. What #81 falsified and what it did not

#81's exact-token semantic profile required the 3-stage RTX 3060 chain to
commit the same greedy token as the RTX 3090 reference at every step of every
case. It failed: 236/576 statistical cases and 4/8 stress cases flipped at
least one token, deterministically, while exact integrity passed everywhere
and NaN/Inf remained zero.

Accepted #71 evidence localized the numerical cause as
`BACKEND_EXECUTION_LOCAL` BF16 device-class GEMM variation: byte-identical
inputs and weights legally produce 1–2 ULP/GEMM differences that accumulate
across 48 layers. #81 therefore falsified **the first Gemma exact-token
semantic profile for this heterogeneous context**. It did not falsify ADR
0010's three-layer conjunction, transport integrity, planner correctness, or
the heterogeneous fabric architecture.

## 2. First-divergence diagnostic (retained #81 evidence, issue #83 analysis)

All numbers in this section are re-derived by
`scripts/issue83_first_divergence.py` (pure stdlib, fail-closed reproduction
gate) from the committed evidence under `evidence/`; see §2.4.

### 2.1 First divergence occurs only at exactly-shared prefixes

Across all 584 cases, whenever the trajectories differed, the first differing
decision occurred at a step where the reference and candidate token prefixes
were byte-identical (machine-verified per case; `argmax_flips_strictly_before_
first_divergence = 0`). Post-divergence steps of a diverged case are
free-running and are excluded from every numerical-equivalence statistic —
their inputs differ, so tensor comparison there is not a same-input
comparison.

First-divergence step histogram (240 diverged cases): step 0: 62, 1: 52,
2: 33, 3: 38, 4: 23, 5: 19, 6: 11, 7: 2. 154 of 240 first divergences fall at
a harness-captured step (0/1/3/7); the full-vocab FP32 final-row logits for
both arms are retained exactly there.

### 2.2 Same-prefix full-domain error is tail-dominated

Over the 624 same-prefix captured rows (both arms, full 262144-wide FP32
consumer-logit row):

- max-absolute error: p50 = 1.95, p90 = 4.76, p99 = 11.25, max = 14.19;
- never-diverged cases (472 rows): max-absolute error up to 12.17 with **zero**
  argmax flips at captured steps;
- the largest errors concentrate on low-reference-logit vocabulary entries
  (median reference logit at the max-error token ≈ −1.1; the extreme 14.19
  error sits on a token whose reference logit is −9.9), i.e. error mass lives
  far from the decision-relevant head of the distribution.

Diagnostic implication: a full-domain max-absolute envelope is dominated by
vocabulary the decision never consults. A stability rule keyed to full-domain
E certifies almost nothing (E = 14.19 ⇒ 0/624 decisions provably stable), not
because the computation is bad but because the domain is not
decision-relevant. This is an observation about metric–domain mismatch, and
the successor contract (§4) responds by qualifying the envelope **on the
strategy-declared comparison domain** while keeping the rule's mathematics
exact.

### 2.3 Divergent decisions are near-ties under the reference

At the 46 retained first-divergence rows:

- candidate token is the reference top-2 in 40/46 cases; rank 3, 4, 5, 6 and
  17 once each (the rank-17 case has reference margin 0 — an exact tie under
  the reference FP32 row);
- every flip is admissible under the row's own two-token envelope:
  `r[a] − r[j] ≤ err@top1 + err@cand` held 46/46;
- no same-prefix row anywhere violated the §3 stability theorem
  (`theorem1_empirical_violations = 0`): whenever a flip occurred, the
  reference margin was ≤ 2·max(err@top1, err@top2) on that row.

The candidate never invented a token: it selected within the reference's
high-probability head. The flips are exactly the near-tie flips #71's
mechanism predicts.

### 2.4 Evidence identity

- `evidence/first-divergence-statistical.json`,
  `evidence/first-divergence-stress.json` — per-case first-divergence
  records with source sha256 sidecars (reference index
  `9ec1b7…`-bound; every consumed case JSON hashed);
- `evidence/same-prefix-error-metrics.json` — per-(case, step) full-vocab
  max/RMS/p99 errors, top-8 overlap, candidate-argmax rank, with per-row
  sha256 of both arms' FP32 rows;
- `evidence/decision-local-errors.json` — per-row errors at the reference
  top1/top2 and candidate-argmax tokens, reference margin, admissibility
  gap;
- raw row binaries: extracted from the retained #81 captures on
  inferswarm01 (`refphaseD/`) and inferswarm03 (`phaseD-*-laststage/`) into
  `/srv/inferswarm/state/i83-analysis/{ref-rows,chain-rows}/` with
  `ref-row-meta.json`/`chain-row-meta.json` recording per-row sha256
  (verified against the capture-internal record hashes); the underlying
  #81 artifacts under `/srv/inferswarm/state/i81/` were read read-only and
  are unmodified.
- One unreadable retained reference capture (`c74-03-04-02`, truncated zip
  directory) is recorded in `ref-row-meta.json` under `unreadable_captures`
  and excluded; it does not change any count above.

## 3. The decision-stability theorem (proved, not fitted)

Let the reference consumer logits be `r ∈ R^V` (FP32), greedy winner
`a = argmax r`, and suppose both executions satisfy the symmetric bound

```text
|candidate_i − reference_i| ≤ E   for all i in D
```

over a frozen comparison domain `D ⊆ {0..V−1}` with `a ∈ D`. Define the
reference top1–top2 margin on `D` as `m = r[a] − r[b]`, `b` the runner-up
in `D`.

**Theorem 1 (stability).** If `m > 2E`, then every candidate satisfying the
bound has the same argmax over `D` as the reference: `argmax_D cand = a`.

*Proof.* For any `j ∈ D, j ≠ a`: `cand_j − cand_a ≤ (r_j + E) − (r_a − E) =
(r_j − r_a) + 2E ≤ 2E < m`. Hence `cand_a > cand_j` for all `j ≠ a`. ∎

**Theorem 2 (admissibility).** Any candidate argmax `j ∈ D` satisfies
`r[a] − r[j] ≤ 2E`.

*Proof.* `j` argmax of cand ⇒ `cand_j ≥ cand_a` ⇒ `r_j + E ≥ cand_j ≥ cand_a ≥
r_a − E` ⇒ `r_a − r_j ≤ 2E`. ∎

**Theorem 3 (tightness of 2E).** The factor 2 is exact. (i) For any
`m < 2E` a bound-satisfying flip exists: with `ε = 2E − m > 0`, take
`r = (0, −m)` and `cand = (−E, −m + E − ε/2)`. Both component errors equal
`E` and `E − ε/2 ≤ E`, and `cand_2 − cand_1 = ε/2 > 0`, so the argmax
flips. (ii) At `m = 2E` exactly, a flip is impossible (Theorem 1 argument
gives `cand_j ≤ cand_a` for all j) but a candidate tie `cand_j = cand_a` is
achievable (`r = (0, −2E)`, `cand = (−E, −E)`), so token identity is still
not guaranteed — argmax under a tie is implementation-defined. (iii) By
Theorem 1 no bound-satisfying candidate can flip when `m > 2E`. Hence
`m > 2E` is the sharp guarantee threshold and the `m ≤ 2E` instability
classification is exact. ∎

The ambiguity set `A_E(r) = { j ∈ D | r[a] − r[j] ≤ 2E }` is therefore
precisely the set of tokens a bound-satisfying candidate may legally select:
`j ∈ A_E(r)` is necessary (Theorem 2) and, for the top of the set, achievable
(construction in Theorem 3). The factor 2 follows from the symmetric
max-absolute bound and is not an empirical fit; the #81 diagnostic (§2.3)
found zero violations of it across all same-prefix rows.

**Requirement on E.** `E` must be the *prospectively qualified* bound for the
applicable strategy/context on the declared domain `D` — derived by the
frozen calibration of the successor methodology (§6), never from observed
#81 values. The descriptive #81 yields in `issue83_first_divergence.py`
output (e.g. 204/624 rows would be certified stable at E = 1.0) are
diagnostics of rule power, not thresholds.

**Domain choice is strategy-owned and prospective.** The strategy freezes `D`
before candidate results. A full-vocabulary domain is the most conservative
and is preferred when its calibrated E remains decision-relevant; §2.2 shows
for this device pair a full-domain max envelope certifies ~nothing, so the
strategy may instead declare a decision-local domain (e.g. the frozen union of
reference top-k tokens) — but then Theorems 1–3 apply exactly on that `D` and
nowhere else, and the domain-freeze itself becomes applicability-keyed
evidence.

## 4. Autoregressive trajectories: canonical-prefix replay + decision-local gate

The successor contract combines designs A + B from the issue, with C reserved:

1. **Canonical-prefix numerical replay (A).** All numerical-envelope
   qualification compares only checkpoints computed from an identical frozen
   token prefix on both arms (the reference trajectory's prefix). The
   candidate is teacher-forced onto the reference prefix regardless of what
   it would have freely chosen. This keeps every numerical checkpoint
   same-input, which is exactly what #81's retained same-prefix rows already
   are (§2.1). Free-running tensors after a divergence are diagnostic only,
   never calibration- or holdout-bearing numerical evidence.
2. **Decision-local semantic gate (B).** At each canonical decision step,
   with E qualified on domain D:
   - if `m > 2E` (stable decision): exact argmax identity over D is required —
     a mismatch is a semantic failure, with no tolerance;
   - if `m ≤ 2E` (unstable decision): the candidate decision must lie in
     `A_E(r)`; decisions outside the ambiguity set are semantic failures
     (Theorem 2 makes this checkable offline from retained rows);
   - after the first allowed unstable divergence, subsequent free-running
     steps of that case are excluded from same-input semantic evaluation and
     the case is marked `BRANCHED_<...>`; qualification aggregates count
     branches, and any strategy needing post-branch claims uses (3).
3. **Independent free-running comparator (C, optional).** If InferSwarm must
   claim something about complete generated behavior after branching, that
   claim is a separate strategy/task-level contract with its own prospective
   calibration and holdout. It must not reuse same-input tensor envelopes.
   The first Gemma successor does not include C: no free-running semantic
   claim is made beyond branch counting.

Why A+B rather than B alone: without A, a candidate that diverged early would
drag every later comparison into a changed-input regime, silently converting
numerical gates into text-continuation gates. Why B rather than A alone: A
qualifies computation but says nothing about the decisions the operator
actually observes; B restores an exact, checkable semantic requirement that is
stronger than "the tensors were close" and weaker than the falsified
"tokens identical everywhere".

## 5. Relationship to `BIT_EXACT_REQUIRED` / strict reproducibility

Two distinct profiles now exist, and neither weakens the other:

- **Strict profile (`EXACT_TOKENS_REQUIRED` / `BIT_EXACT_REQUIRED`).)** Exact
  greedy-token identity at every step, no ambiguity set, no branch label. A
  candidate context qualifies only through a campaign whose semantic gate is
  exact-token equality; #81 remains the valid FAIL of the first attempt under
  this profile for RTX 3090↔RTX 3060/Gemma/FreeToken. When the operator
  requests strict reproducibility, the planner excludes contexts without an
  applicable strict qualification — same-device-class (or verified
  bit-identical) contexts only, per ADR 0010 §6.
- **Heterogeneous decision-stability profile (this contract).** Qualified
  numerical envelope E on domain D + Theorem-1/2 gates + branch semantics.
  This is ordinary heterogeneous correctness; it does not satisfy a strict
  operator request and must not be silently substituted for one.

A strict-profile qualification of context X and a stability-profile
qualification of context Y are separate evidence records. Passing one never
implies the other.

## 6. Prospective calibration/holdout chronology (successor gate outline)

The old circularity (semantic PASS required before threshold derivation,
threshold needed for the semantic rule) is resolved by splitting evidence
kinds and fixing the order:

1. **Freeze the methodology** (this contract + a successor Gemma methodology
   issue): domains D, margin definition, E-derivation algorithm, corpus
   generation, semantic gates, branch rules, evidence schemas — all before
   any physical run.
2. **Numerical calibration (calibration-bearing).** Canonical-prefix replay
   over the calibration corpus derives E mechanically on D (a max over
   same-prefix per-row envelopes, per the frozen derivation). Only
   same-prefix rows are eligible. No semantic verdict exists yet.
3. **E freeze barrier.** E is serialized, hashed, committed, pushed and
   re-fetched byte-identical before any semantic evaluation is opened —
   mirroring the #81 selected-eight barrier mechanics.
4. **Semantic qualification on calibration (calibration-bearing).** The
   Theorem-1/2 gates run on the same retained calibration rows using the
   frozen E. Requirements: zero inadmissible decisions; every stable
   decision exactly identical; unstable decisions within A_E; branches
   recorded.
5. **Sealed holdout (holdout-bearing).** A fresh, independently generated
   sealed corpus (new commitment; the #74 holdout stays sealed and is not
   reused) evaluates the frozen E + gates without any tuning. A holdout
   failure is retained; it does not authorize threshold changes.
6. **Free-running evidence is diagnostic only** unless a C-type contract was
   separately frozen (none exists for Gemma yet).

No step observes candidate results before the method that will judge them is
frozen. #81 is not re-evaluated under this contract; its verdict is terminal.

## 7. Required doctrine updates

Adopted by this PR (maintainer acceptance merges them):

- `docs/architecture/numerical-equivalence-contract.md` §1.3/§5.2: replace
  the implicit "exact deterministic greedy-token identity" default with the
  two-profile taxonomy (strict exact-token vs decision-stability), and
  reference the Theorem-1/2 gates as the canonical decision-stability
  construction. (Edit included in this PR.)
- ADR 0010 needs no change: its layer 3 already delegates the semantic
  profile to the strategy and explicitly does not make exact tokens
  universal.
- Fabric Doctrine: no change required now; the main doctrine already defers
  numerical semantics to the ADR-0010 supplement.

## 8. Non-claims

- No claim that #81 passes under any contract; it is not re-evaluated.
- No threshold, tolerance, or E value is adopted from #81 observations. The
  E yields in §2's tooling output are rule-power diagnostics only.
- No claim that RTX 3090↔RTX 3060 is qualified under the decision-stability
  profile — that requires the successor campaign of §6.
- No claim that decision-local domains are universally superior; domain
  choice is strategy-owned, prospective, and applicability-keyed.
- No holdout unseal, no R6/#76/#81 evidence modification, no new GPU
  campaign from this issue.
- The rank-17 divergence (reference margin exactly 0) shows A_E can be large
  at exact ties; the contract treats exact ties as unstable decisions
  (m = 0 ≤ 2E always), which is consistent but must be remembered when
  reading stress pools that deliberately contain ties.

## 9. Successor implementation/qualification gate outline

1. Successor methodology issue (Gemma v3): freeze D, margin definition
   (reuse `min over steps of fp32(top1−top2)` unless re-adjudicated), E
   derivation (max over same-prefix rows of the declared per-row envelope
   metric on D), corpus generation, semantic gates, branch labels, schemas.
2. Harness deltas (FreeToken research branch, mechanical): teacher-forced
   replay mode on the candidate arm; per-decision retention of the FP32 row
   (or frozen top-k slice per D) on both arms; ambiguity-set check tooling.
3. Campaign per §6; planner integration: `EXACT_TOKENS_REQUIRED` policy
   consumes strict-profile evidence; default heterogeneous mode consumes
   decision-stability evidence; exclusion reasons recorded per ADR 0010 §8.
