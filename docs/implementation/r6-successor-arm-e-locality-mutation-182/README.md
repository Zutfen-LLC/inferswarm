# Issue #117 Arm E — Verified-Inventory Locality Mutation (Planning-Only)

Campaign: `issue182-arm-e-locality-mutation-v1`
Authorization: `physical-authorization-issue182-read-only-inventory`
Attempt: `arme-182-physical-1`
Terminal (derived): **`ISSUE117_ARM_E_LOCALITY_MUTATION_PASS`**

Issue: https://github.com/Zutfen-LLC/inferswarm/issues/182
Starting InferSwarm head: `d4d50b20205e455a195a908ee9d5ea72bc5d8d04`
(the accepted PR #181 Arm-D merge; verified ancestor at authority build)

## Claim

Verified inventory locality changes transition economics and ranking
evidence while the eligibility gate ledger remains unchanged. This is
the accepted Issue #117 Arm-E claim, physically grounded against the
retained Arm-B cold planning inputs and a fresh read-only observation
of the Arm-D-terminal durable verified artifact caches.

## Method (frozen before observation)

- **Arm E-A (cold)**: the retained accepted Arm-B sequence-1
  pre-realization node inventory snapshots (both empty of verified
  objects), consumed byte-for-byte from
  `../r6-successor-dense-full-integration-117/evidence/arm-b/raw/coordinator/`.
- **Arm E-B (warm)**: a fresh read-only observation (2026-09-14) of
  `/srv/inferswarm/cache/issue117/objects` on inferswarm01 (411
  verified objects) and inferswarm03 (218), with sha256 re-verification
  of every object, before/after tree-digest byte-preservation proof,
  materialized-shard pins re-verified against the accepted Arm-D
  authority, GPU totals checked against the frozen pins, and a process
  fence proving no execution-bearing process was live.
- Both arms run the ACCEPTED admission planner
  (`scripts/issue117_planner.py` over `issue103_planner` /
  `issue101_orchestration` / `issue99_artifact_core`) with every
  non-inventory input constructed once and deep-copied into both arms:
  the retained physical candidate set (9 dense candidates from the
  accepted physical preflight), feasibility/capacity facts (observed
  GPU totals minus the frozen 3072 MiB reserve), hard policy (serving
  roles only), the accepted V5 qualification record (reconstructed by
  `issue117_accepted_subject` from byte-pinned historical evidence),
  the retained Arm-B participant requirements, path evidence derived
  from the retained Arm-B acquisition-ledger bytes, and the
  MIN_TRANSITION_COST objective.
- The cold arm reproduces the retained Arm-B plan and requirements
  byte-for-byte (asserted in code) before either ranking runs.

## Result (mechanically re-derived from retained bytes)

| quantity | cold (Arm E-A) | warm (Arm E-B) |
|---|---|---|
| V5 `dense.6171f32b4413` missing bytes | 27,841,245,749 | 0 |
| V5 estimated transition seconds | 60,355.109 (derived from retained ledger bandwidth) | 0.0 |
| selection | `dense.6171f32b4413` | `dense.6171f32b4413` (unchanged) |
| gate ledger (all 9 candidates) | — | byte-identical to cold |

Every non-ranking gate (technical feasibility, hard policy,
integrity, qualification applicability) is identical across arms for
every candidate; no unqualified candidate became admissible or
selected; locality alone explains the entire economic movement.

## Evidence

- `authority.json` — frozen campaign authority (heads, drift
  classification, cold/warm bindings, capacity/bandwidth methods,
  STOP rules, producer hashes)
- `observation/warm-inventory-inferswarm01.json` /
  `observation/warm-inventory-inferswarm03.json` — raw read-only
  observation records (fence, preservation scans, verified objects,
  materialized pins)
- `comparison.json` — the two-arm comparison with per-candidate rows,
  inputs identity digests, and the derived invariants
- `terminal-reduction.json` — the mechanically re-derived terminal
- `MANIFEST.sha256`

Tooling: `scripts/issue182_campaign_pins.py`, `issue182_authority.py`,
`issue182_inventory.py`, `issue182_compare.py`, `issue182_terminal.py`,
`issue182_manifest.py`; contract tests in
`tests/test_issue182_arm_e.py` (32 tests, negative controls included).

## Non-claims

No model execution, no CUDA initialization, no artifact
acquisition/mutation, no new serving output, no throughput numbers, no
transfer-time prediction accuracy, no GPU scheduling claim, no dynamic
congestion behavior, no production failover, no reboot/cache-loss
recovery, no mutable session-cache movement, no public planner or
locality schema. No `h109-*` material was accessed, reconstructed,
generated, or used. This completes the planned Arms A–E integration
sequence locally and creates no broader production or multi-model
claims.

Status: PR OPEN / UNMERGED — maintainer review required.
