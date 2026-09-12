# V0-B — reduce matched Vulkan/native evidence and select an integration seam

Issue: Zutfen-LLC/inferswarm#142 (parent #140). Consumes the accepted
V0-A evidence (issue #141, PR #145 merge
`273b9e8e32c779f063903cd75a0c6772d0d1e451`) and reduces it to an
architectural handoff.

## Contents

- `METHODOLOGY.md` — freeze authority for the ONE authorized physical
  collection (supplemental matched CPU baseline) and the reduction rules.
- `METHODOLOGY-CORRECTION-1.md`, `METHODOLOGY-CORRECTION-2.md` —
  additive corrections of the CPU-arm backend-selection proof rule,
  each frozen before any run under it was accepted; runs collected
  under superseded rules were discarded at collection time (their
  bytes were overwritten by the accepted campaign's re-use of the
  runner's sequential run IDs — declared in correction 1's
  disposition).
- `RESULTS.md` — the human-readable reduction and interpretation.
- `TERMINAL.json` — the machine-readable V0-B terminal classification
  (exactly one), decision inputs, and the scoped V0-C question.
- `results/` — derived reductions (all mechanically produced by the
  `scripts/v0b_*.py` producers, hashes in `MANIFEST.sha256`):
  - `comparability-matrix.json` (Phase 0);
  - `correctness-stability.json` (Phase 1);
  - `economics.json` (Phase 2, incl. the supplemental CPU arm);
  - `capability-assessment.json` (Phase 3);
  - `seam-comparison.json` (Phase 4);
  - `cpu-supplemental/` — raw runs + mechanical summary (Phase 2
    supplemental arm; accepted runs v0b-cpu-01..03).
- `MANIFEST.sha256` — bundle-local immutable manifest (lifecycle v2).

## Terminal

`V0B_PROCEED_TO_INTEGRATION_SPIKE` — see `TERMINAL.json` for the exact
decision inputs and non-claims. This classification is an observation,
not an execution authorization and not an acceptance: it does not
authorize V0-C execution by itself and does not change any accepted
Issue #117 authority.

## Regenerating

```bash
python3 scripts/v0b_comparability_audit.py
python3 scripts/v0b_correctness_stability.py
python3 scripts/v0b_cpu_supplement_derive.py
python3 scripts/v0b_economics.py
python3 scripts/v0b_capability_assessment.py
python3 scripts/v0b_seam_comparison.py
python3 scripts/v0b_terminal.py
python3 scripts/v0b_manifest.py --check
```

The physical runner (`scripts/v0b_cpu_supplement_run.py`) is host-pinned
to inferswarm02 and identity-pinned to the frozen V0-A probe/model; it
refuses to run elsewhere or on drifted bytes. It is NOT part of normal
regeneration — retained runs are never re-executed.
