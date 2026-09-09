# Tooling

Most executables in this directory are **evidence tooling**, not product code.
`sync_project_status.py` is living documentation-maintenance tooling; its
[maintenance contract](../docs/status-maintenance.md) permits reviewed updates.
InferSwarm has no released runtime; these scripts derive, freeze, verify, or
diagnose the retained records under [`docs/`](../docs/). The runtime
experiments themselves live in the
[Zutfen FreeToken fork](../docs/integrations/freetoken.md).

Repository precedence is unchanged:

> **[ADRs](../docs/adr/README.md) decide; the
> [Fabric Doctrine](../docs/architecture/fabric-doctrine.md) specifies;
> [ARCHITECTURE.md](../ARCHITECTURE.md) explains;
> [ROADMAP.md](../ROADMAP.md) sequences.**

A script here implements what an accepted methodology already froze. It does
not decide methodology.

## Conventions every script follows

- **CPU-only and offline.** No script in this directory imports a model
  runtime, initializes CUDA/Triton, or reaches a GPU node. The
  correctness-qualification tools state this in their own docstrings and
  several are mechanically proven not to import `torch`.
- **Deterministic.** Re-running a generator or builder on the same accepted
  inputs reproduces byte-identical output (canonical JSON, sorted keys,
  fixed separators). That property is what lets a test assert a SHA-256.
- **Fail-closed.** A verifier refuses to grant permission when a precondition
  is missing, ambiguous, or hash-drifted. It does not warn and continue.
- **Non-decrypting.** No `verify_*_unseal.py` preflight contains or can reach
  a CMS decrypt operation. Only `seal_issue74_holdout.py` has an `unseal`
  subcommand, and it is gated by the campaign's own authorization rules.
- **Pure standard library, with three exceptions.** `analyze_phase1_p6.py`
  needs `numpy`; `verify_issue79_v2_unseal.py` and
  `verify_issue86_v3_unseal.py` need `jsonschema`. Some tools shell out to
  `openssl` for public-key DER derivation only. The Issue #129 real-tokenizer
  proof needs the exact packages in its retained `requirements.txt`.

## The frozen-producer rule — read before editing anything here

Most of these scripts are **hash-pinned producers**. Their SHA-256 is
recorded inside retained evidence (`producer-hashes.json`,
`MANIFEST.sha256`, `build-audit.json`, `TOOLING.md`, unseal records), and
tests assert those exact values. Editing one silently invalidates the
evidence that cites it.

Consequences in practice:

- **Do not reformat, retype, or "fix" a pinned script** — including a
  docstring typo. A cosmetic edit is still a hash change.
- A methodology repair is a **new** script bound to the old one by a
  deterministic builder, not an in-place edit. The worked example is
  `build_issue110_v5_threshold_adapter.py`: it reads
  `issue109_v5_thresholds.py` (exact SHA-256 required), performs exactly one
  substitution, and emits `issue110_v5_thresholds.py` — with
  `tests/test_issue110_v5_custody_handoff.py` proving a one-line source
  diff, function-bytecode identity, and constant-by-constant equality.
- Superseded selectors and derivers are **retained, not deleted**
  (`select_issue74_margin_stress.py` alongside its v2/v3/v4/v5 successors).
  The old file is the provenance of the old result.

### Preserved docstring misattributions

Three v4 tools carry a docstring that names issue #86 where the artifact they
freeze is v4 / issue #95. The **behavior** is correct and matches the accepted
v4 methodology in every case; only the prose attribution is wrong.

| Script | Its docstring says | Correct attribution |
|---|---|---|
| `generate_issue95_corpora.py` | "the deterministic v4 corpora frozen by InferSwarm issue #86" | the v4 corpora are frozen by **issue #95**; the corpus-generation *machinery* is what is inherited unchanged from issue #74/v1, not the freeze |
| `select_issue95_margin_stress_v4.py` | "Select the eight v4 stress cases from reference-only margins (issue #86)" | the v4 selection is frozen by **issue #95**; the eligibility *rule* it applies is the one prospectively established in issue #86 section 2 |
| `commit_issue95_stress_selection.py` | "InferSwarm issue #86: freeze the v4 stress-selection commitment" | the commitment is frozen by **issue #95** |

