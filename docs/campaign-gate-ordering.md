# Campaign validation gate ordering (Issues #213 / #224)

Normative rule for how a physical/research campaign schedules validation
around independent review. This document is the single repository-owned
authority for campaign handoff gate ordering and review authority;
campaign issues and review prompts must not restate a different order.
The machine-checked model and exact-head suite receipts live in
[`scripts/issue213_gate_orchestration.py`](../scripts/issue213_gate_orchestration.py)
with focused tests in
[`tests/test_issue213_campaign_gate_ordering.py`](../tests/test_issue213_campaign_gate_ordering.py).

This is orchestration doctrine only. It changes **ordering and
deduplication**, never test semantics, exact-head correctness guarantees, or
#148 CI impact planning — the planner and the `CI Gate` remain authoritative
for what CI runs.

## Motivation (observed in #210 / PR #212, revised by #224)

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
mutates the head. Issue #213 fixed the ordering.

Issue #224 revises the **review lane default** on top of that ordering: the
two delegated adversarial lanes that #213-era boilerplate made mandatory were
routinely consuming 600–1200 seconds each, often timing out before
structured completion, while the maintainer independently reviewed the
pushed exact head at handoff anyway (concrete trigger: issue #222 / PR #223,
where delegated Lane 2 hit the 1200-second cap after performing its scopes
and the maintainer then performed the authoritative exact-head review before
merge). The assurance actually wanted is **independent review of the exact
proposed head**, not a mandatory count of delegated LLM sessions. The
canonical review authority is therefore now the maintainer exact-head PR
review; delegated agent/LLM adversarial reviews are optional, targeted,
advisory work.

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
-> PUSH EXACT HEAD + OPEN PR
-> INDEPENDENT REVIEW (read-only, against the exact proposed head)
   default authority: MAINTAINER EXACT-HEAD PR REVIEW
   optional advisory: delegated agent/LLM reviews (no default count/timeout)
-> APPLY ALL ACCEPTED REVIEW FIXES (focused checks re-run as needed;
   if the head changes, the maintainer review repeats on the new exact head)
-> FINAL-HEAD PHASE (requirements proven against one final reviewed head)
  one full CPU suite (mandatory; never omitted from a campaign plan)
  one hosted exact-head CI (mandatory; never omitted from a campaign plan)
  finalizer/status fixed-point checks
