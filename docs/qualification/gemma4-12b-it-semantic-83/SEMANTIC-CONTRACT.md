# Heterogeneous greedy semantic-output contract (issue #83)

Status: **Proposed doctrine supplement** (research adjudication; adoption
pending maintainer acceptance of this issue's PR; revised 2026-09-04 by
the PR #85 hardening pass that separates mandatory full-vocabulary
numerical qualification from supplemental decision-local semantic
stability)

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

Diagnostic implication, stated narrowly: #81 shows that full-vocabulary
max-absolute error can be a weak predictor of greedy decision stability
because large errors occurred in low-logit tails. This is an observation
about the predictive power of one metric for one kind of decision claim. It
is NOT a statement that the full-vocabulary numerical correctness domain
should be replaced by top-k or by any decision-local domain: broad
numerical execution equivalence over the entire vocabulary remains a
mandatory qualification envelope (`E_full`, §3.1), unchanged by this
contract. What the observation does motivate is an additional, separately
qualified decision-local semantic bound (`E_D`, §3.2) that can certify
decision stability in regimes where the full-domain envelope is too loose
to distinguish stable from unstable decisions. The numerical layer and the
semantic layer are distinct (§3.1/§3.2); neither replaces the other.

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

## 3. Two envelopes and the decision-stability theorems

This section separates two distinct concepts that the first draft of this
contract conflated under a single `E`:

1. the **mandatory full-vocabulary numerical bound** `E_full` (§3.1), and
2. the **supplemental decision-local semantic bound** `E_D` on a frozen
   strategy-declared decision domain `D` (§3.2).

`E_D` supplements `E_full`; it never replaces, waives, or substitutes for
it, and a smaller `D` never waives full-vocabulary correctness.

### 3.1 Mandatory full-vocabulary numerical bound `E_full`

```text
E_full = the prospectively qualified FP32 consumer-logit max-absolute
         envelope over the ENTIRE vocabulary
```

`E_full` is the existing correctness-bearing
`fp32-consumer-logits:max-absolute-difference` envelope of the 15-envelope
numerical contract, derived on canonical identical-prefix replay rows by
the frozen calibration methodology. It is **mandatory and not optional**:

- it is not replaced by top-k or by any decision-local domain;
- it continues to prove broad numerical execution equivalence over the
  whole vocabulary;
- a qualification under the decision-stability profile requires the
  mandatory full-vocabulary numerical envelopes — including `E_full` — to
  PASS, exactly as under any other profile.

Nothing in this contract weakens, loosens, or re-scopes any existing
numerical envelope. This restates the standing doctrine (numerical-
equivalence contract §5.4: final-row logits should use the full vocabulary
when practical; a historical/top-k subset can supplement but should not be
the sole qualification domain).

### 3.2 Supplemental decision-local semantic bound `E_D`

If a strategy needs a tighter useful bound for decision stability, it may
prospectively define a separate

```text
E_D = the prospectively qualified max-absolute error bound over a frozen,
      strategy-declared decision domain D ⊆ {0..V−1}
```

satisfying, for both executions,

```text
|candidate_i − reference_i| ≤ E_D   for all i in D
```

`E_D` is a **supplemental semantic-decision bound**, not a substitute for
`E_full`. It is derived under the same prospectively frozen calibration
methodology (same corpus, same same-prefix eligibility), with its own
derivation rule frozen before any candidate result is observed. A
qualification under the decision-stability profile therefore requires
BOTH:

```text
mandatory full-vocabulary numerical envelopes PASS   (numerical layer,
                                                      incl. E_full)
AND
decision-local E_D / containment / stability gate PASS (semantic layer)
```

### 3.3 The theorems (proved, not fitted)

Let:

- `r ∈ R^V` be the reference consumer logits (FP32);
- `a = argmax r` be the reference full-vocabulary greedy winner, with
  `a ∈ D` required (§3.4);
- `b_D` be the reference runner-up within `D` (the best `r[k]`, `k ∈ D`,
  `k ≠ a`);
- `m_D = r[a] − r[b_D]` be the reference top1–top2 margin on `D`;
- `E_D` be the qualified bound on `D` (§3.2).

