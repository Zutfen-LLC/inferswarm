# R8-I3C — Vulkan mechanism diagnostic (Issue #252)

**Current status (#266): aggregate mainline candidate; STOP for maintainer exact-head review of PR #256, OPEN / UNMERGED.** The #254 producer/custody stack includes completed successors #258 (PR #259), #260 (PR #261), #262 (PR #263), and #264 (PR #265). The maintainer [accepted #264 for its bounded scope](https://github.com/Zutfen-LLC/inferswarm/issues/264#issuecomment-5969219338): an authenticated output.weight MMV path transition on the frozen RTX 3060 subject, SUBGROUP/subgroup/32x1x1 to LARGE/hybrid/128x1x1. Both arms remain screening-variable; no numerical causality, root-cause attribution, or H2/H3/H5 theorem closure is accepted. No further physical execution is authorized; #266 is repository/CPU-only aggregate validation, not a new experiment.

Historical scope: the methodology was frozen prospectively on 2026-09-30. Phase 0 remains offline/repository-only and reports `physical_execution: false`; its records and all accepted historical methodology/evidence remain unchanged. This living summary grants no dispatch, execution, or merge authority.

## Contents and evidence

- [`METHODOLOGY.md`](METHODOLOGY.md) — prospective frozen subject, hypotheses, five one-factor arms, repeat/custody law, dispatch gate, reducer terminals, and prohibitions.
- [`evidence/phase0/reconciliation.json`](evidence/phase0/reconciliation.json) — accepted authority/source/model/host reconciliation. SHA-256: `250833edb5519d2ff86e9d539c7ecb40825e903c01e0e8d6c6003e29e201f46c`
- [`evidence/phase0/vulkan-path.json`](evidence/phase0/vulkan-path.json) — pinned-source Vulkan path and candidate mechanisms. SHA-256: `87c5e9b3fd67d74e4d567c96586db88c300f8a901f4482db70d7d15c7bf876da`
- [`evidence/phase0/hypothesis-matrix.json`](evidence/phase0/hypothesis-matrix.json) — six unproven hypotheses, arm map, exact controls, repeat law. SHA-256: `f80cfff43863705cf74ad2a056ab33c8dfa3aa81773ca8d30ad4bda27180498d`

The hashes above are to be literal SHA-256 values; generate/verify them from the checked-in bytes using `sha256sum` before committing this README.

## Tooling and tests

- `scripts/issue252_constants.py` — single source for frozen issue, heads, model-member digests, comparator, source pin/tree, host identity, terminal vocabulary, and dispatch format.
- `scripts/issue252_phase0.py` — offline reconciliation of accepted predecessor, model/comparator authority, and pinned llama.cpp commit/tree; no physical execution or network access.
- `scripts/issue252_vulkanpath.py` — deterministic pinned-source path/control reconstruction.
- `scripts/issue252_arms.py` — frozen hypotheses, five one-factor arms, validation, and deterministic hypothesis-matrix generation.
- `scripts/issue252_physical.py` — fail-closed physical execution/custody gates; does not itself grant dispatch authority.
- `scripts/issue252_terminal.py` — retained-byte terminal derivation (AMENDMENT-006: capability-explicit arm-set theorem).
- `scripts/issue258_theorem.py` — frozen per-arm terminal-capability law and hypothesis-coverage derivation (#258; consumed by the reducer; grants no execution authority).
- [`METHODOLOGY-AMENDMENT-007.md`](METHODOLOGY-AMENDMENT-007.md) — #260 source-only H2/H3 instrumentation freeze and explicit H5 boundedness blocker. `issue260-source-identity.json` and `patches/issue260-vulkan-instrumentation.patch` pin the distinct prospective source; `scripts/issue260_instrumentation.py` parses synthetic exact-format markers. No physical result, new-arm dispatch, binary freeze, or amendment of historical A1–A5 evidence follows from this addition.
- Issue #262 rapid physical pilot — `issue262-source-identity.json` freezes the full instrumented comparator source chain (pinned b29c606e + #260 H2/H3 patch + `patches/issue262-h5-route.patch` output-projection route markers + accepted R8-E patch + comparator/2 seam); `scripts/issue262_source_patch.py` rebuilds and verifies it; `scripts/issue262_h5.py` parses H5 route markers and derives coopmat2 one-factor eligibility; `scripts/issue262_pilot.py` is the bounded pilot producer (issue-authorized, frozen subject, screening 2–3 units/arm). The `#260` H2/H3 parser accepts the `#262` tree identity additively.

- [`evidence/issue262/REPORT.md`](evidence/issue262/REPORT.md) — completed bounded H2/H3 pilot: all arms screening-variable; serialized/normal submission observations and the A4 target-memory-choice contrast are not numerical causal proof. The observed MMV route made the coopmat2 candidate ineligible.
- [`METHODOLOGY-ISSUE264.md`](METHODOLOGY-ISSUE264.md) and [`evidence/issue264/REPORT.md`](evidence/issue264/REPORT.md) — completed, bounded H5 MMV path discriminator and accepted four-unit pilot. `issue264-source-identity-v2.json`, `issue264-build-identity.json`, and `patches/issue264-mmv-selector-v2.patch` retain the distinct gen2 source/binary identity; the gen1 audit is historical, not the selected comparator. `scripts/issue264_h5.py`, `issue264_pilot.py`, and `issue264_report.py` verify exact dispatch pairing, custody, and descriptive screening facts. These do not promote historical #254 rows into instrumented evidence or close the #258 theorem.

From the repository root, run the focused CPU-only tests:

```sh
.venv/bin/python -m unittest tests.test_issue252_phase0 tests.test_issue252_vulkanpath tests.test_issue252_arms tests.test_issue252_physical tests.test_issue252_terminal tests.test_issue258_theorem
```

Then validate documentation/status and planning CI:

```sh
.venv/bin/python -m unittest tests.test_plan_ci
python3 scripts/sync_project_status.py --check
python3 scripts/finalize_repository.py --check
python3 -m unittest tests.test_project_status -v
```

Tests exercise repository fixtures and do not establish a physical result or authorize a run.
