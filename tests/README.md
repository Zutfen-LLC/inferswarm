# Tests

These tests guard **retained evidence**, not a product runtime. They assert
that the frozen tooling in [`../scripts/`](../scripts/README.md) still
reproduces the accepted records under [`../docs/`](../docs/README.md)
byte-for-byte, and that every fail-closed gate still fails closed.

A test failure here usually means one of two things:

1. a pinned producer or evidence file was edited, which invalidates the
   record that cites its SHA-256; or
2. a genuine defect in tooling that has not yet produced accepted evidence.

The first is not a test to relax. See the frozen-producer rule in
[`../scripts/README.md`](../scripts/README.md).

## Requirements

The canonical CPU test environment is declared once in
[`../requirements-test.txt`](../requirements-test.txt) (Issue #131). That file
is the single dependency authority — CI, the bootstrap, and the doctor all
consume it; it installs the immutable Issue #117 frozen tokenizer requirements
by reference and never restates their pins.

```bash
python3 scripts/bootstrap_test_env.py     # idempotent; creates .venv/
.venv/bin/python scripts/check_test_env.py  # fast doctor before the suite
```

What the environment provides and why:

| Requirement | Needed for |
|---|---|
| Python 3.12 (exact) | everything — the accepted Issue #129 frozen tokenizer environment pins its software identity to 3.12; the bootstrap creates a 3.12 `.venv` and the doctor rejects other minor versions |
| `jsonschema` | `test_issue74_methodology` and `test_issue110_v5_custody_handoff` |
| `numpy` | `scripts/analyze_phase1_p6.py` only (a declared environment dependency; that historical analysis's test was retired by Issue #246) |
| `pyyaml` | the CI YAML check, not the test suite |
| the pinned Issue #129 tokenizer requirements | the tokenizer-backed checks in `test_issue74_methodology` and `test_issue237_r8i_methodology` (installed by reference from the authority file) |
| `openssl` on `PATH` | the sealing/preflight tools and the synthetic certificate/custody tests in `test_issue109_v5_methodology` and `test_issue110_v5_custody_handoff` (external executable checked by the doctor, not a Python package) |

Everything else is standard library. No test imports `torch`, initializes
CUDA, or contacts a GPU node — `test_issue115_cleanup_retention` mechanically
asserts that the cleanup tooling cannot, and the Issue #131 doctor rejects a
model-runtime package entering the CPU environment.

A missing declared dependency is an environment setup failure, not a
pre-existing test failure: run the doctor, fix what it names, re-run. Do not
stash, reset, or check out another revision merely to demonstrate a declared
dependency is missing on the base branch.

## Running

The bounded parallel runner is the preferred full-suite invocation. It first
uses raw `unittest` discovery as the population authority, then proves that
worker-executed identities exactly equal that serial population. The modules
import their script dependencies by inserting `scripts/` on `sys.path`
themselves, so no `tests/__init__.py` is needed:

```bash
# one module
python3 -m unittest tests.test_issue237_r8i_methodology -v

# everything (preferred bounded parallel full suite)
python3 scripts/run_full_cpu_suite.py

# raw serial discovery (direct debugging / equivalence check)
python3 -m unittest discover -s tests -p 'test_*.py'
```

The repository-integrity check is separate and needs no dependencies:

```bash
python3 scripts/check_phase0_workloads.py
```

## Expected result

On a clean or dirty working tree inside a bootstrapped environment, the whole
suite passes with **4 skips** (discovery adds no skips; CI's named-module
selection remains a subset). Every skip is a host-local resource this
repository deliberately does not carry:

| Skipped test | Reason |
|---|---|
| `test_issue74_methodology.test_public_artifacts_reproduce_byte_for_byte_with_pinned_tokenizer` | the pinned tokenizer is not provided |
| `test_issue133_physical_execution_retention` (3 frozen-reducer replays) | the host-local `/tmp/is133-venv` frozen-tokenizer interpreter is not present |

The FreeToken producer-delta skips and the dirty-tree skip belonged to
`test_issue117_applicability` and `test_issue117_preflight`, which Issue #246
retired.

## What CI runs

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs the YAML check,
the Phase-0 workload check, the Markdown internal-link check, repository
hygiene, project-naming consistency, and a named list of test modules.

The generated-status gate also runs `test_project_status` for documentation
drift and authority-field separation. The separate evidence-manifest gate runs
`test_evidence_manifest_lifecycle` and the Issue #187 bundle verifier; the
accepted #137 and #153 bundles are verified by the tombstone-aware
`scripts/check_ci_test_retention.py` (their frozen builders hash retired test
files).

Every canonical test module is registered to exactly one CI group and
carries a retention record in
[`docs/ci/test-retention-audit.json`](../docs/ci/test-retention-audit.json)
(Issue #246). Tests are retained because they protect current contracts,
reachable regressions, or current evidence integrity; issue provenance alone
is not a reason to keep one. See the
[test lifecycle](../docs/ci-impact-planning.md#test-lifecycle-issue-246).

Historical behavior suites that only replayed completed campaigns were
retired: the Phase-1/Phase1R derivations, V0-B, V0-C/V1/V2-A, #35, the
V2-B..V2-G V340L campaigns, R8-C/D/E/G/H, the #117/#129/#133/#137/#153
Arm-C lineage, #157, #166-#182, #175, and the superseded Gemma V2-V4 lines.
Their accepted evidence, manifests, and producers are pinned instead, and the
always-on `scripts/check_ci_test_retention.py` check fails if any of those
bytes change. Where an accepted manifest names a deleted test file, the row
is excused only by an exact tombstone in
[`docs/ci/retired-test-rows.json`](../docs/ci/retired-test-rows.json). The one
still-current guard those suites carried — consumed holdout observations never
become successor inputs — lives in `test_consumed_holdout_boundary`.

CI bootstraps the same canonical environment locally developers use
(`bootstrap_test_env.py` + `check_test_env.py`, Issue #131); it installs no
Python packages outside `requirements-test.txt`.

## Adding a test

- One module per gate or lane, named `test_issue<NNN>_<topic>.py` for gate
  work or `test_<script_name>.py` for a tool.
- Assert the exact SHA-256 of anything that retained evidence pins, and assert
  byte-identical regeneration for anything a builder produces.
- Give every fail-closed path a negative control. Several modules
  (`test_issue99_proof`, `test_ci_test_retention`,
  `test_consumed_holdout_boundary`) exist mostly to prove that hash drift,
  missing evidence, and unauthorized inputs are rejected rather than
  tolerated.
- Skip — with an explicit reason string — rather than fail when a host-local
  resource is genuinely absent. Never skip to route around a real failure.
- Wire the module into `ci.yml` in the same change.
