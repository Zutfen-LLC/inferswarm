# Campaign validation gate ordering (Issue #213)

Normative rule for how a physical/research campaign schedules validation
around adversarial review. This document is the single repository-owned
authority for campaign handoff gate ordering; campaign issues and review
prompts must not restate a different order. The machine-checked model and
exact-head suite receipts live in
[`scripts/issue213_gate_orchestration.py`](../scripts/issue213_gate_orchestration.py)
with focused tests in
[`tests/test_issue213_campaign_gate_ordering.py`](../tests/test_issue213_campaign_gate_ordering.py).

This is orchestration doctrine only. It changes **ordering and
deduplication**, never test semantics, exact-head correctness guarantees, or
#148 CI impact planning — the planner and the `CI Gate` remain authoritative
for what CI runs.

## Motivation (observed in #210 / PR #212)

The pre-#213 convention ran expensive validation in this order:

```text
full CPU suite -> hosted exact-head CI -> adversarial exact-head reviews
-> review-driven fixes -> full CPU suite AGAIN -> hosted exact-head CI AGAIN
```

In PR #212 this cost two full-suite runs (2,759 tests each) and two hosted CI
runs where one of each would have carried the same guarantee, because the
review lanes returned GO with only P3 findings and the fixes created a new
head — voiding the first exact-head results. The redundancy is structural,
not accidental: any post-review commit invalidates pre-review exact-head
validation by design, so running it before review wastes it whenever review
mutates the head.

## Canonical ordering

```text
PRE-REVIEW PHASE (cheap, reviewer-trust gates only)
  focused/affected-surface tests
  campaign reducer + negative-control tests
  accepted-predecessor evidence verifiers / preservation checks
  evidence manifest checks
  physical authority / discovery / topology validation
  prospective correctness/authority freeze checks
  finalizer/status pre-review integrity checks
  CI planner self-check (where touched)
-> ADVERSARIAL EXACT-HEAD REVIEWS (read-only, against the frozen head)
-> APPLY ALL ACCEPTED REVIEW FIXES (focused checks re-run as needed)
-> FINAL-HEAD PHASE (exactly once, on the final reviewed head)
  one full CPU suite
  one hosted exact-head CI
  finalizer/status fixed-point checks
-> HANDOFF
```

Invariants:

1. Nothing is deleted or weakened; tests and thresholds are unchanged.
2. Final handoff still requires a full CPU suite on the final exact head
   wherever current policy requires it.
3. Final handoff still requires hosted CI SUCCESS on the final exact head
   wherever current policy requires it. Review GO verdicts are necessary but
   never sufficient (enforced by `handoff_gate_status`).
4. Review-driven changes invalidate prior exact-head validation exactly as
   today; the optimization is ordering, not exemption.
5. Every check that reviewers need to trust the head (invariant 5 of the
   issue) still runs BEFORE review — the pre-review list above is unchanged
   from campaign doctrine; only the full suite and hosted CI moved.
6. A pre-review full suite or hosted CI run remains allowed ONLY when a
   campaign explicitly declares it **review-critical** (a review lane
   genuinely requires that result as an input) or repository policy names a
   concrete reason. Declaration is per-campaign, per-gate, and recorded in
   the campaign plan; it never becomes a default.
7. Unknown gates, malformed plans, or ambiguous workflow state fail closed
   to the existing broader validation (a fresh full-suite + hosted-CI run).
8. A post-final-suite review, where a campaign requires one, is read-only.
   Any resulting mutation creates a new final head and legitimately
   re-triggers final validation.

## Review workflow semantics (Phase 4)

Adversarial review lanes verify the correctness/evidence surfaces assigned
to the lane, mechanically, against the frozen review head. Lanes must not:

- require or re-run the full CPU suite or hosted CI unless the campaign
  declared that gate review-critical for that lane;
- re-run unrelated campaign gates;

and each lane returns findings against the frozen head. After all lanes
complete, the maintainer/agent applies accepted fixes, then the single
final expensive validation cycle runs. If a lane needs assurance that
focused tests or campaign reducers are green before review, the campaign
names those narrower gates in the pre-review phase — they are cheap and
already in the canonical list.