In each case the misattribution appears to be inherited text from the v3
predecessor that was not updated when the v4 tool was derived from it. The
reference to #86 is not meaningless — the v4 eligibility rule genuinely comes
from #86 — but the freeze these tools implement is #95's.

**These docstrings are deliberately not corrected.** All three files are
hash-pinned by accepted v4 evidence. Editing a byte would change the SHA-256
that evidence records, forcing an update to accepted manifests purely to repair
historical prose — provenance churn with no correctness benefit, in a
repository whose entire value rests on those hashes meaning what they say.

The rule for successors: **a new tool carries a corrected description.** When a
v6 generator, selector, or commitment tool is derived from one of these, write
its docstring to name its own gate, and inherit only the machinery. Do not
propagate the misattribution, and do not retroactively repair the frozen ones.

## Running them

See [`../tests/README.md`](../tests/README.md) for the interpreter version,
dependencies, and the full verification procedure. The single check that runs
without any third-party package is:

```bash
python3 scripts/check_phase0_workloads.py
```

## Inventory by lane

### Repository integrity

| Script | Purpose |
|---|---|
| `sync_project_status.py` | Renders living status sections and checks for drift; refreshes only explicitly maintained documentation/CI manifest rows. Does not grant execution authority. |
| `check_phase0_workloads.py` | Validates the frozen Phase-0 workload manifest without model or GPU access. Wired into CI. |

### Phase 0 / Phase 1 / Phase1R derivation and analysis

Historical publication and derivation tools. Their outputs are the
byte-preserved records under
[`docs/investigations/data/`](../docs/investigations/data/README.md) and
[`docs/benchmarks/results/`](../docs/benchmarks/README.md).

| Script | Purpose |
|---|---|
| `analyze_phase1_p6.py` | Deterministic analysis for the `f29013fd` Phase-1 P6 campaign. Requires `numpy`. |
| `derive_phase1_placement.py` | Historical v1 derivation of sanitized P0-I routing evidence and the frozen Phase-1 placement. |
| `derive_phase1_placement_v2.py` | Corrected v2 placement derivation from canonical P0-I evidence only. |
| `derive_phase1r_d3_placement.py` | Frozen D3 two-worker placement from sanitized P0-I counts. |
| `derive_phase1r_d4_placement.py` | D4 capability-weighted placement from frozen P0-I and calibration. |
| `derive_phase1r_d7_placement.py` | Frozen D7 fan-in-sparse placement from exact P0-I routes; the D3 top-6000 union is immutable. |

### Correctness qualification — v1 (issues #74 / #76 / #79)

| Script | Purpose |
|---|---|
| `generate_issue74_corpora.py` | Deterministic prompt corpora from the pinned tokenizer JSON only. |
| `issue74_methodology.py` | CPU-only reducers and derivations for the v1 methodology. |
| `build_issue74_manifests.py` | Frozen manifests built from the v1 corpus artifacts. |
| `hash_issue74_artifacts.py` | Review manifest over every v1 artifact. |
| `select_issue74_margin_stress.py` | v1 eight-case stress selection from reference-only margins. |
| `seal_issue74_holdout.py` | Seals (and, under campaign authorization only, unseals) the v1 holdout with OpenSSL CMS. |
| `commit_issue74_holdout.py` | Public commitment for the newly sealed v1 holdout. |
| `generate_issue76_stress_pool_v2.py` | v2 stress pool after the stopped #76 attempt; v1 machinery unchanged. |
| `select_issue76_margin_stress_v2.py` | v2 selector; v1 selector retained separately as provenance. |
| `issue79_v2_thresholds.py` | Versioned v2 threshold derivation, fail-closed. |
| `verify_issue79_v2_unseal.py` | Non-decrypting v2 unseal preflight. Requires `jsonschema`. |

