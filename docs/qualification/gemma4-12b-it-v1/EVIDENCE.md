# Evidence and invalid-run rules

## Producer and preflight

Every physical arm must use a clean producer derived from FreeToken commit
`d4d16089165917704a87f4e2f0c4a09969646f95`. Record the producer commit and
build hashes. Stop if the source tree is dirty.

Complete `schemas/preflight.schema.json` before each arm. Compare every
applicability field with the frozen subject. Stop on a mismatch. Record device
UUIDs as diagnostic identity. Require two different RTX 3060 UUIDs for a class
claim. The RTX 3090 reference remains instance-bound.

## Attempt retention

Assign a unique attempt ID before execution. Retain every attempt, including an
invalid attempt. Do not overwrite evidence. Link a repeat to the prior attempt
and its frozen invalidity reason.

A valid failing case is final evidence. Never repeat it to obtain a better
result.

An attempt is infrastructure-invalid only for one of these prospective codes:

- `PROCESS_DID_NOT_START`;
- `PROCESS_CRASH_BEFORE_FIRST_CASE`;
- `NODE_OR_LINK_LOST_BEFORE_CASE_COMMIT`;
- `ARTIFACT_WRITE_OR_HASH_FAILURE`;
- `OPERATOR_ABORT_BEFORE_CASE_COMMIT`;
- `PREFLIGHT_IDENTITY_CHANGED_BEFORE_CASE_COMMIT`;
- `EVIDENCE_SCHEMA_OR_COMPLETENESS_FAILURE`.

If a failure occurs after a case commit, retain the committed case as valid.
Repeat only incomplete cases. Do not repeat any committed numerical or semantic
failure.

These events are valid failures, not infrastructure-invalid runs:

- exact identity, state, boundary, attribution, or path mismatch;
- fallback or substitution;
- same-device nondeterminism;
- NaN or Inf;
- a numerical-envelope exceedance;
- a greedy-token mismatch;
- an applicable device or role coverage failure.

Use `INSUFFICIENT_EVIDENCE` when required evidence is absent or invalid. Do not
use it for a valid numerical exceedance.

## Evidence order

1. Freeze and hash preflight.
2. Execute the authorized arm.
3. Hash native tensor bytes before reduction.
4. Record exact and semantic checks.
5. Reduce the full declared domains.
6. Validate the attempt with `schemas/attempt-evidence.schema.json`.
7. Retain the immutable attempt and its hash.

The calibration summary may refer only to retained Arm D calibration hashes.
It must not contain a holdout field or an `h74-` case ID.

## Methodology execution audit

The issue #74 methodology build is CPU-only. It can read the pinned tokenizer
JSON and run Python standard-library tests. It can use OpenSSL to seal content.
It must not import torch, FreeToken, Transformers model classes, CUDA, Triton,
or a native execution extension. It must not query or initialize a GPU. It must
not read model weight files. It must not execute any calibration arm.