**Theorem 1 (stability).** If `m_D > 2E_D`, then every candidate satisfying
the bound on `D` has the same argmax over `D` as the reference:
`argmax_D cand = a`.

*Proof.* Let `j ∈ D, j ≠ a`. By definition of the runner-up,
`r[a] − r[j] ≥ m_D`. Then

```text
cand_j − cand_a
<= (r_j + E_D) − (r_a − E_D)
=  −(r_a − r_j) + 2 E_D
<= −m_D + 2 E_D
<  0
```

where the last step uses `m_D > 2E_D`. Therefore `cand_a > cand_j` for all
`j ≠ a` in `D`. ∎

(Note the inequality chain must terminate in `< 0` via `−m_D + 2E_D < 0`;
an earlier draft terminated the chain with a comparison against the
margin instead of establishing negativity of `cand_j − cand_a`, which
did not constitute a proof.)

**Theorem 2 (admissibility — necessity).** If the actual candidate
full-vocabulary winner `j` lies in `D`, then

```text
r[a] − r[j] <= 2 E_D
```

*Proof.* `j` the full-vocabulary argmax of `cand` ⇒ `cand_j ≥ cand_a` ⇒
`r_j + E_D ≥ cand_j ≥ cand_a ≥ r_a − E_D` ⇒ `r_a − r_j ≤ 2E_D`. ∎

The **ambiguity set**

```text
A_ED(r) = { k ∈ D | r[a] − r[k] <= 2 E_D }
```

is the set of reference tokens **not ruled out by the symmetric error
envelope**. Membership in `A_ED(r)` is a *necessary* condition for any
bound-satisfying candidate winner inside `D` (Theorem 2). The set should
not be overstated as "precisely every token that can always be made the
winner": achievability separates into the strict-gap and boundary cases
below.

**Theorem 3 (tightness of the factor 2).** The factor 2 is exact.

(i) *Strict flip below the envelope.* If `m_D < 2E_D`, a bound-satisfying
candidate exists whose strict winner (on `D`, and on the full vocabulary
when `D` is the whole vocabulary) is the runner-up: with
`ε = 2E_D − m_D > 0`, take `r = (0, −m_D)` and
`cand = (−E_D, −m_D + E_D − ε/2)`. Both component errors are within `E_D`
(exactly `E_D` on the first, `E_D − ε/2 ≤ E_D` on the second), and
`cand_2 − cand_1 = ε/2 > 0`, so the argmax flips strictly.

(ii) *Boundary: only a tie.* If `m_D = 2E_D` exactly, no bound-satisfying
candidate can make any `j ≠ a` a *strict* winner (Theorem 1's chain gives
`cand_j − cand_a ≤ −m_D + 2E_D = 0`), but a tie `cand_j = cand_a` is
achievable (`r = (0, −2E_D)`, `cand = (−E_D, −E_D)`). Whether the
candidate actually emits `a` or `j` then depends on the frozen
deterministic tie-break rule (§3.5); the numerical envelope alone does not
guarantee token identity at equality.

(iii) *Above the envelope.* If `m_D > 2E_D`, Theorem 1 forbids every flip
and every tie. ∎

Trichotomy, stated exactly:

- `m_D > 2E_D` ⇒ guaranteed argmax identity, independent of tie-breaking;
- `m_D < 2E_D` ⇒ a strict-flip construction exists (instability is
  certifiable);
- `m_D = 2E_D` ⇒ a tie construction exists and a strict flip does not;
  identity cannot be guaranteed unless the frozen tie-break rule itself
  favors the reference winner. Do not claim "a flip is always achievable
  at equality" — that is true only if the frozen tie-breaking makes it so.

The factor 2 follows from the symmetric max-absolute bound and is not an
empirical fit; the #81 diagnostic (§2.3) found zero violations of it
across all same-prefix rows.

