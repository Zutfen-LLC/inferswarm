# Issue #241 (R8-I3) — RX 580 comparator/2 campaign (subject generation 2)

Prospective freeze for the first practical AMD/Vulkan Qwen comparator on
the matched high-RAM host, pivoted to the REPLACEMENT consumer Polaris
RX 580 8GB (generation 2) after the generation-1 physical card failed
fatally under dispatch. Implementation and CPU/fake fixtures only: NO
physical R8-I3 execution has occurred against the generation-2 subject.
Physical phases 1-4 are dormant until the maintainer dispatches the
exact frozen producer head (phrase `R8I3 PHYSICAL DISPATCH #241`).
Dispatch authority is an exact-head OWNER/MEMBER top-level PR
conversation comment on PR #242 (single-maintainer repository; GitHub
review state, including APPROVED, is not part of the gate); any
branch-head movement invalidates an existing authorization.

- Frozen methodology: [METHODOLOGY.md](METHODOLOGY.md) (frozen 2026-09-23;
  subject re-freeze amendment:
  [METHODOLOGY-AMENDMENT-001-REPLACEMENT.md](METHODOLOGY-AMENDMENT-001-REPLACEMENT.md),
  2026-09-24)
- Campaign status producer: `scripts/issue241_campaign.py`
- Phase 0 preservation audit: `scripts/issue241_phase0.py` (clean on
  this slice; all 27 accepted R8-I MANIFEST rows byte-preserved; holdout
  ciphertext unchanged; generation-2 freeze provenance mechanically
  verified against retained census bytes; historical retention present)
- Constants/authority: `scripts/issue241_constants.py`
  (SUBJECT_GENERATION = 2)
- Dispatch verifier: `scripts/issue241_dispatch.py`
- Census validator: `scripts/issue241_census.py`
- Matched-placement ladder: `scripts/issue241_placement.py`
- comparator/2 observer seam: `scripts/issue241_observer_patch.py`
- comparator/2 validation reducer: `scripts/issue241_comparator.py`
- Practicality projection: `scripts/issue241_practicality.py`
- Supersession builder: `scripts/issue241_supersession.py`
- Focused tests: `tests/test_issue241_r8i3_rx580.py` (202 tests)

## Subject generations

| Generation | Physical card | Negotiated width | State |
|---|---|---|---|
| 1 | RX 580 (Sapphire Pulse subsystem 1da2:e353, rev e7) | x8 | FAILED — fatal PCIe/AER; terminal `R8I3_RX580_INFRASTRUCTURE_BLOCKED`; historical |
| 2 | REPLACEMENT RX 580-class card, same slot | x16 | prospective frozen subject (this slice) |

Generation-2 freeze authority: the retained fresh READ-ONLY replacement
census of 2026-09-24 (`evidence/replacement-census-2026-09-24/` — raw
sysfs/lspci/nvidia-smi/per-ICD vulkaninfo bytes; no GPU compute, no
model reads, no dispatch machinery). The frozen constants equal the
mechanical derivation of those bytes
(`issue241_constants.derive_candidate_identity_from_census`, enforced by
the Phase-0 audit). The derivation reads NO frozen constant: the BDF is
derived from the retained PCI topology (`raw/pci.txt` cross-corroborated
by `raw/pci_verbose.txt`, unique AMD display endpoint, rc-checked), then
cross-bound to the retained per-BDF sysfs artifacts; the Radeon ICD is
derived from the retained ICD inventory (`raw/icd_inventory.txt`, unique
radeon entry) cross-bound to the retained successful RADV observation
(`raw/vulkan_radeon.txt` GPU0, `rc=0`, vendor/device match against the
derived BDF's sysfs bytes) — negatively controlled by sandboxed
topology/ICD/receipt mutations (correction round 2, review comment
5814248688). Exactly one field changed versus generation 1:
negotiated `link_width` x8 → x16. All other software-visible identity
fields are byte-identical (same marketed model, same subsystem
1da2:e353, rev e7, 8192 MiB VRAM, amdgpu, RADV POLARIS10 UUID) —
recorded as coincidental equality, NOT card equality: the physical card
was replaced and no software field individuates Polaris boards.
Generation-1 receipts can never satisfy a generation-2 acceptance gate
(negatively controlled in tests).

## Historical evidence (immutable)

`historical/` retains, byte-preserved and hash-bound by the area
MANIFEST:

- `campaign-v2-dispatch-b6148de/` — the complete generation-1 dispatched
  campaign at head `b6148de` (Phase 1 census PASS; Phase 2 placement
  PASS at ngl=8; Phase 3 fail-closed on the RX580 fatal AER fault;
  platform-fault capture: journal windows, D-state stacks, per-device
  lspci, AER records — 10 artifacts under SHA256SUMS). Terminal:
  `R8I3_RX580_INFRASTRUCTURE_BLOCKED`. Diagnostic history only; never
  qualification evidence for the replacement card.
- `oldcard-canonical-fault-repro-2026-09-24/` — the failed card
  reproducing the identical fatal AER fault under the accepted canonical
  no-hook binary at the exact historical crash-leg geometry (excludes
  comparator/2 instrumentation as cause).
- `replacement-crash-leg-diagnostic-2026-09-24/` — the replacement card
  completing the exact formerly-fatal leg cleanly (canonical binary,
  8/8 tokens, normal thermals/power/VRAM release). Remediation evidence
  only; carries no dispatch authority or campaign schema and cannot
  satisfy any acceptance gate.

## Dormancy contract

| Phase | Kind | State |
|---|---|---|
| 0 preservation audit | CPU-only | RUNNABLE — clean (generation 2) |
| 1 fresh same-host precheck | physical | DORMANT — NEW dispatch required |
| 2 matched-placement ladder | physical | DORMANT — NEW dispatch required |
| 3 comparator/2 validation | physical | DORMANT — NEW dispatch required |
| 4 practicality projection | reducer | DORMANT — consumes measured receipts only |
| 5 v2 supersession | builder | DORMANT — phase-4 terminal AND maintainer GO; emits no authority before that |

Every physical entrypoint is the committed bounded path in
`scripts/issue241_physical.py` (`run_phase1`/`run_phase2`/`run_phase3`);
each invokes `issue241_dispatch.require_live_dispatch` BEFORE fixture
load, device probe/init, server build, model-byte reads, telemetry, or
inference (structurally tested). The superseded #240 exploration is
diagnostic history only; nothing from it is consumed here.

The generation-2 physical cascade, when authorized by a NEW exact-head
dispatch comment on the generation-2 producer head, must run Phase 1 →
Phase 4 complete and fresh on the replacement card; no generation-1
placement, comparator, or performance observation may satisfy any
acceptance gate for the replacement.
