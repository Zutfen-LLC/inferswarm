# V1-C — supersede the subject-pinned accounting reducer and complete NV-A portability proof

Status: physical campaign complete on `inferswarm02` (Issue #161); terminal `V1C_CROSS_SUBJECT_PORTABILITY_PASS`, recorded in draft PR #162 pending maintainer review. This terminal independently resolves the blocker discovered by accepted V1-B; the V1-B historical terminal `V1B_SECOND_SUBJECT_REFACTOR_REQUIRED` is retained verbatim and was never rewritten or promoted.

## What this campaign did

The accepted V1-B campaign proved the second physical subject (NV-A, RTX 3060 Ti, BDF `04:00.0`, selector `Vulkan3`) physically viable end-to-end through the accepted generic seam, except the accepted V0-C accounting reducer failed closed because it hardcodes the first subject's selector label. This campaign is the separately authorized prospective repair:

- **Successor accounting reducer** (`scripts/v1c_accounting.py`, schema `inferswarm.v0c.materialization-accounting/2`): preserves the accepted /1 accounting semantics exactly while parameterizing the selected Vulkan resource label from frozen authority data. No selector, BDF, vendor, or device name appears in the reusable logic; observed values appear only in compatibility fixtures bound to accepted retained evidence.
- **Retained-transcript regression proof** (`RETAINED-TRANSCRIPT-REGRESSIONS.json`): against the accepted retained V1-A transcript the successor reproduces the accepted accounting artifact field-by-field AND byte-identically over shared facts; against the accepted retained V1-B Vulkan3 transcript it reduces cleanly with the 0/0/0 three-tuple from direct runtime evidence (retrospective only — not the physical PASS). Eleven negative controls prove fail-closed behavior (wrong/missing/malformed selector, duplicate rows, ambiguous/missing final rows, contradictory totals, unexplained host mirror, post-ready fetch/movement, and cross-device transcripts reduced under exactly the frozen selector).
- **V1-C orchestration** (`scripts/v1c_runner.py`): reuses the accepted V1-A participant, adapter, runner stages, and byte-exact comparator UNCHANGED; the only superseded stage is canonical accounting.
- **Prospective authority** (`PHYSICAL-AUTHORITY.json`): frozen and pushed (commit `c43a544`) before any V1-C correctness-bearing physical output, with re-measured NV-A identity (selector, loader, ICD, driver, VRAM), exact reuse of the accepted runtime/model/prompt/configuration (hash-verified, no drift), and the accepted V1-B subject-local byte-exact reference (`9013db8f...`) inherited unchanged — no recalibration, no new tolerance. Repeatability is inherited from the accepted V1-B 3/3 stability sample, explicitly recorded as inherited rather than newly measured.

## Fresh campaign evidence

- qualification `v1c-nv-a-qualification-01`: PASS, 37/37 offload, no fallback, clean exit, adapter-sealed observation, measured wall 14.737 s as the honest objective value;
- generic plan `v1c-nv-a-plan-01`: the production generic planner selected NV-A from opaque facts; the AMD pressure resource was excluded `EVIDENCE_STALE` with honest unfalsified economics; frozen plan digest `1a9822071ed8b3c879d15c4c1f66b9f85120ada5a6a165cd31f4598445be582b`;
- canonical execution `v1c-nv-a-canonical-01`: exit 0, 37/37 offload, intended device, no fallback, selector-aware accounting `0/0/0`, byte-exact visible output vs the frozen reference, adapter-sealed canonical proof, generic canonical observation, and execution receipt attributed to the exact visible response bytes and frozen plan;
- cross-subject audit (`CROSS-SUBJECT-AUDIT.json`): PASS — accepted generic semantics reused, selector classified `SELECTOR_AUTHORITY_DATA_ONLY`, accounting refactor `GENERIC_ACCOUNTING_REFACTOR_ACCEPTED`, no subject-specific code on the canonical reusable path, no foundational invariant falsified.

## Lifecycle strategy

Successor module, not in-place edit: the accepted reducer's bytes are hash-pinned by the accepted V0-C/V1-A/V1-B fixed-inventory manifests, so an in-place edit would invalidate accepted evidence. All historical namespaces (`vulkan-v0-a/b/c`, `vulkan-v1-a`, `vulkan-v1-b`) are byte-unchanged; all accepted source hashes verified at Phase 0 and re-verified by the V1-C manifest.

## Nonclaims

Reusable internal seam cross-subject reproduction only; not production Vulkan support; not a public plugin API; not default/preferred-backend policy; no broad hardware/model qualification; no comparator recalibration or new tolerance; no Vulkan/CUDA numerical-equivalence claim; the accepted NV Vulkan-vs-CUDA output difference is not reinterpreted; SSH is not used.
