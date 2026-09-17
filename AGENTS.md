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

Campaign/review handoffs follow `docs/campaign-gate-ordering.md` (Issue #213):
run the cheap pre-review gates, freeze the head for adversarial review, apply
accepted fixes, then run exactly one full CPU suite and one hosted exact-head
CI on the final head. Adversarial review never substitutes for those final
gates, and a pre-review full suite or hosted CI run requires an explicit
review-critical declaration.
