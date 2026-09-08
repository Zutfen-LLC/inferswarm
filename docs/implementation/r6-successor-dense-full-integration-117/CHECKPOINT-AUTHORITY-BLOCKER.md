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
