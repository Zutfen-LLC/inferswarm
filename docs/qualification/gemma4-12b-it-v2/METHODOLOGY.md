# Gemma 4-12B-IT heterogeneous numerical qualification — methodology v2

## Status

```
METHODOLOGY_V2_DRAFT — NOT YET ACCEPTED
(derived from accepted issue #74 v1 methodology at inferswarm@f394dc9;
rationale: observed v1 Phase-0 stop, InferSwarm issue #76)
```

Historical R6 remains permanently `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`.
The v1 qualification methodology (issue #74, merged at `f394dc9`) is retained
unchanged at `docs/qualification/gemma4-12b-it-v1/` and remains accepted
historical evidence. This v2 area is a **new prospective methodology
version**, not an in-place reinterpretation of v1.

## Why v2 exists (from the v1 Phase-0 stop, issue #76)

The v1 campaign (execution PR Zutfen-LLC/FreeToken#28, physical producer
`29e04d0`) completed its Phase-0 reference-only run validly on the RTX 3090
reference: all 48 frozen v1 stress-pool cases, 8 greedy tokens each, zero
NaN/Inf, no heterogeneous candidate execution, holdout sealed. The producer
pre-registered, before the reference run:

```
positive_top1_margin(case)
=
min over all 8 greedy steps of
fp32(top1_logit - top2_logit)
```

Under that definition, 5 of the 48 v1 pool cases have margin exactly 0
(bit-identical fp32 logits for distinct token ids at one greedy step). The
frozen v1 selector treats the existence of ANY nonpositive-margin pool case
as fatal to the entire selection, so v1 stress selection could not complete
validly, and the campaign stopped before candidate execution per the issue's
own barrier. That stop is legitimate and retained; the v1 reference evidence
remains historical evidence (it informs why v2 exists but must NOT determine
the v2 selected cases).

## Maintainer decision 1 — margin definition (FROZEN, UNCHANGED)

The pre-registered margin formula is retained verbatim:

```
positive_top1_margin(case)
=
min over all 8 greedy steps of
fp32(top1_logit - top2_logit)
```

This is the most semantically conservative definition (it asks whether the
prompt ever reaches a fragile greedy decision). The five exact-zero cases in
the v1 run are legitimate observed evidence, not a bug in FreeToken,
InferSwarm, the GPU, or the qualification subject. Post-observation
alternatives (step 0, any single step, max, mean, median, min over capture
positions only) are all REJECTED as results-informed methodology selection;
the v2 selector machine-rejects any margin-definition drift (see
`tests/test_issue76_v2_stress_selection.py`).

## Maintainer decision 2 — selector defect and v2 fix

The defect is narrower than the margin definition: the frozen v1 selector
makes the existence of any nonpositive-margin pool case fatal to the entire
selection. The intended stress concept — smallest positive margins and
largest positive margins — is preserved, with stress-pool eligibility fixed
prospectively:

1. a fresh stress candidate pool is generated from a new prospectively
   frozen seed (`inferswarm-issue-76-stress-pool-v2`, generator
   `scripts/generate_issue76_stress_pool_v2.py` — v1 generation machinery
   unchanged: same lexemes, RNG construction, exact-token-count loop,
   tokenizer profile);
2. the matched reference-only run is executed (NOT yet authorized — this
   freeze precedes it);
3. the unchanged `min-over-8` margin is calculated per case;
4. a pool case is stress-selection-eligible only when:

```
margin is finite AND margin > 0
```

   The eligibility rule is exactly: eligible iff the margin is finite and
   strictly `> 0`; a FINITE margin `<= 0` (an exact tie at 0.0 or a finite
   negative value) makes the case INELIGIBLE; a NON-FINITE margin (NaN,
   +Inf, -Inf) is an unconditional reference correctness failure and stops
   selection immediately. A non-finite reference value means the reference
   correctness path produced invalid numerical output (ADR 0010 / accepted
   #74 correctness semantics) — it is NOT merely another ineligible
   category, it is never converted into an ineligible case count, and it is
   never silently ignored;

5. finite zero/nonpositive cases are retained as reference evidence but are
   INELIGIBLE, not a fatal pool-wide error;
6. at least 8 eligible cases are required (fail closed otherwise);
7. from eligible cases exactly four smallest positive margins and four
   largest positive margins are selected (deterministic tie-break by
   case_id);
8. every reference-margin row is bound to the exact frozen case identity:
   the row's `case_id` must exist in the frozen v2 pool AND its
   `case_sha256` must equal the frozen pool case's `case_sha256`; unknown
   case IDs, missing or malformed case hashes, correct-ID-wrong-hash rows,
   swapped hashes, duplicate/substituted rows, and incomplete pool coverage
   are all rejected. The valid path establishes the full chain
   reference-margin summary -> exact v2 pool SHA -> exact case-ID set ->
   exact `case_id -> case_sha256` mapping -> margin value;
9. the selected 8-case manifest is frozen/committed before any
   heterogeneous candidate execution.

The v1 observed 48-case pool and its observed margins are explicitly
forbidden as selection inputs for v2 (enforced in the pool provenance and
the commitment).

## Frozen v2 artifacts (this directory)

| artifact | sha256 |
|---|---|
| `manifests/margin-stress-pool.json` (48 cases, seed `inferswarm-issue-76-stress-pool-v2`) | `533b32857721b3f99243e5695bc18b24960cbd3c80692d626154907d6ecbd7c9` |
| `manifests/margin-stress-selection-commitment.json` | `04421a6f19f6338a340dfea296214509eae3adc5ca32067dfd76880ab1cacba0` |
| selector program `scripts/select_issue76_margin_stress_v2.py` | `e32e8672671c3b3ec6b47e3b119c66fd54e2c5a62ba72fb2ec2288764508beab` |
| generator program `scripts/generate_issue76_stress_pool_v2.py` | recorded in pool `generator_sha256` |

Pool provenance verified: 48 cases, 2 per cell, all 24 content-class x
length-regime cells covered, case ids `p76-01-01-01` … `p76-04-06-02`,
token-id disjoint from the v1 stress pool AND the unchanged 576-case
calibration corpus.

## Unchanged from v1 (explicit)

- qualification subject, model/checkpoint identities, BF16 execution,
  Triton attention path, deterministic greedy replay-prefill, one-chunk
  geometry;
- architecture and ADR 0010 (three conjunctive correctness layers);
- the 576-case statistical calibration corpus (unchanged unless a concrete
  methodology dependency requires otherwise — none identified);
- 15 mandatory numerical envelopes, three metrics per family, nearest-rank
  p99, host-float64 reducer (`REDUCER.md` v1 remains normative);
- statistical target p=0.99, familywise 0.95, Bonferroni 15, distribution-
  free maximum-order-statistic tolerance limit, n=568/576 design;
- semantic profile, holdout acceptance contract (see below);
- historical `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`.

## Holdout disposition — Branch A: original holdout RETAINED

Custody investigation verdict: `FOUND_VERIFIED` (2026-09-03). The original
#74 recipient private key and secret seed were recovered by the maintainer
from the original sealing laptop and verified cryptographically against the
committed recipient certificate WITHOUT unsealing the holdout:
public-key DER hash match `f0a89fea…f8693`; secret-seed sha256 matches the
committed `secret_seed_sha256` (`2ddb4196…24d8`). See
`manifests/holdout-custody-record.json` for custodian metadata (no private
material).

Adjudication (default disposition adopted): the existing sealed v1 holdout
REMAINS APPLICABLE to v2, unchanged and unopened, because v2 changes ONLY
stress-case calibration selection (pool seed + eligibility rule) and does
NOT change: the qualification subject, the target population, the numerical
envelopes, the reducer, the semantic profile, or the holdout acceptance
contract. The holdout cases are cell-stratified and disjoint from both the
v1 and v2 stress pools. This disjointness is MECHANICALLY VERIFIED from the
PUBLIC holdout commitment
(`docs/qualification/gemma4-12b-it-v1/manifests/sealed-holdout-commitment.json`),
not merely inferred from the independent seed/namespace: the v2 stress
pool's `prompt_sha256` set has zero intersection with the holdout
commitment's per-case `prompt_sha256` set, and the v2 `token_ids_sha256`
set has zero intersection with the holdout commitment's `token_ids_sha256`
set (machine-checked in
`tests/test_issue76_v2_stress_selection.py::TestV2StressPoolFrozen::test_pool_is_disjoint_from_public_holdout_commitment`).
No holdout plaintext is required or consulted for this proof — only the
already-public commitment hashes. The independent sealed namespace/seed
remains additional provenance.

Preserved exactly: encrypted CMS bytes, certificate, ciphertext sha256
`23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59`, secret
seed commitment, `SEALED_NOT_CONSUMED` state.

Custody improved before any further physical execution: two recorded
custodian copies of the SAME key (orchestrator
`~/.local/share/inferswarm/issue74-holdout-v1/`, and inferswarm00
`/srv/inferswarm/state/issue74-holdout-custody/`), both verified against
the committed certificate, restrictive permissions, never committed. The
methodology fails closed (`HOLDOUT_CUSTODY_BLOCKED`) if both custodians
become unavailable. No fresh v2 holdout is created; no key was regenerated;
no re-sealing occurred.

## Prohibitions (machine-enforced where possible)

- v1 observed margins MUST NOT be used to select v2 cases (pool provenance
  + commitment);
- v1 pool case ids MUST NOT appear in the v2 pool (disjointness test);
- margin formula changes are rejected by the v2 selector;
- no arbitrary epsilon, no tie-breaking by token id/rank dressed as a
  positive margin; a tie IS a zero margin;
- no modification of model execution math to eliminate ties;
- v1 artifacts (pool, commitment, selector, holdout, evidence) are
  immutable historical evidence.

## Not yet authorized

- the v2 Phase-0 reference-only run over the frozen v2 pool;
- any heterogeneous (3060-chain) candidate execution;
- threshold derivation;
- holdout consumption.

This methodology must be reviewed and accepted by the maintainer before any
of the above. Physical execution for v2 requires its own prospective
producer chronology (fresh producer branch/SHA; the v1 harness may be
reused only if code-identical and revalidated).