## Duplicate-launch prevention (Phase 2)

One logical final-head full-suite request launches at most one suite process
for that head/configuration on a host. A cooperative single-launch lock
(``LaunchLock`` in the orchestration module) implements this:

- the first request acquires the lock and owns the launch;
- a concurrent duplicate request **attaches** (waits on the existing
  process) rather than starting a second suite;
- polling always attaches to the existing process;
- a stale lock (holder process gone) is pruned and retaken;
- a malformed lock, or a lock held by a different suite configuration,
  fails closed — no second launch.

The #210 session's two successive `run_full_cpu_suite.py --json`
appearances were audited (session record, 2026-09-17): they were **two real
suites on two different heads** (323ef49 and 0059731) — the first correctly
failed on a missing #184 allowlist entry, a fix landed, and the second run
validated the corrected head. They were not one run plus polling; each run
was individually legitimate under then-current convention. The waste was
the *convention* (validating a head that review was about to mutate), which
this doctrine removes, not a phantom duplicate-launch bug.

## Exact-head suite receipt (Phase 3)

The runner already proves serial/executed identity equality; the receipt is
the smallest record binding a PASS to its exact identity:

| Field | Source |
|---|---|
| `git_commit_sha` | `git rev-parse HEAD`, clean tree enforced |
| `suite` | runner schema, canonical command, serial + executed identity digests, count |
| `environment` | sha256 of each environment authority file (`requirements-test.txt`, bootstrap, doctor) |
| `result` | `PASS` only |
| `started_unix` / `ended_unix` | positive duration required |

Reuse rules (all fail closed): head drift, suite-configuration drift, or
environment/dependency drift invalidates reuse and requires a fresh run; a
failed/cancelled/incomplete receipt can never satisfy the gate; no receipt
may be presented as current if its exact-head binding cannot be proven
(schema check + full identity match). Receipts are advisory deduplication
metadata for orchestration, **not** accepted scientific evidence and not a
persistent cache — campaigns that must retain validation evidence retain it
through the existing evidence lifecycle, not through receipts.

## Phase 0 audit — gate classification at the time of adoption

| Source | Gate | Classification |
|---|---|---|
| `CONTRIBUTING.md` (local checks) | full CPU suite before PR | FINAL_HEAD_REQUIRED (unchanged; it is the pre-handoff local run, not a pre-review convention) |
| `docs/ci-impact-planning.md` | full regression locally, planner, CI Gate | NOT_APPLICABLE (tooling docs: how to run, not when relative to review) |
| `tests/README.md` | suite invocation docs | NOT_APPLICABLE (same) |
| `AGENTS.md` + `docs/status-maintenance.md` | status sync in same PR, finalizer | PRE_REVIEW_REQUIRED (repository-consistency checks) |
| `docs/evidence-manifests.md` + campaign MANIFEST tools | manifest checks | PRE_REVIEW_REQUIRED |
| Campaign issues' handoff checklists (e.g. #210 §report items) | full CPU suite + hosted CI on final head | FINAL_HEAD_REQUIRED |
| #210/PR #212 observed practice | full suite + hosted CI BEFORE review, both re-run after review fixes | REDUNDANT_CURRENTLY (the pattern this issue eliminates) |
| Freeze-ordering rules (authority before observation) | prospective freeze checks | PRE_REVIEW_REQUIRED |
| #148 planner / `CI Gate` | impact-selected CI | NOT_APPLICABLE (authoritative; untouched) |
| Adversarial review prompts (delegate lanes) | mechanical lane verification | PRE_REVIEW_REQUIRED (the lanes themselves); requiring full-suite/CI results in a lane is BOTH_WITH_JUSTIFICATION (only with a review-critical declaration) |

Historical evidence, terminals, and manifests are untouched by this
reclassification — the audit classifies guidance, not retained bytes.

## Non-goals

No test deletion, no weakening of exact-head validation, no skipped final
hosted CI, no change to qualification thresholds, no alteration of accepted
evidence, no redesign of #148 group selection, no general build cache, and
no agent-implementation authority: these semantics are repository-owned and
agent-independent.
