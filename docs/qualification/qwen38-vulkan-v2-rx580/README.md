# Issue #241 (R8-I3) — RX 580 comparator/2 dormant campaign slice

Prospective CPU/static freeze for the first practical AMD/Vulkan Qwen
comparator on the matched high-RAM host. Implementation and CPU/fake
fixtures only: NO physical R8-I3 execution has occurred. Physical
phases 1-4 are dormant until the maintainer dispatches the exact frozen
producer head (phrase `R8I3 PHYSICAL DISPATCH #241`).

- Frozen methodology: [METHODOLOGY.md](METHODOLOGY.md)
- Campaign status producer: `scripts/issue241_campaign.py`
- Phase 0 preservation audit: `scripts/issue241_phase0.py` (clean on
  this slice; all 27 accepted R8-I MANIFEST rows byte-preserved; holdout
  ciphertext unchanged)
- Constants/authority: `scripts/issue241_constants.py`
- Dispatch verifier: `scripts/issue241_dispatch.py`
- Census validator: `scripts/issue241_census.py`
- Matched-placement ladder: `scripts/issue241_placement.py`
- comparator/2 observer seam: `scripts/issue241_observer_patch.py`
- comparator/2 validation reducer: `scripts/issue241_comparator.py`
- Practicality projection: `scripts/issue241_practicality.py`
- Supersession builder: `scripts/issue241_supersession.py`
- Focused tests: `tests/test_issue241_r8i3_rx580.py` (75 tests)

## Dormancy contract

| Phase | Kind | State |
|---|---|---|
| 0 preservation audit | CPU-only | RUNNABLE — clean |
| 1 fresh same-host precheck | physical | DORMANT — dispatch required |
| 2 matched-placement ladder | physical | DORMANT — dispatch required |
| 3 comparator/2 validation | physical | DORMANT — dispatch required |
| 4 practicality projection | reducer | DORMANT — consumes measured receipts only |
| 5 v2 supersession | builder | DORMANT — phase-4 terminal AND maintainer GO; emits no authority before that |

Every physical entrypoint is the committed bounded path in
`scripts/issue241_physical.py` (`run_phase1`/`run_phase2`/`run_phase3`);
each invokes `issue241_dispatch.require_live_dispatch` BEFORE fixture
load, device probe/init, server build, model-byte reads, telemetry, or
inference (structurally tested). The superseded #240 exploration is
diagnostic history only; nothing from it is consumed here.
