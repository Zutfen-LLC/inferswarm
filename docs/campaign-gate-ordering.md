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
-> FINAL-HEAD PHASE (requirements proven against one final reviewed head)
  one full CPU suite (mandatory; never omitted from a campaign plan)
  one hosted exact-head CI (mandatory; never omitted from a campaign plan)
  finalizer/status fixed-point checks
-> HANDOFF
```

Invariants:

1. Nothing is deleted or weakened; tests and thresholds are unchanged.
2. Final handoff still requires a full CPU suite on the final exact head
   wherever current policy requires it — and for campaign handoffs
   governed by this doctrine the full-suite and hosted-CI gates are
   MANDATORY plan members: a plan omitting either (including an empty
   final-head phase) fails closed, with no caller-supplied bypass.
3. Final handoff still requires hosted CI SUCCESS on the final exact head
   wherever current policy requires it, proven through a structured
   exact-head status. Review GO verdicts are necessary but never
   sufficient (enforced by `handoff_gate_status`).
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
for that `(head, suite configuration, environment authority)` identity on a
host. The guard (`LaunchGuard` + `run_single_head_suite` in the orchestration
module) is integrated into the **canonical invocation path**: the
`run_full_cpu_suite.py` CLI itself delegates through `run_single_head_suite`,
so direct legitimate invocation cannot bypass single-launch behavior.

### The normalized suite configuration (identity-bearing)

`suite configuration` means exactly one structured object — the runner's
`suite_config` (`suite-config/1`) — never a bare test-count/digest proxy:

| Field | Meaning |
|---|---|
| `tests_dir` | effective tests directory (repo-relative posix path); the identity derives from the SAME directory execution uses |
| `jobs` | effective/selected worker count from the runner's deterministic plan of the exact `(root, tests_dir, requested jobs)` |
| `plan_digest` | sha256 of the deterministic phased task plan (task order, phase, TMPDIR mode, module assignment) |
| `timeout` | per-task timeout in seconds |
| `retain_dir` | the retention request: `null` or the resolved requested directory |

Identity binds the **effective** schedule, not the requested label: default
jobs and explicit `--jobs 1` are distinguishable exactly when their effective
schedules differ (identical effective configurations deduplicate normally).
The task-plan digest makes schedule drift mechanically unforgeable.

**Identity-bearing runner options**: `--tests-dir`, `--jobs` (through the
plan-derived schedule), `--timeout`, `--retain-dir`. All other runner options
are either non-execution-bearing (display: `--json`, `--list/--plan`) or
internal worker plumbing not part of the public request.

### Custom tests-directory rules (fail closed)

`--tests-dir` restores the pre-#213 execution contract
(`run_suite(root, tests_dir, ...)`): the guarded path executes the requested
tests tree and derives its launch identity from the SAME effective tests
directory; a custom directory is never silently normalized back to
`root/tests`. For a Git-backed guarded request the tests tree must be
**provably bound to the exact committed head**: it must live inside the
repository root (never under `.git`) and be a real directory. Combined with
the clean-worktree prerequisite, every file under it is tracked and
byte-identical to `HEAD`. An external or unprovable tests tree is **refused**
— never cached as though HEAD authorized its contents. Plain non-Git fixture
roots keep the runner's existing unguarded behavior.

### Retention and reuse policy (smallest safe policy, no artifact cache)

A cached run without retained per-task artifacts cannot silently satisfy a
later `--retain-dir` invocation:

- concurrent identical requests with the same retention request may
  deduplicate (exactly one launch; the retained artifacts land once, in the
  one requested directory);
- sequential cached-PASS reuse is **disabled** when satisfying the request
  would omit the requested retained artifacts — the request performs a fresh
  underlying suite run unless the exact documented artifact set is
  mechanically proven present and compatible in the requested directory
  (per-task `task-N-modules.json`, `task-N-expected.json`, `task-N.json`,
  `task-N-stdout.txt`, `task-N-stderr.txt` for every task, plus the CLI's
  `summary.json`);
- this is a presence check against the exact retained set — **no
  generalized artifact cache** is built.

### Launch identity and guard mechanics

- the launch identity key is **derived mechanically** — exact repository
  SHA + canonical suite population identity (the runner's own plan digest
  and count) + the normalized suite configuration + environment authority
  hashes. An arbitrary caller-supplied lock key is never accepted as
  authority;
- a **clean committed worktree is a prerequisite to the launch identity
  itself**: every guarded canonical full-suite request in a Git checkout
  establishes a clean committed worktree (the runner's own
  `ensure_clean_git_worktree` doctrine — the same `git status --porcelain`
  census and the same fail-closed behavior on git-status failure inside a
  real work tree) BEFORE deriving a reusable launch identity, consulting
  an existing completion, attaching to an existing launch, or launching
  the suite. A dirty worktree is **refused**, never treated as merely
  another cache-key component: the runner contract requires a committed
  exact head, so a dirty tree cannot reuse a prior clean-head completion
  or bypass the runner's fail-closed dirty-tree check. Plain non-Git
  fixture roots keep the runner's existing unguarded behavior;
- the first request wins an atomic `O_CREAT | O_EXCL` lock creation and
  owns the single launch; concurrent losers of the create race re-read and
  **attach**, waiting on the owner's bounded completion receipt instead of
  starting a second suite (race-safe for truly concurrent starters);
- the lock records the PID of the process that actually invokes the suite,
  never a parent that could exit while an untracked suite child remains;
- a stale holder is replaced only when **mechanically proven dead**
  (`os.kill(pid, 0)` → `ESRCH`); a holder alive past the suite wall or a
  malformed/unreadable lock fails closed — no second launch;
- the owner writes a bounded completion receipt (validated shape, capped
  liveness) that concurrent and immediately-following identical requests
  consume; distinct head/config/environment identities derive distinct keys
  and never share results. This is bounded local state, not a generalized
  persistent build cache;
- a completion receipt is **mechanically validated against the launch
  identity** before it can suppress an actual suite launch: matching key
  and SHA alone never authorize reuse. The embedded `result` must be a
  canonical runner result (known full-suite runner schema, real boolean
  `ok`, positive integer count, valid 64-hex serial/executed digests),
  its outcome must agree with the record's top-level `ok` flag, and a
  PASS additionally requires serial digest == executed digest, a count
  exactly equal to the launch identity's suite count, digests exactly
  equal to the launch identity's suite population digest, AND a suite
  configuration exactly equal to the launch identity's configuration
  (a completion produced under different jobs/tests/timeout/retention
  inputs can never suppress this request's launch). Malformed,
  missing, or forged result fields fail closed — an incomplete result
  such as `{"ok": true}` can never suppress a fresh suite;
- a completed FAIL is delivered only to requests that already attached to
  the live launch (the single real result of the one underlying launch);
  it is never interpreted as a reusable PASS. A later independent
  invocation after a completed FAIL **reruns** the suite — a failure
  never suppresses a fresh launch;
- if the underlying suite raises, no completion is written: waiters fail
  closed and the next identical request launches fresh.

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
| `git_commit_sha` | `git rev-parse HEAD`, clean tree enforced, exact 40-hex shape |
| `suite` | runner schema (must be the known runner schema), canonical command, the normalized suite configuration (`suite-config/1`), serial + executed identity digests (hex, equal), positive count |
| `environment` | sha256 of each environment authority file — the complete required set, exactly (missing or unknown keys rejected) |
| `result` | `PASS` only |
| `count` | positive integer, consistent with the suite count |
| `started_unix` / `ended_unix` | positive duration required |

Validation is **structural and fail-closed**, never arbitrary
nested-dictionary equality: unknown schema, non-canonical command,
malformed digest shapes, serial/executed inequality, non-positive or
inconsistent counts, incomplete or unknown environment authority keys,
malformed SHA shape, and non-positive durations all reject. Reuse rules
(all fail closed): head drift, suite-configuration drift, or
environment/dependency drift invalidates reuse and requires a fresh run; a
failed/cancelled/incomplete receipt can never satisfy the gate; no receipt
may be presented as current if its exact-head binding cannot be proven.
Receipts are advisory deduplication metadata for orchestration, **not**
accepted scientific evidence and not a persistent cache — campaigns that
must retain validation evidence retain it through the existing evidence
lifecycle, not through receipts.

## Independently bound final handoff (exact-head means exact-head)

`handoff_gate_status` takes an **independently derived**
`FinalHeadRequest` — the current/final head identity derived from the
repository itself (`current_final_head_request`: clean tree, `git
rev-parse HEAD`, the runner's canonical plan of that tree under the
**canonical final-head suite configuration**, environment authority
hashes) — and never identity extracted from the receipt under
validation. The canonical final validation configuration is: default
tests directory (`root/tests`), default jobs schedule, default per-task
timeout (1800 s), no retained-artifact request. Because the normalized
suite configuration is part of the request identity, a suite run under a
different jobs/tests/timeout/retention configuration can never satisfy
the canonical final-head request even when it discovers the same test
IDs. Both final gates must bind to that one exact SHA:

- the suite receipt must validate (structurally, per above) against the
  final-head request identity;
- hosted-CI success must present a **structured status receipt**
  (`hosted-ci-exact-head-status/1`: exact `git_commit_sha`, `SUCCESS`
  result, nonempty run identity, optional run URL). A bare unbound
  boolean can never complete handoff; malformed or missing CI identity
  rejects.

Handoff is therefore impossible when the suite receipt is from SHA A and
the final head is SHA B, when the CI SUCCESS is from SHA A and the final
head is SHA B, when suite and CI are individually valid but bound to
different SHAs, or when either identity is malformed or incomplete.

## Review-critical reuse and accounting terminology

A review-critical expensive gate that ran pre-review is **stale** when
review mutates the head — it runs again on the new final head. When review
does **not** mutate the head, its exact-head result satisfies the final
requirement through mechanically validated reuse: no duplicate-phase error,
no second physical execution. The final-head plan records this explicitly:
`requirements` names what must be *proven* against the final head, `gates`
names what is *physically executed* there, and `reuse_satisfied_final`
lists requirements discharged by a validated pre-review result.

Accounting is mechanically distinct:

- `expensive_gate_executions` counts PHYSICAL expensive-gate executions;
- `final_validation_cycles` counts complete final validation CYCLES — one
  normal cycle is ONE cycle containing the full suite AND hosted CI proven
  against one final head.

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