### Semantic contract (issue #83)

| Script | Purpose |
|---|---|
| `issue83_first_divergence.py` | Re-derives the first-divergence aggregates from committed evidence; pure stdlib so it runs anywhere. |

### Correctness qualification — v3 (issues #86 / #88)

| Script | Purpose |
|---|---|
| `generate_issue86_corpora.py` | Deterministic v3 corpora; v1 generation machinery unchanged. |
| `issue86_v3_methodology.py` | The #83 semantic contract as executable v3 methodology. |
| `issue86_v3_thresholds.py` | v3 threshold derivation from calibration-only summaries. |
| `select_issue86_margin_stress_v3.py` | v3 stress selection under the #86 eligibility rule. |
| `commit_issue86_stress_selection.py` | Freezes the public v3 stress-selection commitment. |
| `commit_issue86_holdout.py` | Public commitment and custody record for the sealed v3 holdout. |
| `build_issue86_schemas.py` | Emits the versioned v3 JSON Schemas byte-identically. |
| `build_issue86_disjointness.py` | Mechanical v3 disjointness proof. |
| `verify_issue86_v3_unseal.py` | Non-decrypting v3 unseal preflight. Requires `jsonschema`. |

### Post-v3 diagnosis and doctrine (issues #90 / #93)

| Script | Purpose |
|---|---|
| `issue90_post_v3_diagnosis.py` | Read-only re-derivation of every quantity in the post-v3 `DIAGNOSIS.md`, hash-pinned to accepted #88/#86 bytes. |

### Correctness qualification — v4 (issues #95 / #97)

