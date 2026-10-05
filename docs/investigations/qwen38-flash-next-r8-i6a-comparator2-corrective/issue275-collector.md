# Issue #275 collector and first demonstration

## Outcome mapped to acceptance

- Production entry point `capture_execution_273` performs one bounded CPU-fixture capture and retains each original probe byte sequence under `source/<case>/<arm>/raw/`.
- The derived `observation.json` declares `inferswarm.issue275.collector-observation/1`, inventories every retained probe with byte count and SHA-256, and distinguishes checked receipt claims from observed facts.
- Missing/empty required observations raise `CollectorMissing`; the demonstration verifies the capture root remains absent.
- Both collector and demonstration tests are registered in `r8i-qwen-qualification` and in its workflow command.

## Trust boundary

The finite `ExecutionProbes` method list in `scripts/issue275_collector.py` is the ONLY trust boundary: `read_boot_identity`, `read_start_ticks`, `read_process_census`, `read_process_cmdline`, `read_exe_identity`, `read_open_model_members`, `read_device_census`, and `read_residency`. The collector retains those returned bytes; every parser, validation, inventory, and derived observation downstream consumes those retained in-memory bytes. No downstream observation is an independent probe.

## Retained-byte contract

- `raw/*.bin` contains probe output verbatim, without normalization or re-encoding.
- `observation.json`'s `probe_inventory` records SHA-256 and byte length for each raw path; the observation is derived-only.
- `receipt.json` preserves the caller-provided serialized receipt representation. Receipt labels are claims, not observations; only named cross-checks appear in `receipt_claims_checked`.

## Fail-closed inventory

The collector rejects invalid evidence before committing the bundle. Guard and rejection reason strings include:

- Required probe absent/empty/non-bytes: `CollectorMissing`, e.g. `read_boot_identity returned missing/empty output` (absent-file and key paths report `<method> absent: ...`).
- Unsafe case or destination: `unsafe case`, `unsafe destination path`, `symlink destination ancestor`, `unsafe destination directory`, or `symlink capture root`.
- Invalid arm/repeat/receipt and required nested fields: `unknown arm`, `repeat must be bool`, `receipt must be an object`, `process_attribution must be an object`, `process_attribution.server_env must be an object`, `subject_identity must be an object`.
- Process identity malformed or inconsistent: `process_attribution.server_pid invalid`, `process identity malformed`, `process census/boot mismatch`, `process not found uniquely in census`, `census/boot mismatch vs start-tick bytes`.
- Executable/model contradiction: `exe_identity path/sha256 malformed`, `exe_identity.sha256 != expected comparator sha`, `effective --model argument contradicts frozen model member path`, or `open_model_members contradict frozen model members`.
- Device census/selection ambiguity: `device census empty/malformed`, `census entry missing/malformed <field>`, `census entry malformed bdf: expected PCI BDF`, `ambiguous device census duplicate/missing <field>`, or `selector does not resolve exactly one census device`.
- Frozen lineage drift: `candidate observed vendor/device/ICD drift`, `candidate observed Vulkan UUID drift`, `reference observed PCI/UUID lineage mismatch`, or `positive RX580 excluded census absent`.
- Receipt contradiction: `receipt claim subject_identity.bdf contradicts derived selected device`, `receipt claim model_members contradicts derived open members`, or `receipt claim exe_sha256 contradicts derived exe sha`.
- Invalid residency: `residency <phase>/<bdf> counter malformed` or `excluded device <bdf> residency delta exceeds noise bound`.
- Append-only and write failures: `append-only destination exists`, `cannot create destination directory`, and `cannot write destination`; partial files are cleaned on failed writes.

## Fixture is not authority

This is CPU recording-fixture evidence only. It performs no physical execution, hardware discovery, or network access, and uses no holdout. It establishes collector byte-retention behavior, not hardware truth or qualification authority.

## Evidence and reconciliation

- Reviewed capability head: `d6a4c44` (spec review PASS, round 2; quality review APPROVED, round 2).
- Demonstration and CI-registration commit: `b1c790e` (tests/test_issue275_demo.py; scripts/ci_groups.json + scripts/plan_ci.py group/path registration; .github/workflows/ci.yml unittest line; docs/ci/test-retention-audit.json audit rows).
- Test result: 19 collector tests and 1 demonstration test; the requested five-module subset passed 92 tests in 322.717 seconds.
- Reconciliation pointer: campaign branch `issue-273-r8i6a-comparator2-corrective`, including its current branch state and issue #275 Task 1 collector implementation.
