# Issue #250 — METHODOLOGY AMENDMENT 009: exact source-pin correction

Date: 2026-09-30 UTC (2026-09-29 EDT). Repository-only correction of PR #251
comment 5901201290; starting reviewed head
`6bb83a4bdfd4a9cb5f87f5e58635e3bc4bceca1a`, accepted main
`bc71774dc68e7d7fddaf97bd794bbbc297e66ca5`.

## Defect and independent authority

The old executable source authority was
`b29c606e28a01b1bc8c1351026a0fae616bf6c4` (39 characters).
It is not a full Git SHA. It entered the Phase-0/diagnostic tooling in
commit `4b296f01cc58d784e6544d1562def8e0ed15c880`. Its similarity to a real
revision is not authentication; no insertion, normalization, prefix lookup,
or fuzzy repair is allowed.

The accepted full source authority is independently
`b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`. Mechanically inspected,
byte-preserved predecessor bindings on accepted main are:

- R8-B `evidence/runtime-authority/runtime-authority.json`, line 4:
  `llama_cpp_commit` equals the complete revision; `TOPOLOGY-FREEZE.md`
  line 10 independently freezes the same clean-clone source.
- R8-E `evidence/instrumentation/instrumentation.json`, line 2:
  `base_commit` equals it; `r8e-build.sh` line 11 creates that exact worktree.
- R8-H `evidence/PHYSICAL-AUTHORITY.json`, line 183, and
  `evidence/freeze/campaign-freeze.json`, line 255: `llama_cpp_pin` equals it.
  `evidence/runtime/armB-runtime.json`, line 68, binds the same source
  revision to canonical Vulkan server digest
  `21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e`.
- Accepted #241 predecessor
  `4e8b4fc369defe409f68da46e26d152eade4df47:scripts/issue241_constants.py`
  explicitly freezes `LLAMA_CPP_PIN` to the complete revision and binds
  comparator/2's observation-only patched source to that accepted base.
  Merged #248 `scripts/issue248_diagnostic.py`, lines 96–100 and 121–125,
  identifies the three accepted builds of that source family and pins
  the comparator to
  `6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad`.
  The retained #248 terminal-reduction also binds this exact comparator.

`evidence/source-pin-correction/source-authority.json` records exact
immutable `commit:path` identities and SHA-256 values for these inputs.
These accepted repository bindings, not the host checkout or a repaired
spelling, establish that the 39-character string is a transcription defect.
The accepted source tree is `950999fe62b7fe55f44ab5b7394e3c8542f37f12`.

## Prospective correction and fail-closed contract

`issue250_diagnostic.LLAMA_PIN` now equals the complete accepted revision.
`V0_SOURCE_PIN` and `V0N_SOURCE_PIN` are prospective aliases of that pin.
All executable source tokens must be exactly 40 lowercase hexadecimal
characters and must equal the independently established accepted source.
The validator returns the unchanged token or rejects it; there is no
normalization or repair path. Malformed or mismatched freezes/aliases fail
before a dispatch fetch or execution callback.

The production authority fetcher now invokes `verify_source_build` BEFORE
GitHub authority lookup. This NONPHYSICAL preflight reads Git HEAD/tree and
status, hashes the accepted comparator, resolves ELF dependencies with `ldd`,
and hashes all eight frozen observer libraries. Absent, duplicate, mismatched,
unresolved, or CUDA-linked observer dependencies fail closed. It does not
invoke the server, including help/list-devices, load a model, attest model
bytes, post dispatch, or create a physical unit. The accepted binary hashes
authenticate the retained build; no new build or pristine working directory
is claimed. Existing observation-only source modifications are reported.

## Historical bytes and consumer audit

The frozen Phase-0 source/analysis, original methodology and amendments,
accepted V0/V0n receipts, bridge record, and #248 physical populations remain
verbatim. In particular, `issue250_phase0.LLAMA_PIN` and Phase-0's committed
analysis preserve the defective historical label for deterministic historical
reconstruction only; they are NOT prospective executable source authority.
This amendment supersedes their spelling where it was described as a Git pin.
No historical analysis or manifest is regenerated to manufacture a new record.

`HISTORICAL_SOURCE_LABEL` is an explicit historical schema /1 custody label,
not a valid Git pin. Retained V0 consumers admit its exact bytes ONLY at
`ACCEPTED_V0_EXECUTED_HEAD`; retained V0n consumers do so ONLY at
`ARM_A_BRIDGE_EVIDENCE_HEAD`. Live placement checks default to the corrected
source pin; the retained V0 verifier passes its independently authenticated
predecessor head explicitly. Neither label is repaired or resolved.
Re-signed prospective freezes carrying the historical label still reject.
The amendment-008 synthetic predecessor fixtures retain the historical label
explicitly so their unchanged frozen custody validators remain exercised.

The current preparation root is not rewritten/rebound by this correction.
It still names its historical reviewed producer/dispatch context, remains
attempt-free, and cannot execute at a new producer head. No top-level V0/V0n
population is synthesized. Only a separately reviewed, exact-head prepared
campaign and fresh maintainer dispatch can permit later execution.

## Read-only verification and preservation

`evidence/source-pin-correction/nonphysical-preflight.json` retains real
inferswarm01 observations from the corrected producer bytes, supplied in
memory without modifying any host checkout or preparation root:

- `/home/hermes/llama.cpp` HEAD and committed tree exactly match accepted
  source authority; existing server-context.cpp instrumentation and untracked
  observation worktrees are explicitly retained as status, not hidden.
- The comparator executable remains exactly the accepted SHA-256 above.
- All eight resolved observer-library hashes match the frozen accepted family;
  no dependency is unresolved and no CUDA dependency participates in that family.
- The real retained predecessor populations re-authenticate through the custody
  verifiers/reducers: V0 `CROSS_VENDOR_DISAGREEMENT_STOP_BLOCKED`, V0n
  `CURRENT_NVIDIA_VARIABLE_STOP`. This is offline verification, NOT an Arm-A
  result or new execution authority.

Before/after complete-file inventories are byte-equal: inferswarm01 V0 copy
43 files, V0n 27 files, #248 535 files, existing preparation root 78 files.
The original inferswarm05 V0 population also equals the 43-file custody copy.
`preservation-check.json` binds the inventories in `retained-file-inventories.json`.
No accepted repository evidence or parent manifest has changed. This successor
slice has its own bundle-local manifest; no parent bundle is extended.

## Tests and authority boundary

The source-pin regressions exercise predecessor authority equality, strict
shape rejection, malformed/mismatched source and aliases before authority or
execution, real production-shaped positive source/build/library preflight,
source-tree/library drift, unresolved/CUDA library rejection, exact historical
head scoping, and competent re-signed prospective freeze attacks. No test
repairs or normalizes a source pin. Existing amendment-008 admission/provenance
coverage remains controlling.

This is a source-authority correction only: no architecture, capability,
accepted gate result, project-status decision, comparator methodology,
threshold, or later-arm authority changes. Living status need not be promoted.
Validation at the exact correction head is reported in the PR body/status;
this committed observation slice binds producer SHA-256 bytes, avoiding a
self-referential commit SHA.

ZERO physical Arm-A units attempted, no fresh dispatch, no server launch,
model inference, B/C/C1/C2/D discriminator, holdout access, or R8-J work.
Stale dispatch `5896620975` remains unusable and was not reused.
Defect report `5901201290` is addressed by repository correction only.
A NEW exact-head `d250-arm-a` maintainer dispatch remains mandatory AFTER
maintainer exact-head re-review. Green checks grant no execution authority.
STOP for that re-review; do not merge or dispatch Arm A.
