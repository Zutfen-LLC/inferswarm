# V2-A — reusable device qualification harness (issue #163)

Status: IN PROGRESS (Phase 0 complete; namespace is additive).

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

- `scripts/v2a_discovery.py` — NON-AUTHORIZING physical inventory:
  enumerates Vulkan devices, binds each runtime selector to a stable
  PCI BDF mechanically, fails closed on ambiguity. Output is inventory
  data only; it never selects, promotes, or authorizes a device.
- `scripts/v2a_authority.py` — machine-readable campaign authority
  contract + loader: subject/resource, runtime/state, correctness
  (prospectively authorized reference bytes + provenance + explicit
  no-recalibration rule), and evidence IDs. Incomplete or
  self-authorizing authorities are rejected.
- `scripts/v2a_harness.py` — ONE reusable campaign engine consuming a
  frozen authority: mechanical preflight, fresh qualification,
  adapter-sealed observation, capability creation, generic resource
  snapshot, production generic planner, candidate+plan freeze,
  canonical physical execution, selector-aware V1-C accounting,
  accepted byte-exact comparator, adapter-sealed canonical proof,
  generic canonical observation, execution receipt, deterministic
  evidence reduction. Reuses accepted V1-A/V1-C components by import;
  no subject literal in reusable logic.
- `scripts/v2a_manifest.py` — generalized fixed-inventory evidence
  bundle generator/verifier driven by an inventory contract (ladder of
  exact permitted states), not a hand-written per-subject producer.

Discovery and campaign authorization are mechanically distinct: a
correctness-bearing campaign may begin only from an authority that
already contains a prospectively valid correctness reference; the
harness never derives a reference from output it just observed.

## Nonclaims

Internal/research qualification harness only. Not a public plugin API,
not production scheduler/backend support, not default/preferred-backend
policy, no broad hardware/model qualification, no comparator
recalibration, no Vulkan/CUDA numerical-equivalence claim, no SSH.

## Evidence plan

- Retained AMD (V1-A) and NV (V1-C) transcript replays under the same
  harness bytes (retrospective regression only).
- Two fresh physical campaigns (AMD-A and NV-A) from two separate
  prospective authorities over the SAME source freeze.
- Machine-readable portability audit comparing the two campaigns.