-> MAINTAINER VERIFIES HEAD DID NOT MOVE + FINAL GATES GREEN -> MERGE
```

A PR may be opened before hosted CI completes. If hosted CI happens to run
before the maintainer GO and the head remains unchanged, the existing #213
exact-head binding/reuse rules may satisfy the final CI requirement; do not
launch a duplicate CI run merely to make it occur chronologically after
review. If review changes the head, old CI is naturally invalidated. The
full CPU suite remains deferred until after maintainer GO unless the
campaign explicitly declares it review-critical.

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
   #213 issue) still runs BEFORE review — the pre-review list above is
   unchanged from campaign doctrine; only the full suite and hosted CI
   moved.
6. A pre-review full suite or hosted CI run remains allowed ONLY when a
   campaign explicitly declares it **review-critical** (an independent
   review genuinely requires that result as an input) or repository policy
   names a concrete reason. Declaration is per-campaign, per-gate, and
   recorded in the campaign plan; it never becomes a default.
7. Unknown gates, malformed plans, or ambiguous workflow state fail closed
   to the existing broader validation (a fresh full-suite + hosted-CI run).
8. A post-final-suite review, where a campaign requires one, is read-only.
   Any resulting mutation creates a new final head and legitimately
   re-triggers final validation.

## Review authority (Issue #224)

### Default required review

One **maintainer exact-head review** of the pushed PR head.

Requirements:

- the reviewer inspects the actual pushed artifact/diff/evidence;
- the review names or otherwise mechanically identifies the exact head
  being reviewed;
- P0/P1 findings block handoff;
- accepted fixes create a new head and require re-review;
- maintainer GO is necessary but not sufficient: the final
  suite/CI/finalizer gates must still pass.

There is deliberately **no repository mechanism** by which the
implementation agent can mint a self-authored `maintainer_review_go=true`
receipt and mechanically satisfy independent review. Maintainer review is
process authority outside the implementation agent's evidence graph; the
machine-checked `handoff_gate_status` remains a purely mechanical decision
over suite/CI/finalizer identity and never consumes a review verdict
(maintainer or delegated) as an input.

### Delegated agent/LLM review (optional by default)

- zero delegated lanes is valid under the default plan;
- there is no default lane count;
- there is no default 600/1200-second review requirement;
- delegated reviews may be requested for a narrow specialist surface when
  useful;
- a campaign may explicitly require one or more delegated reviews only
  when it states a concrete reason that independent specialist review
  materially adds assurance (declared prospectively in the campaign
  issue — never retrofitted to justify a run that already happened);
- optional delegated review timeout/truncation does not block maintainer
  handoff;
- findings from an optional delegated review are still real findings:
  accepted P0/P1 corrections must be resolved if surfaced before handoff;
- do not launch broad duplicate "review the whole campaign" lanes merely
  because historical issues used two lanes.

Examples where a targeted delegated review can still be justified:

- cryptographic/security boundary;
- unusually novel evidence/provenance mechanism;
- destructive migration or irreversible external action;
- specialist runtime/source audit materially outside the maintainer's
  primary review;
- the maintainer explicitly requests a second opinion.

## Review workflow semantics (Phase 4)

Independent review — by default the maintainer exact-head PR review,
optionally plus delegated advisory lanes — verifies the
correctness/evidence surfaces assigned to it, mechanically, against the
exact proposed head. Reviews must not:

- require or re-run the full CPU suite or hosted CI unless the campaign
  declared that gate review-critical for that review;
- re-run unrelated campaign gates;

and each review returns findings against the exact head. After the
maintainer review (and any delegated lanes) complete, the maintainer/agent
applies accepted fixes — if the head changed, the maintainer review
repeats on the new exact head — and then the single final expensive
validation cycle runs. If a review needs assurance that focused tests or
campaign reducers are green before review, the campaign names those
narrower gates in the pre-review phase — they are cheap and already in the
canonical list.

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
**provably bound to the exact committed head**. A clean
`git status --porcelain` census alone does NOT prove that: ignored in-repo
trees (`scratch/`, `tmp/`, `.cache/`, ...) are invisible to that census, so
files below them can be present and executable without being HEAD content.
The mechanical HEAD-binding proof (all fail closed, before identity
derivation, completion lookup, attach, or launch) is:

1. the effective tests directory lives inside the repository root (never
   under `.git`) and is a real directory;
2. the directory itself is not an ignored tree with no committed content
   (`git check-ignore` + the HEAD census below) — an ignored in-repo tree
   can never claim exact-head authority;
3. every test source module the runner's own discovery imports from that
   tree (bytecode writing suppressed so the proof does not dirty the tree)
   appears in the `git ls-tree -r --name-only HEAD -- <tests-dir>` census —
   the census enumerates the committed tree, not the index or worktree, so
   untracked or ignored execution-relevant content can never appear in it;
4. the ordinary clean-worktree prerequisite remains: every TRACKED file is
   byte-identical to `HEAD` (staged, unstaged, and untracked dirtiness all
   refuse).

Together: everything the suite can execute from that tree is tracked at the
exact HEAD and unmodified, so the exact committed head authorizes the
executed contents. An external or unprovable tests tree is **refused** —
never cached as though HEAD authorized its contents. Plain non-Git fixture
roots keep the runner's existing unguarded behavior. The default canonical
`tests/` tree is itself tracked content, so ordinary execution (including
`__pycache__` noise, ignored by rule) is unaffected.

### Retention and reuse policy (smallest safe policy, no artifact cache)

A cached run without retained per-task artifacts cannot silently satisfy a
later `--retain-dir` invocation.  `summary.json` finalization is part of
the guarded **logical request**: the launch owner writes it after the
underlying suite produced the full per-task retained set and *before* the
completion receipt is published and the launch lock is released, so a
successful completion is never observable while the retained artifact
contract is incomplete (there is no post-suite/pre-summary window in
which a second identical request could observe a completion over an
incomplete retained directory).  The runner CLI never writes
`summary.json`; the orchestration seam is its single writer.

- concurrent identical requests with the same retention request may
  deduplicate (exactly one launch; the retained artifacts land once, in
  the one requested directory, complete before any completion is
  observable);
- sequential cached-PASS reuse is **disabled** when satisfying the request
  would omit the requested retained artifacts — an empty (or absent)
  requested directory with an existing completion performs a fresh
  underlying suite run that produces them; reuse is permitted only when
  the requested directory mechanically proves the exact documented
  artifact set (per-task `task-N-modules.json`, `task-N-expected.json`,
  `task-N.json`, `task-N-stdout.txt`, `task-N-stderr.txt` for every task,
  plus `summary.json`);
- a **non-empty directory that is not the exact documented set fails
  closed** with a precise error before any launch: the runner refuses a
  non-empty retain directory, so a fresh launch would only produce a
  misleading "retain directory is not empty" failure while silently
  disabling completion reuse.  Resolve the directory deliberately (or
  point the request at a new empty directory); a fresh retained run
  requires a new empty retain directory;
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

## Machine-checked orchestration (Issue #224 semantics)

The #213 schemas and exact-head receipt machinery are preserved unchanged;
no schema version changed. The `adversarial-review` phase identifier is
retained for compatibility and redefined canonically as the **independent
review phase** (alias `independent-review`), defaulting to maintainer
exact-head PR review. The plan now records `delegated_review_lanes`
(default 0, validated non-negative) and `delegated_review_required: false`
— delegated review is explicitly NOT represented as a mandatory gate, and
`handoff_gate_status` remains the mechanical final-validation decision
over suite/CI/finalizer identity only. Its documentation no longer implies
that delegated review GO is a machine input, and there is no
agent-self-asserted review receipt anywhere in the module.

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
| Independent review (Issue #224: maintainer exact-head PR review by default; delegated lanes optional) | mechanical review of the pushed exact head | PRE_REVIEW_REQUIRED (the review itself); requiring full-suite/CI results in a review is BOTH_WITH_JUSTIFICATION (only with a review-critical declaration) |

Historical evidence, terminals, and manifests are untouched by this
reclassification — the audit classifies guidance, not retained bytes.

## Non-goals

No test deletion, no weakening of exact-head validation, no skipped final
hosted CI, no change to qualification thresholds, no alteration of accepted
evidence, no redesign of #148 group selection, no general build cache, and
no agent-implementation authority: these semantics are repository-owned and
agent-independent.
