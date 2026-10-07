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
