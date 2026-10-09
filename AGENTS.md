# Working in InferSwarm

Read `CONTRIBUTING.md` and follow the canonical documentation hierarchy before
changing architecture or runtime work. Preserve accepted evidence and pinned
experimental producers.

For changes to capabilities, architecture, integration branches, gate results,
acceptance, or execution authorization, review documentation impact in the same
PR. Follow `docs/status-maintenance.md`: update the living status record from
recorded authority, regenerate managed sections, and update affected explanatory
prose. Explain any no-impact determination in the PR description. Never treat
an observed PASS, generated status text, or green CI as execution authorization.

## Experiment-first review standard (default)

InferSwarm is **experimental hardware research in a controlled homelab**, not a
production service or a hostile multi-tenant deployment. Optimize reviews for
the actual near-term decision: can the named hardware run a trustworthy,
bounded experiment and produce interpretable measurements? Do not seek
maximum numbers of findings or treat generic production hardening as progress.

A finding may block a PR or hardware experiment **only if all three apply**:

1. **Realistic here:** identify a concrete failure path under the *actual*
   host, backend, network, hardware, workload, and operating assumptions.
   Do not import hypothetical malicious actors or unsupported configurations.
2. **Material here:** the failure could invalidate the current experiment's
   result or attribution, defeat its frozen STOP/budget boundaries, harm
   hardware, or cause uncontrolled/destructive execution.
3. **Not already contained:** existing ownership, identity, observer,
   correctness, health, timeout, budget, or fail-closed checks do not prevent
   the failure or safely stop it before an invalid result is accepted.

The reviewer bears the burden of explaining **what happens in this experiment,
why it matters, and which existing safeguard fails**. Support NO-GO with a
reproducible test/trace or a clearly demonstrated code-level path under the
real configuration. "Cannot prove this is impossible in all environments" is
not evidence of a blocker. Do not label a theoretical edge case P1 merely
because it could matter in a different deployment.

**Default to GO with clearly documented limitations** when the experiment
remains safe and interpretable. Treat general security hardening, hostile
local-process assumptions, rare portability scenarios, optional diagnostics,
and future-production concerns as nonblocking unless their relevance is
demonstrated. Revisit them if/when InferSwarm enters a separately approved
production-hardening phase.

For example, a stale baseline server actually answering a candidate request
or missing same-request GPU attribution **is blocking**. A hypothetical
adversarial same-port listener requiring a host configuration not present in
the controlled loopback experiment **is not blocking** without evidence that
it can affect this run. Make the distinction explicit.

Keep review and correction **proportional**: one focused exact-head review,
the smallest necessary code change, and the existing required validation
gates. Do not invent prerequisite issues, duplicate qualification campaigns,
additional LLM review lanes, broader frameworks, new methodology, or repeated
authorization of unchanged facts. After a bounded experiment, preserve a
genuine STOP/failed result rather than trying again until PASS.

This standard **does not weaken** already frozen hardware safety, model/source
identity, observer evidence, semantic acceptance, execution budgets, or
approval boundaries. It governs which *new* findings deserve to block.
Documentation-only changes that do not affect executable code, workflows,
experiment authority, or validation semantics need ordinary applicable CI and
a focused diff review; do not launch a full hosted CPU campaign merely to
approve policy wording. For actual campaign/evidence changes, keep the
exact-head ordering and gates in `docs/campaign-gate-ordering.md`.

## Authorized campaign autonomy

Once the maintainer has explicitly authorized a bounded campaign with its
subject, scope, budget, stop conditions, and any required frozen inputs, the
agent **executes autonomously inside that authority**. Maintainer silence,
elapsed time, a new agent/session, or the absence of a fresh human
reconfirmation is not a stop condition.

Preflight is for detecting **material anomalies**, not for re-proving
unchanged facts. Reuse previously established operator/environment facts
unless objective evidence indicates drift. Prefer machine-observable checks
(device identity, topology, hashes, temperatures, fault logs, resource
headroom, runtime/model identity) and proceed when they remain within the
authorized envelope.

Escalate to the maintainer only when a newly observed condition materially
requires a decision, including:

- subject/runtime/model/topology drift that affects applicability or evidence;
- a health, thermal, integrity, attribution, or safety anomaly that the frozen
  stop rules do not already resolve;
- requested scope, budget, spending/purchase, hardware modification, or
  destructive/irreversible action beyond existing authority;
- an implementation/methodology defect that requires changing the frozen
  experiment; or
- genuinely ambiguous or conflicting execution authority.

Do **not** invent confirmation gates for unchanged cooling, cabling, host
placement, staged artifacts, prompts, thresholds, or other facts already
covered by the accepted campaign. A campaign may require a fresh human check
only when a concrete newly observed anomaly cannot be resolved mechanically
and that fact is material to safe or valid execution. If a bounded run fails,
preserve and report the failure; do not convert it into an approval loop or
retry-until-PASS campaign.

Campaign/review handoffs follow `docs/campaign-gate-ordering.md` (Issues
#213/#224/#226): run the cheap pre-review gates, push the exact head and open the
PR, obtain the default independent review — the maintainer's exact-head PR
review (delegated agent/LLM adversarial reviews are optional, targeted,
advisory lanes with no default count or timeout) — apply accepted fixes
(re-reviewing the new head if it moved), then validate the final head with
exactly one hosted Final CPU Validation run (the canonical full CPU suite,
dispatched on the exact reviewed SHA; `final-cpu-validation.yml`) and one
hosted exact-head CI run. Independent review never substitutes for those
final gates, and a pre-review full suite or hosted CI run requires an
explicit review-critical declaration.
