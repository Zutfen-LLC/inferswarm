# V1-C — selector-aware successor accounting and NV-A portability proof

Status: in progress (Issue #161). This additive namespace was created at
Phase 0 before any modification; historical V0/V1-A/V1-B evidence and the
accepted hash-pinned sources are byte-unchanged.

## What this campaign is

The separately authorized prospective repair boundary required by the
accepted V1-B finding (`V1B_SECOND_SUBJECT_REFACTOR_REQUIRED`): replace
the first-subject-pinned accounting assumption with a selector-aware
reusable Vulkan accounting reducer, and complete a fresh plan-driven
NV-A canonical proof under a new authority — without rewriting or
promoting any historical campaign.

## Lifecycle strategy

Successor module, not in-place edit. The accepted
`scripts/v0c_canonical_run.py::parse_accounting` is hash-pinned by the
accepted V0-C/V1-A/V1-B manifests; editing it in place would invalidate
those fixed-inventory manifests (each manifest pins the producer bytes
it was generated from). The successor reducer
`scripts/v1c_accounting.py` preserves the accepted accounting semantics
exactly while parameterizing the selected Vulkan resource label from
frozen authority data. The V1-C orchestration (`scripts/v1c_runner.py`)
reuses the accepted V1-A participant, adapter, runner stages, and
byte-exact comparator unchanged, superseding only the accounting stage.

## Nonclaims

Reusable internal seam cross-subject reproduction only; not production
Vulkan support; not a public plugin API; not default/preferred-backend
policy; no broad hardware/model qualification; no comparator
recalibration or new tolerance; no Vulkan/CUDA numerical-equivalence
claim; the accepted NV Vulkan-vs-CUDA output difference is not
reinterpreted; SSH is not used.