**Requirement on `E_D`.** `E_D` must be the *prospectively qualified* bound
for the applicable strategy/context on the declared domain `D` — derived
by the frozen calibration of the successor methodology (§6), never from
observed #81 values. The descriptive #81 yields in
`issue83_first_divergence.py` output (e.g. 204/624 rows would be certified
stable at E = 1.0) are diagnostics of rule power, not thresholds, and are
not adopted.

### 3.4 Decision-domain containment (fail-closed)

Theorems 1–3 prove argmax behavior **over `D`**. Actual generation emits
the candidate's full-vocabulary winner, and that winner can lie outside
`D`. Proving

```text
argmax_D(candidate) == a
```

does not prove

```text
argmax_full_vocab(candidate) == a
```

unless the actual emitted candidate winner is also known to lie in `D`.
Therefore, for any decision-stability profile using a proper subset `D`:

- **reference containment (precondition):** `a ∈ D` is required. A frozen
  `D` from which the reference winner escapes is invalid for that
  context; the decision cannot be certified on it.
- **candidate containment (fail-closed):** the actual candidate
  full-vocabulary emitted winner `j` must satisfy `j ∈ D`. If
  `j ∉ D`, the semantic gate fails immediately and unconditionally:

  ```text
  DECISION_DOMAIN_ESCAPE
  ```

  This is not classified as "unstable", is not branch-eligible, and is
  not admissible under any ambiguity set. Ambiguity-set membership is
  evaluated against the **actual emitted token** — never against a
  clipped `argmax_D` candidate. The emitted token itself is checked.

Consequently:

> A proper-subset decision domain is valid only for contexts whose
> qualification demonstrates zero decision-domain escapes under the
> frozen method.

**`D` is strategy-owned and frozen prospectively** (before any candidate
result is observed). Acceptable prospective constructions include:

- the full vocabulary (`D = {0..V−1}`; containment is then trivial);
- a frozen union/reference support set;
- another strategy-defined candidate-complete domain;

but #83 does not choose among them; that choice belongs to the successor
methodology and must be mathematically justified prospectively. In
particular, a reference-only top-k domain is **not** automatically safe:
it can exclude a candidate token whose candidate logit is boosted enough
to become the full-vocabulary winner — exactly the
`DECISION_DOMAIN_ESCAPE` failure. And #81 observations must not inform
the choice: no top-k size may be derived from the observed rank-17 case
or from any other #81 statistic; that would be results-informed
methodology design.

### 3.5 Frozen argmax/tie-break semantics

Because exact equality `m_D = 2E_D` can produce ties (Theorem 3(ii)), the
strategy semantic profile must record the **deterministic argmax/tie-break
rule** used by both the reference and the candidate — for example:

- lowest token id wins ties;
- first-index max;
- explicitly frozen backend/framework behavior.

Tie behavior must not be left "implementation-defined" inside a
qualification contract. Qualification applicability includes the frozen
argmax/tie-break semantics whenever ties can affect emitted tokens. If
the reference and candidate tie-breaking rules differ, the semantic
profile is inapplicable (or fails, if the mismatch is discovered during
evaluation). Under the ordinary decision-stability rule, `m_D = 2E_D` is
treated as **unstable** (an ambiguity-set decision) unless a stronger
prospective proof — covering the frozen tie-break rule — says otherwise.

## 4. Autoregressive trajectories: canonical-prefix replay + decision-local gate

The successor contract combines designs A + B from the issue, with C reserved:

