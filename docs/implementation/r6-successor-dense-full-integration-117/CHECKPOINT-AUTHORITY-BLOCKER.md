# Issue #117 checkpoint-authority blocker

Status: `ISSUE117_IMPLEMENTATION_FREEZE_BLOCKED`.

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
