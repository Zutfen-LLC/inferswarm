# Issue #275 collector and first demonstration

## Outcome mapped to acceptance

- Production entry point `capture_execution_273` performs one bounded CPU-fixture capture and retains each original probe byte sequence under `source/<case>/<arm>/raw/`.
- The derived `observation.json` declares `inferswarm.issue275.collector-observation/1`, inventories every retained probe with byte count and SHA-256, and distinguishes checked receipt claims from observed facts.
- Missing/empty required observations raise `CollectorMissing`; the demonstration verifies the capture root remains absent.
- Both collector and demonstration tests are registered in `r8i-qwen-qualification` and in its workflow command.

## Trust boundary

The finite `ExecutionProbes` method list in `scripts/issue275_collector.py` is the ONLY trust boundary: `read_boot_identity`, `read_start_ticks`, `read_process_census`, `read_process_cmdline`, `read_exe_identity`, `read_open_model_members`, `read_device_census`, `read_residency`, `read_process_environ`, and `read_used_vulkan_device`. The collector retains those returned bytes; every parser, validation, inventory, and derived observation downstream consumes those retained in-memory bytes. No downstream observation is an independent probe.

Round 3 (selection provenance and incarnation binding) added the last two probes and no others:

- `read_process_environ(pid)` — original contemporaneous process-environment bytes (the `/proc/<pid>/environ` shape). The process-owned `GGML_VK_VISIBLE_DEVICES` selector and `VK_ICD_FILENAMES` ICD are derived ONLY from these bytes.
- `read_used_vulkan_device(pid)` — collector-side observation of the Vulkan physical device the captured process actually used (backend, ICD, Vulkan device UUID, BDF, index, driver id). The used-device identity is derived ONLY from these bytes and is then resolved against the independently observed device census; it is never inferred from census availability plus environment claims.
- Closing incarnation binding: `read_boot_identity` and `read_start_ticks` are re-observed AFTER the execution-owned observations. The capture is accepted only when PID + boot identity + start ticks are unchanged across the window (`process.incarnation_close` in `observation.json`; retained as `raw/boot_identity.end.bin` / `raw/start_ticks.end.bin`). A reused/replaced PID or reboot splices the evidence and fails closed.

## Receipt claims are claim-only

`process_attribution.server_env.GGML_VK_VISIBLE_DEVICES`, `process_attribution.server_env.VK_ICD_FILENAMES`, and `subject_identity` labels may be retained and are cross-checked against the observed values (`observed_selection` in `observation.json` names the raw bytes it derives from). They can NEVER establish actual selection, backend, or device identity; disagreement raises a named claim-contradiction error, and a receipt without them succeeds on observed bytes alone.

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
- Device census/selection ambiguity: `device census empty/malformed`, `census entry missing/malformed <field>`, `census entry malformed bdf: expected PCI BDF`, `ambiguous device census duplicate/missing <field>`, `observed used Vulkan UUID absent/ambiguous in device census`, `used_vulkan_device BDF contradicts census entry for the used UUID`, `observed selector/used-device index disagreement (stale index assumption)`, `observed ICD disagrees between environ and used-device observation`, `unsupported observed backend`, `used_vulkan_device missing/malformed <field>`, `observed environ GGML_VK_VISIBLE_DEVICES must be a digit string`, or `process environ lacks usable <KEY> observation` / `process environ entry malformed` / `process environ is not UTF-8` / `process environ duplicate key`.
- Frozen lineage drift: `candidate observed vendor/device/ICD drift`, `candidate observed Vulkan UUID drift`, `reference observed PCI/UUID lineage mismatch`, or `positive RX580 excluded census absent`.
- Receipt contradiction: `receipt claim subject_identity.bdf contradicts derived selected device`, `receipt claim model_members contradicts derived open members`, `receipt claim exe_sha256 contradicts derived exe sha`, `receipt claim process_attribution.server_env.GGML_VK_VISIBLE_DEVICES contradicts observed selector`, or `receipt claim process_attribution.server_env.VK_ICD_FILENAMES contradicts observed ICD`.
- Incarnation binding: `process incarnation changed during capture (boot identity/start ticks mismatch)` or `closing process identity malformed`.
- Invalid residency: `residency <phase>/<bdf> counter malformed` or `excluded device <bdf> residency delta exceeds noise bound`.
- Append-only and write failures: `append-only destination exists`, `cannot create destination directory`, and `cannot write destination`; partial files are cleaned on failed writes.

## Fixture is not authority

This is CPU recording-fixture evidence only. It performs no physical execution, hardware discovery, or network access, and uses no holdout. It establishes collector byte-retention behavior, not hardware truth or qualification authority.

## Evidence and reconciliation

- Reviewed capability head: `d6a4c44` (spec review PASS, round 2; quality review APPROVED, round 2).
- Demonstration and CI-registration commit: `b1c790e` (tests/test_issue275_demo.py; scripts/ci_groups.json + scripts/plan_ci.py group/path registration; .github/workflows/ci.yml unittest line; docs/ci/test-retention-audit.json audit rows).
- Round 3 (reviewed head `246063a`): RED regressions committed first (`b52807a`; 6 failures + 2 errors demonstrating the receipt-authored-selection and unbound-incarnation defects), then the fix (`eaac7e2`): observed-selection derivation, claim-only receipt cross-checks, closing incarnation binding, `tests/test_issue275_provenance.py`, and CI/retention registration. Round 4 (`round-4 review corrections`) resolved the independent spec/quality review blockers: candidate census must match the frozen two-die BDF set exactly (omitted/extraneous devices fail closed), observed Vulkan driver identity is required and validated per-arm against the VkDriverId domain (NVIDIA_VULKAN_DRIVER_ID (collector-owned constant; the authority module is frozen) vs the census-derived DRIVER_ID_MESA_RADV), duplicate JSON keys in any probe document fail closed, probe-surface gaps (AttributeError/NotImplementedError) classify as CollectorMissing, empty boot identity and negative start ticks fail closed, residency counters must be objects with type(bytes) is int (bool rejected), huge selector strings raise CollectorError not ValueError, and the frozen reference identity is emitted as `reference_identity_expected` (expected/claim), never as an observation. Test migration note: the committed RED suite's first test originally asserted the (defective) acceptance of a receipt-authored selection; its successor in `tests/test_issue275_provenance.py` asserts the corrected claimless-receipt positive case, so the RED→GREEN mapping is semantic per defect, not a byte-identical suite. 57 tests across the three #275 modules pass.
- Test result: 19 collector tests and 1 demonstration test; the requested five-module subset passed 92 tests in 322.717 seconds.
- Reconciliation pointer: campaign branch `issue-273-r8i6a-comparator2-corrective`, including its current branch state and issue #275 Task 1 collector implementation.