| Script | Purpose |
|---|---|
| `generate_issue95_corpora.py` | Deterministic v4 corpora (docstring misattributes this to #86; see above). |
| `issue95_v4_methodology.py` | v4 prediction-aligned methodology under the #93 two-tier classification. |
| `issue95_v4_contract.py` | Pure CPU/static contract checks for the v4 freeze. |
| `issue95_v4_thresholds.py` | v4 threshold derivation from complete calibration evidence only. |
| `select_issue95_margin_stress_v4.py` | v4 stress selection (docstring misattributes this to #86). |
| `commit_issue95_stress_selection.py` | Freezes the public v4 stress-selection commitment (docstring misattributes this to #86). |
| `commit_issue95_holdout.py` | Public commitment and custody record for the sealed v4 holdout. |
| `build_issue95_schemas.py` | Emits the versioned v4 JSON Schemas byte-identically. |
| `build_issue95_disjointness.py` | v4 public prompt/token hash disjointness proof. |
| `verify_issue95_v4_unseal.py` | Non-decrypting v4 unseal preflight. |

### Post-v4 diagnosis and doctrine (issues #105 / #108)

| Script | Purpose |
|---|---|
| `issue105_post_v4_core_diagnosis.py` | Read-only re-derivation of the post-v4 core diagnosis from retained raw FP32 rows. |
| `issue108_post_v4_statistical_metric_doctrine.py` | Validates the accepted statistical and metric-core doctrine; successor methodologies validate against this module rather than a local copy. |

### Correctness qualification — v5 (issues #109 / #110 / #115)

| Script | Purpose |
|---|---|
| `generate_issue109_corpora.py` | IID mixture-population corpora — the construction that replaced the v1/v3/v4 balanced-cell design. |
| `issue109_v5_methodology.py` | The v5 mixture-population methodology instantiating ADR 0012 / issue #108. |
| `issue109_v5_contract.py` | Pure CPU/static contract checks for the v5 freeze. |
| `issue109_v5_methodology_freeze.py` | Validates and assembles the freeze against the accepted #108 statistical contract. |
| `issue109_v5_thresholds.py` | Accepted v5 threshold deriver. **Frozen; superseded in use by the #110 adapter.** |
| `select_issue109_margin_stress_v5.py` | v5 stress selection; eligibility unchanged from v4. |
| `commit_issue109_stress_selection.py` | Freezes the public v5 stress-selection commitment. |
| `commit_issue109_holdout.py` | Reads the plaintext holdout once on the sealing host and emits the public commitment plus custody record. |
| `build_issue109_schemas.py` | Emits the versioned v5 JSON Schemas byte-identically. |
| `build_issue109_build_audit.py` | The v5 provenance/build audit. |
| `build_issue109_disjointness.py` | v5 historical-exclusion and collision audit. |
| `build_issue109_historical_exclusion.py` | The fixed historical prompt/token exclusion inventory. |
| `validate_issue109_prerequisites.py` | Fails closed on immutable v5 prerequisite source identities. |
| `verify_issue109_v5_unseal.py` | Non-decrypting v5 unseal preflight. |
| `issue110_v5_custody.py` | Non-decrypting custody validation and deterministic construction of the effective completed custody record. |
| `build_issue110_v5_threshold_adapter.py` | Deterministic builder: reads the accepted #109 deriver by exact SHA-256, substitutes only the custody-record hash constant. |
| `issue110_v5_thresholds.py` | The generated adapter — the deriver actually used for the executed v5 campaign. |

### Plan-driven artifact distribution (issues #99 / #101 / #103)

| Script | Purpose |
|---|---|
| `issue99_artifact_core.py` | The model-independent acquisition core required by ADR 0009. |
| `issue99_mini_model.py` | The model-specific side of the #99 seam: a compact proving model and strategy adapter. |
| `issue99_proof.py` | Runs the canonical #99 acquisition proof and emits its evidence. |
| `issue101_fixture.py` | Deterministic CPU strategy and independent reference for #101. |
| `issue101_orchestration.py` | Node inventory, source selection, peer publication, replacement-plan deltas. |
| `issue101_proof.py` | Emits the isolated #101 orchestration evidence. |
| `issue103_fixture.py` | Deterministic opaque CPU fixture for #103. |
| `issue103_planner.py` | The internal generic ranking seam where artifact locality is ranking evidence, not a feasibility rule. |
| `issue103_proof.py` | Emits the isolated #103 transition-planning evidence. |

### R6 successor integration (issue #117)

| Script | Purpose |
|---|---|
| `issue117_gemma_strategy.py` | The **only** place model-family and accepted-campaign nouns for this integration live — the "strategy constrains" side of the accepted rule. |
| `issue117_planner.py` | The model-independent admission planner: strategy legality, then the qualification-applicability barrier as a distinct recorded gate. |
| `issue117_subject_identity.py` | The projection from a complete candidate subject to the execution-equality subject the qualification gate compares. |
| `issue117_accepted_subject.py` | Reconstructs the historical subject the accepted V5 qualification was adjudicated against, from byte-pinned evidence only. |
| `issue117_applicability.py` | The fail-closed applicability barrier and producer-delta collector over the correctness-bearing execution zone. |
| `issue117_checkpoint_authority.py` | Deterministic checkpoint-authority validator: authority SHA-256 equals the SHA-256 of the `model.safetensors` bytes. |
| `issue117_integration_fixture.py` | Selects one public case per frozen mixture component from the accepted `c109-*` corpus. |
| `issue117_preflight.py` | The physical preflight record schema and its fail-closed validation, required before any correctness-bearing arm. |
| `issue117_proof.py` | Runs the CPU integration-freeze campaign and emits its evidence. |
| `issue129_arm_c_retry_core.py` | Runs the CPU-only Arm-C retry methodology. It proves the real frozen tokenizer and Coordinator rendering, exact runtime-call equality, immutable accepted history, campaign-scoped STOP behavior, and fixed-path accepted-Git authority binding. |

## Adding a script

1. Confirm the roadmap gate actually calls for it. Tooling is frozen when the
   methodology it serves is accepted, not before.
2. Give it a docstring that states its lane, its CPU-only posture, and what
   it fails closed on.
3. Keep output deterministic and canonical.
4. Add a test under [`../tests/`](../tests/README.md) and wire it into
   [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
5. If it produces retained evidence, record its SHA-256 in that evidence and
   treat the file as frozen from then on.