1. **Canonical-prefix numerical replay (A).** All numerical-envelope
   qualification compares only checkpoints computed from an identical frozen
   token prefix on both arms (the reference trajectory's prefix). The
   candidate is teacher-forced onto the reference prefix regardless of what
   it would have freely chosen. This keeps every numerical checkpoint
   same-input, which is exactly what #81's retained same-prefix rows already
   are (§2.1). Free-running tensors after a divergence are diagnostic only,
   never calibration- or holdout-bearing numerical evidence. This is the
   substrate on which BOTH `E_full` and `E_D` are derived.
2. **Decision-local semantic gate (B).** At each canonical decision step,
   with `E_D` qualified on the frozen domain `D`, the reference winner
   `a ∈ D`, and `j` = the actual candidate full-vocabulary emitted winner:
   - **containment first:** if `j ∉ D`, the decision fails immediately:
     `DECISION_DOMAIN_ESCAPE` (§3.4);
   - if `m_D > 2E_D` (**stable decision**): `j == a` exactly — a mismatch
     is a semantic failure, with no tolerance;
   - if `m_D ≤ 2E_D` (**unstable decision**, including the equality case
     of §3.5): `j ∈ A_ED(r)`; an emitted token inside `D` but outside the
     ambiguity set is a semantic failure (Theorem 2 makes this checkable
     offline from retained rows);
   - after the first allowed unstable divergence, subsequent free-running
     steps of that case are excluded from same-input semantic evaluation and
     the case is marked `BRANCHED_<...>`; qualification aggregates count
     branches, and any strategy needing post-branch claims uses (3).
   - qualification under this profile additionally requires the mandatory
     full-vocabulary numerical envelopes (including `E_full`) to PASS —
     the semantic gate is a conjunction on top of the numerical layer,
     never a replacement for it (§3.1/§3.2).
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

- **Strict profile (`EXACT_TOKENS_REQUIRED` / `BIT_EXACT_REQUIRED`).** Exact
  greedy-token identity at every step, no ambiguity set, no branch label. A
  candidate context qualifies only through a campaign whose semantic gate is
  exact-token equality; #81 remains the valid FAIL of the first attempt under
  this profile for RTX 3090↔RTX 3060/Gemma/FreeToken. When the operator
  requests strict reproducibility, the planner excludes contexts without an
  applicable strict qualification — same-device-class (or verified
  bit-identical) contexts only, per ADR 0010 §6.
- **Heterogeneous decision-stability profile (this contract).** The
  mandatory numerical envelopes (including full-vocabulary `E_full`) PLUS
  the prospectively frozen semantic triple `(D, E_D, argmax/tie-break rule)`
  with fail-closed containment (§3.4), the Theorem-1/2 gates, and branch
  semantics. This is ordinary heterogeneous correctness; it does not satisfy
  a strict operator request and must not be silently substituted for one.

A strict-profile qualification of context X and a stability-profile
qualification of context Y are separate evidence records. Passing one never
implies the other.

## 6. Prospective calibration/holdout chronology (successor gate outline)

The old circularity (semantic PASS required before threshold derivation,
threshold needed for the semantic rule) is resolved by splitting evidence
kinds, separating the two bounds, and fixing the order:

1. **Freeze the methodology** (this contract + a successor Gemma methodology
   issue): the `D` construction rule, margin definition, `E_full` and `E_D`
   derivation algorithms, corpus generation, containment/escape rule,
   tie-break semantics, semantic gates, branch rules, evidence schemas —
   all before any physical run.
2. **Numerical calibration (calibration-bearing).** Canonical-prefix replay
   over the calibration corpus derives the existing **15 numerical
   envelopes** mechanically — including the full-vocabulary FP32
   consumer-logit `E_full` (`fp32-consumer-logits:
   max-absolute-difference`). If decision stability uses a proper subset
   `D`, the supplemental `E_D` is derived under the same prospectively
   frozen calibration (its derivation rule was frozen in step 1). Only
   same-prefix rows are eligible. No semantic verdict exists yet. `E_D`
   does not replace `fp32-consumer-logits:max-absolute-difference` or any
   of the 15 envelopes.
3. **Threshold-freeze barrier.** The FULL threshold manifest is serialized,
   hashed, committed, pushed and re-fetched byte-identical before any
   semantic evaluation is opened — mirroring the #81 selected-eight
   barrier mechanics. The manifest contains:
   - all 15 normal numerical limits (unchanged in kind; `E_full` among
     them);
   - the `D` identity (construction rule + membership);
   - `E_D`;
   - the frozen argmax/tie-break semantics.
4. **Semantic qualification on calibration (calibration-bearing).** The
   containment and Theorem-1/2 gates run on the same retained calibration
   rows using the frozen `E_D` and frozen tie-break rule. Requirements:
   zero `DECISION_DOMAIN_ESCAPE`; zero inadmissible decisions; every
   stable decision exactly identical; unstable decisions within `A_ED`;
   branches recorded.
5. **Sealed holdout (holdout-bearing).** A fresh, independently generated
   sealed corpus (new commitment; the #74 holdout stays permanently sealed
   and is not reused — its ciphertext `23311c55…` remains sealed
   historical evidence) evaluates, without any tuning:
   - exact integrity;
   - the mandatory full numerical envelopes (incl. `E_full`);
   - decision-domain containment;
   - the stability/ambiguity semantic gate.
   A holdout failure is retained; it does not authorize threshold changes.
6. **Free-running evidence is diagnostic only** unless a C-type contract was
   separately frozen (none exists for Gemma yet).

No step observes candidate results before the method that will judge them is
frozen. #81 is not re-evaluated under this contract; its verdict is terminal.

## 7. Required doctrine updates

Adopted by this PR (maintainer acceptance merges them):

- `docs/architecture/numerical-equivalence-contract.md` §1.3/§5.2/§5.4:
  the two-profile taxonomy (strict exact-token vs decision-stability),
  with the decision-stability profile defined as the supplemental
  `(D, E_D, argmax/tie-break rule)` semantic layer **on top of** the
  unchanged mandatory numerical envelopes including full-vocabulary
  `E_full`, fail-closed `DECISION_DOMAIN_ESCAPE` containment, and §5.4's
  full-vocabulary-when-practical rule restated so the numerical layer and
  the semantic layer no longer appear to conflict. (Edit included in this
  PR.)
- ADR 0010 needs no change: its layer 3 already delegates the semantic
  profile to the strategy and explicitly does not make exact tokens
  universal.
- Fabric Doctrine: no change required now; the main doctrine already defers
  numerical semantics to the ADR-0010 supplement.

## 8. Non-claims

- No claim that #81 passes under any contract; it is not re-evaluated.
- No threshold, tolerance, `E_full`, or `E_D` value is adopted from #81
  observations. The E yields in §2's tooling output are rule-power
  diagnostics only.
- No claim that `E_D` or any decision-local domain can replace, waive, or
  loosen `E_full` or any mandatory numerical envelope; the two are
  conjunctive (§3.2).
- No claim that `A_ED(r)` is "precisely every token that can always be made
  winner": membership is necessary (Theorem 2); strict-flip achievability
  holds for gaps strictly below `2E_D`, and at the boundary only a tie can
  be forced, with the emitted token determined by the frozen tie-break
  rule (§3.3, §3.5).
- No claim that RTX 3090↔RTX 3060 is qualified under the decision-stability
  profile — that requires the successor campaign of §6.
- No claim that decision-local domains are universally superior; domain
  choice is strategy-owned, prospective, and applicability-keyed.
- No holdout unseal, no R6/#76/#81 evidence modification, no new GPU
  campaign from this issue.
- The rank-17 divergence (reference margin exactly 0) shows `A_ED` can be
  large at exact ties; the contract treats exact ties as unstable decisions
  (m = 0 ≤ 2E_D always), which is consistent but must be remembered when
  reading stress pools that deliberately contain ties.

## 9. Successor implementation/qualification gate outline

1. Successor methodology issue (Gemma v3): freeze the `D` construction rule,
   margin definition (reuse `min over steps of fp32(top1−top2)` unless
   re-adjudicated), `E_full` derivation (unchanged 15-envelope method),
   `E_D` derivation (max over same-prefix rows of the declared per-row
   envelope metric on `D`), tie-break semantics, corpus generation,
   semantic gates, branch labels, schemas.
2. Harness deltas (FreeToken research branch, mechanical): teacher-forced
   replay mode on the candidate arm; per-decision retention of the FP32 row
   (full row supports `E_full`; the frozen `D` slice supports `E_D`) on
   both arms; containment-check and ambiguity-set tooling.
3. Campaign per §6; planner integration: `EXACT_TOKENS_REQUIRED` policy
   consumes strict-profile evidence; default heterogeneous mode consumes
   decision-stability evidence (numerical envelopes AND semantic gate);
   exclusion reasons recorded per ADR 0010 §8.
