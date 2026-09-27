# METHODOLOGY AMENDMENT 004 — Issue #250 Arm-C terminal authority

Dated: 2026-09-27. Repository-only correction on PR #251; no new physical
execution, inference, holdout access, dispatch, or merge is authorized here.
The frozen `METHODOLOGY.md` and amendments 001–003 remain verbatim historical
records; this amendment supersedes **only** AMENDMENT-003's statement that
five identical C1 `-t 4 -tb 4` rows with varying default threading suffice
for `R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED`, and its restriction that
C2 is available only after a variable C1. Other prospective cost, timeout,
evidence-generation, and Arm-D rules retain their own authority.

## Reason for correction

Issue #250 §C expressly requires comparison between accepted/default CPU
threading and a *mechanically proven serial/single-thread reference regime
covering prompt prefill and first generation*. Its terminal interpretation
localizes CPU parallel execution/order only when default varies **and serial
is deterministic**; when serial also varies, §D is next. The four-thread C1
regime is materially reduced but is not serial. AMENDMENT-003 §3 incorrectly
allowed a C1-deterministic/default-variable result to terminate as LOCALIZED
while recording `single_thread_tested=False`. That conclusion exceeded the
issue's evidence authority, not merely its label or level of confidence.

## Corrected prospective sequence

1. Keep C1 as the frozen bounded intermediate `-t 4 -tb 4` diagnostic:
   retain its full five-identical deterministic proof or first-mismatch
   variable prefix, with the existing CPU-only semantics. Neither completed
   C1 verdict alone can close §C or reach §D. If C1 is incomplete, BLOCKED.
2. With either completed C1 verdict (deterministic **or** variable), absent
   serial C2 evidence means `R8I3B_REDUCER_BLOCKED_INCOMPLETE` and no
   terminal. Retain the C1 verdict and explicit C2 gate/execution status.
   Never issue LOCALIZED for a four-thread-only boundary or UNRESOLVED on
   a missing mandatory serial comparison.
3. C2 remains a separate, expensive, **non-automatic** `-t 1 -tb 1`
   discriminator. It requires a fresh maintainer exact-head dispatch scoped
   precisely to `d250-arm-c2` / `C2-serial` with the literal
   `c2-serial-gate: authorized-for-serial-deep-probe` line and a retained
   `c1-completed-c2-gate.json` record (schema
   `inferswarm.issue250.c1-completed-c2-gate/1`) at the new evidence root.
   The record binds `head_sha`, `c1_completed: true`, `c1_verdict` (exactly
   `deterministic` or `variable`), and the separate C1 and C2 dispatch
   authority digests. Verify the C1 verdict against retained full-row
   receipts and both digests against their *live* exact-head authorities
   before C2 launch/reduction. The older
   `c1-varied-c2-gate.json` shape grants no current C2 authority.
4. Only a completed, separately authorized C2 population may settle §C.
   Default varies + C2 serial deterministic (five identical rows) can
   LOCALIZE the exact default-vs-serial CPU execution boundary, without
   asserting a deeper root cause. If C2 serial also varies (valid
   first-mismatch prefix), §D becomes reachable. A missing/invalid C2
   population remains BLOCKED. No C1 outcome authorizes C2 by itself;
   generic C or C1 namespace dispatch never authorizes serial work.

## Producer cost authority and retained-record binding

The pass-6 prospective planning record is now a producer precondition, not a
report-only calculation. Each fresh-process unit and the Arm-B same-process
lifecycle derives its cost condition from its frozen arm/unit plan, loads
`cost-planning-record.json` from the canonical evidence generation, and
checks the complete record against an independently recomputed frozen
projection before any physical runner/server launch. The producer does not
accept caller-supplied costs or rates. Its canonical SHA-256 binds the entire
record except the digest field itself, including generation, source identity,
all condition entries and dispositions, numeric rates, unit counts and
estimated costs, and campaign ceiling. A matching recomputed digest alone is
not sufficient: even a re-signed mutation must differ from the independent
frozen derivation and fail closed. The HTTP timeout is a distinct safety
bound, never a cost authorization. Conditional B and D admission does not
create sequential reachability or dispatch authority; those gates remain
separate. C2 exceeds the automatic ceiling and may launch only with its
own validated exact-head maintainer authorization and retained C1 proof.

The signed C2 gate is not a terminal and does not authorize physical work
without independent maintainer dispatch. Neither accepted #241/#248 evidence
nor the failed v1 #250 evidence is reinterpreted.
The four-thread finding remains useful retained context, not the terminal
boundary the issue asked for. No thresholds, comparator methodology,
case-4096, predictive work, or Arm-D predicate is changed.
