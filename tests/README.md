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
| Python 3.12 (exact) | everything — the accepted Issue #129 real-tokenizer proof pins its frozen software identity to 3.12; the bootstrap creates a 3.12 `.venv` and the doctor rejects other minor versions |
| `jsonschema` | `test_issue74_methodology`, `test_issue79_v2_threshold_tooling`, `test_issue86_v3_methodology`, `test_issue110_v5_custody_handoff`, and the v2/v3 unseal preflights |
| `numpy` | `test_analyze_phase1_p6` only |
| `pyyaml` | the CI YAML check, not the test suite |
| the pinned Issue #129 tokenizer requirements | `test_issue129_arm_c_retry` real-tokenizer proof (installed by reference from the authority file) |
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

`unittest` discovery over the test directory is the canonical full-suite
invocation (verified on a clean bootstrapped environment; the modules import
their script dependencies by inserting `scripts/` on `sys.path` themselves,
so no `tests/__init__.py` is needed):

```bash
# one module
python3 -m unittest tests.test_issue117_preflight -v

# everything (1640 tests; ~8 minutes)
python3 -m unittest discover -s tests -p 'test_*.py'
```

The repository-integrity check is separate and needs no dependencies:

```bash
python3 scripts/check_phase0_workloads.py
```

## Expected result

On a clean working tree inside a bootstrapped environment, the whole suite
passes with **5 skips** (discovery adds no skips; CI's named-module selection
remains a subset). Every skip is a host-local resource this repository
deliberately does not carry:

| Skipped test | Reason |
|---|---|
| `test_derive_phase1r_d7_placement.test_companion_and_byte_deterministic_rerun` | frozen external exact-route evidence is host-local |
| `test_issue117_applicability` (3 producer-delta tests) | the FreeToken repository is not present on this machine |
| `test_issue74_methodology.test_public_artifacts_reproduce_byte_for_byte_with_pinned_tokenizer` | the pinned tokenizer is not provided |

**A dirty working tree adds a sixth skip.**
`test_issue117_preflight.test_valid_preflight_passes` skips with
`test repository working tree is dirty` whenever uncommitted changes exist —
including the change you are testing. Commit or stash before treating that
test as having run.

## What CI runs

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs the YAML check,
the Phase-0 workload check, the Markdown internal-link check, repository
hygiene, project-naming consistency, and a named list of test modules.

The generated-status gate also runs `test_project_status` for documentation
drift and authority-field separation. The separate evidence-manifest gate runs
`test_evidence_manifest_lifecycle` and the Issue #137 bundle verifier.

Every module guarding live evidence is in that list, including
`test_issue117_physical_retention`, which runs in the issue #117 CPU-only step.

Five modules are deliberately out:

| Module | Why it is out of CI |
|---|---|
| `test_analyze_phase1_p6` | historical Phase-1 analysis; runs locally under the canonical environment (which does provide `numpy`) |
| `test_derive_phase1_placement_v2` | historical Phase-1 derivation |
| `test_derive_phase1r_d3_placement` | historical Phase1R derivation |
| `test_derive_phase1r_d4_placement` | historical Phase1R derivation |
| `test_derive_phase1r_d7_placement` | historical Phase1R derivation |

These five guard records that are frozen and no longer change. Run them locally
before touching anything under `docs/investigations/data/`.

CI bootstraps the same canonical environment locally developers use
(`bootstrap_test_env.py` + `check_test_env.py`, Issue #131); it installs no
Python packages outside `requirements-test.txt`.

## Adding a test

- One module per gate or lane, named `test_issue<NNN>_<topic>.py` for gate
  work or `test_<script_name>.py` for a tool.
- Assert the exact SHA-256 of anything that retained evidence pins, and assert
  byte-identical regeneration for anything a builder produces.
- Give every fail-closed path a negative control. Several modules
  (`test_issue90_post_v3_diagnosis`, `test_issue99_proof`,
  `test_issue117_preflight`) exist mostly to prove that hash drift, missing
  evidence, and unauthorized inputs are rejected rather than tolerated.
- Skip — with an explicit reason string — rather than fail when a host-local
  resource is genuinely absent. Never skip to route around a real failure.
- Wire the module into `ci.yml` in the same change.
