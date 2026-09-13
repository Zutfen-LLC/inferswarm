# V2-A — reusable device qualification harness (issue #163)

Status: CORRECTION ROUND 2 (R2) in progress. The attempt-01 dual
campaigns and their `V2A_REUSABLE_DEVICE_QUALIFICATION_HARNESS_PASS`
terminal are SUPERSEDED (see ATTEMPT01-SUPERSESSION.json,
FINAL-TERMINAL-ATTEMPT01.json). They remain retained, byte-unchanged,
as diagnostic evidence that the execution harness works; their
authorities lacked the mechanically required reviewed-discovery
binding (maintainer NO-GO review 5190619330).

V0 established Vulkan as a promising portable substrate; V1-A/V1-B/V1-C
established a reusable internal S2 participant across two physical
subjects (AMD-A and NV-A) and made the accounting reducer
selector-aware. V2-A turns that accepted evidence-grade path into ONE
reusable internal device qualification/onboarding harness: a campaign
is fully described by prospectively frozen authority DATA, and the same
harness bytes drive discover -> review/freeze authority -> qualify ->
generic plan -> canonical execute -> account -> verify -> seal for any
Vulkan-capable Compute Unit.

## Architecture (authority/data separation)

- `scripts/v2a_discovery.py` — attempt-01 NON-AUTHORIZING physical
  inventory (retained unchanged): runtime listing rows, loader PCI
  blocks, lspci slots; exact-name join with AMBIGUOUS/UNRESOLVED
  classifications that never resolve by ordering.
- `scripts/v2a_discovery_v2.py` — R2 reviewed-discovery successor
  producing the two pre-authority layers:
  `DISCOVERY-INVENTORY.json` (raw inventory, NON_AUTHORIZING) and
  `DISCOVERY-BINDINGS.json` (reviewed selector->BDF bindings, still
  NON_AUTHORIZING). Ambiguous selectors are resolved ONLY by the
  bounded NON-CORRECTNESS-BEARING identity probe: the accepted runtime
  runs with `-n 0` (zero generated tokens) and `-lv 4`, so its own
  selected-device line states the stable BDF. Probe evidence (argv,
  executable identity, raw identity-proof line, exit code, digests) is
  retained and digest-bound; mismatch or ambiguity fails closed.
- `scripts/v2a_authority.py` — attempt-01 authority contract/loader
  (retained unchanged; still enforcing correctness-reference
  provenance).
- `scripts/v2a_authority_v2.py` — R2 successor schema
  `inferswarm.v2a.campaign-authority/2`: requires a
  `discovery_binding` block referencing the reviewed discovery
  artifacts by path+digest; verifies NON_AUTHORIZING status, selector
  presence, BOUND status, exact BDF/hostname/runtime-hash agreement,
  staleness bounds, and binding-proof digests. A caller cannot enrich
  an AMBIGUOUS row into a BOUND authority by supplying a BDF.
- `scripts/v2a_harness.py` — ONE reusable campaign engine consuming a
  frozen v2 authority (reviewed-discovery binding verified at load):
  mechanical preflight, fresh qualification, adapter-sealed
  observation, capability creation, generic resource snapshot,
  production generic planner, candidate+plan freeze, canonical
  physical execution, selector-aware V1-C accounting, accepted
  byte-exact comparator, adapter-sealed canonical proof, generic
  canonical observation, execution receipt, deterministic evidence
  reduction. Accepted V1-A/V1-C components imported, never forked; no
  subject literal in reusable logic. The R2 portability audit also
  classifies the discovery->authority layer.
- `scripts/v2a_manifest.py` — generalized fixed-inventory evidence
  bundle generator/verifier driven by an inventory contract (ladder of
  exact permitted states). The R2 ladder retains the attempt-01
  evidence at every rung and requires `DISCOVERY-INVENTORY.json`,
  `DISCOVERY-BINDINGS.json`, and the raw identity-probe evidence from
  the reviewed-discovery rung onward.

Discovery and campaign authorization are mechanically distinct: a
correctness-bearing campaign may begin only from an authority whose
selector/BDF pair is already mechanically BOUND to digest-verified
reviewed discovery, and which already contains a prospectively valid
correctness reference; the harness never derives a reference from
output it just observed.

## Nonclaims

Internal/research qualification harness only. Not a public plugin API,
not production scheduler/backend support, not default/preferred-backend
policy, no broad hardware/model qualification, no comparator
recalibration, no Vulkan/CUDA numerical-equivalence claim, no SSH.

## Evidence plan

- Retained AMD (V1-A) and NV (V1-C) transcript replays under the same
  harness bytes (retrospective regression only).
- Attempt-01 dual physical campaigns retained as superseded diagnostic
  evidence (byte-unchanged).
- R2: fresh reviewed discovery (inventory + probed bindings) under the
  corrected source freeze, then two fresh physical campaigns (AMD-A-R2
  and NV-A-R2) from separate v2 authorities over the SAME corrected
  source freeze, then the R2 portability audit including the
  discovery->authority layer.
