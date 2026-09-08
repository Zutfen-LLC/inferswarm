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

| Requirement | Needed for |
|---|---|
| Python 3.11 or newer | everything (CI pins `3.12`) |
| `jsonschema` | `test_issue74_methodology`, `test_issue79_v2_threshold_tooling`, `test_issue86_v3_methodology`, `test_issue110_v5_custody_handoff`, and the v2/v3 unseal preflights |
| `numpy` | `test_analyze_phase1_p6` only |
| `pyyaml` | the CI YAML check, not the test suite |
| `openssl` on `PATH` | the sealing/preflight tools, not the test suite |

Everything else is standard library. No test imports `torch`, initializes
CUDA, or contacts a GPU node — `test_issue115_cleanup_retention` mechanically
asserts that the cleanup tooling cannot.

```bash
python3 -m pip install --user jsonschema numpy
```

## Running

There is no `tests/__init__.py`, so `unittest discover` does not work. Name
the modules, exactly as [`ci.yml`](../.github/workflows/ci.yml) does:

```bash
# one module
python3 -m unittest tests.test_issue117_preflight -v

# everything
python3 -m unittest $(ls tests/test_*.py | sed 's#tests/#tests.#; s#\.py$##')
```

The repository-integrity check is separate and needs no dependencies:

```bash
python3 scripts/check_phase0_workloads.py
```

## Expected result

On a clean working tree with `jsonschema` and `numpy` installed, the whole
suite passes with **5 skips**. Every skip is a host-local resource this
repository deliberately does not carry:

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

Every module guarding live evidence is in that list, including
`test_issue117_physical_retention`, which runs in the issue #117 CPU-only step.

Five modules are deliberately out:

| Module | Why it is out of CI |
|---|---|
| `test_analyze_phase1_p6` | requires `numpy`, which CI does not install |
| `test_derive_phase1_placement_v2` | historical Phase-1 derivation |
| `test_derive_phase1r_d3_placement` | historical Phase1R derivation |
| `test_derive_phase1r_d4_placement` | historical Phase1R derivation |
| `test_derive_phase1r_d7_placement` | historical Phase1R derivation |

These five guard records that are frozen and no longer change. Run them locally
before touching anything under `docs/investigations/data/`.

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
