# Plan-Driven Model Artifact Acquisition — Issue #99

Status: **Complete: `PLAN_DRIVEN_ARTIFACT_ACQUISITION_PASS`**

Implements and proves the minimum end-to-end plan-driven model artifact
acquisition seam required by
[ADR 0009](../../adr/0009-plan-driven-model-artifact-distribution.md) and the
[Model Artifact Distribution](../../architecture/model-artifact-distribution.md)
supplement: a frozen Execution Plan determines each participant's required
immutable artifacts; a participant that begins without any local model
repository acquires exactly those artifacts from an authorized Source,
verified before trust, resumable across interruption, cache-reusable, and
fail-closed against wrong/corrupt/unauthorized/unrelated bytes — with zero
unrelated model bytes and zero unexplained whole-model dependency.

- Methodology and arm list: [methodology.md](methodology.md)
- Machine-readable retained evidence: [evidence/](evidence/)
  (integrity anchor: [evidence/MANIFEST.sha256](evidence/MANIFEST.sha256))
- Producers: `scripts/issue99_artifact_core.py` (generic, model-independent
  seam), `scripts/issue99_mini_model.py` (strategy/fixture boundary),
  `scripts/issue99_proof.py` (canonical campaign)
- Tests: `tests/test_issue99_artifact_core.py`, `tests/test_issue99_proof.py`

This is an internal-first implementation: schemas, digests, cache layout, and
source descriptors remain intentionally unfrozen, and no public CAS/manifest
or peer protocol is defined. Physical FreeToken-runtime integration, peer
sourcing, transfer optimization, and cache-locality planning are later work.
