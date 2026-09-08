# Issue #117 checkpoint-authority blocker

Status (historical, at the time of the original blocker):
`ISSUE117_IMPLEMENTATION_FREEZE_BLOCKED`.

Current state (additive record,
`evidence/v5-qualification-subject-recovery.json`):
`ISSUE117_IMPLEMENTATION_FREEZE_PENDING_RE_EVALUATION` — both blockers
below are resolved; the physical preflight and Arms A-E have NOT run.

## Finding

The retained V5 evidence records checkpoint SHA-256
`5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d`.
It does not retain a mechanical derivation from `/srv/models/gemma-r6` bytes
to that value.

The reviewed checkout has no `/srv/models/gemma-r6` directory. The retained
files contain no whole-repository digest rule and no frozen object manifest
that can reproduce the accepted value. They only repeat the accepted value.

## Effect

`checkpoint-authority.json` cannot establish the historical identity. A
newly written file can attest any observed object set to the accepted string.
That is circular evidence. Structural Gemma checks do not correct this
failure because foreign tensor bytes can have the same model identity,
revision, layer count, tied layout, and BF16 representation.

The retained V5 subject also does not retain a checkpoint representation
identity that is sufficient to reconstruct the current #117
`checkpoint-safetensors` subject without relying on current candidate code.

## Required retained input

Before Issue #117 can continue, retain one of these accepted artifacts with
an exact derivation rule:

- the checkpoint-wide byte digest algorithm and its accepted input set; or
- a frozen object manifest with object paths, byte lengths, SHA-256 values,
  and the algorithm that derives the checkpoint SHA-256 from that manifest.

The artifact must itself be authenticated as accepted historical evidence.
The physical preflight must recompute that rule from the actual repository.
Until then, it must fail closed. Physical preflight and Arms A-E remain
pending and were not executed.


## Resolution (2026-09-07): `V5_CHECKPOINT_AUTHORITY_PROVENANCE_RECOVERED`

A maintainer-commissioned forensic investigation recovered the original
derivation. It was never a whole-repository digest:

    checkpoint sha256 == sha256(model.safetensors bytes)

The value is exactly the Hugging Face LFS oid of `model.safetensors` at
revision `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`, independently
confirmed by:

1. the live HF hub tree API for the pinned revision (server-side
   content-addressed; `lfs.oid == 5a84cb31...ff18d`, size 23,919,549,408);
2. the retained HF cache on inferswarm01 (hash-named blob
   `blobs/5a84cb31...ff18d`, tree manifest, xet download log whose final
   reconstruction record covers exactly 23,919,549,408 bytes);
3. the first committed record of the value: FreeToken `a68ed8d`
   ("R6: freeze METHODOLOGY before canonical results",
   `docs/inferswarm_r6/METHODOLOGY.md`), written 2026-09-02 after the
   census `sha256sum` of the snapshot file;
4. fresh full-file hashes on inferswarm01/03/04 (2026-09-07): all three
   `/srv/models/gemma-r6/model.safetensors` copies derive exactly
   `5a84cb31...ff18d`; all supplemental files byte-identical.

The evidence package is retained at
`evidence/checkpoint-authority-provenance.json`; the deterministic
validator at `scripts/issue117_checkpoint_authority.py` recomputes the
rule from candidate bytes (fail-closed on any mutation, symlink,
size change, or self-attesting sidecar); negative tests at
`tests/test_issue117_checkpoint_authority.py` prove altered bytes cannot
inherit the authority; the physical preflight now consumes this
independent authority instead of failing closed.

Historical note preserved: the original blocker text above stands as the
accurate record of the pre-recovery state. No old evidence was rewritten.

## Resolution (2026-09-07, second gate): `V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED`

The remaining blocker — the absent independently reconstructed accepted V5
qualification subject — is resolved. The complete accepted
execution-equality subject was reconstructed purely from byte-pinned
accepted historical evidence by `scripts/issue117_accepted_subject.py`:

- model / revision / checkpoint authority / execution semantics:
  `docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json`
  (the #109 frozen physical subject, unchanged by #110);
- stage structure and per-stage GPU UUIDs/layer ranges:
  `docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json`
  (the #97 execution authority, carried unchanged into V5; corroborated by
  the calibration producer's frozen chain plan at FreeToken `7e5c852`);
- Compute Unit identities (node/index/product/compute capability) and the
  five-field backend/runtime stack:
  `docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json`,
  cross-checked field-by-field against
  `docs/qualification/gemma4-12b-it-v4-campaign-97/PREFLIGHT-APPLICABILITY.json`
  and the #110 TERMINAL-REPORT runtime identity line;
- representation (`checkpoint-safetensors`, the single-file safetensors
  checkpoint whose sha256 is the authority): the PR #119 recovery record;
- terminal adjudication identity: the pinned
  `b/holdout-adjudication.json` file's own SHA-256 (`f024f8b3...b7a70`,
  `V5_QUALIFICATION_PASS`).

The mechanically derived accepted subject digest is
`sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd`.
The retained provenance record is
`evidence/accepted-v5-qualification-subject.json`; the reconstruction is
independent of all current candidate machinery (enforced structurally and
by a mutation regression). Physical applicability now evaluates candidates
against this independently reconstructed subject through the ordinary
generic digest-equality gate. The physical preflight has still NOT run and
Arms A-E remain pending.

## PR #120 correction: historical/current-state hierarchy

The accepted #118 canonical summary
(`evidence/canonical-summary.json`) is historical terminal evidence for
the state that existed when PR #118 was accepted
(`ISSUE117_IMPLEMENTATION_FREEZE_BLOCKED`, authority and subject
provenance unavailable at that time). It is preserved byte-for-byte and
is never rewritten by later recovery work. The current state after both
recoveries lives only in the additive record
`evidence/v5-qualification-subject-recovery.json`:

- classification: `V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED`;
- accepted subject digest:
  `sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd`;
- checkpoint authority / qualification subject: `RECOVERED`;
- previous #118 disposition: `ISSUE117_IMPLEMENTATION_FREEZE_BLOCKED`
  (historical, preserved);
- current Issue #117 state:
  `ISSUE117_IMPLEMENTATION_FREEZE_PENDING_RE_EVALUATION`;
- `physical_preflight_executed == false`, `physical_arms_executed == false`.

The PR #120 correction also hardened the physical preflight: it now
mechanically requires the canonical V5-geometry candidate to
independently derive `QUALIFICATION_APPLICABLE` (reason
`MATCHED_ACCEPTED_QUALIFICATION_RECORD`, matched record exactly
`inferswarm.issue117.accepted-v5-qualification/1`) and verifies every
declared accepted-subject evidence pin — including the #110 terminal
report — before any of its data contributes to the reconstructed
subject. An honestly regenerated `QUALIFICATION_NOT_APPLICABLE` for the
V5 candidate fails the preflight.
