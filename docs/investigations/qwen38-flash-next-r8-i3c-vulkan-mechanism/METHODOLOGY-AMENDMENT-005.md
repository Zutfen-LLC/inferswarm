# METHODOLOGY-AMENDMENT-005 — A3 Vulkan placement/mechanism law correction + failure quarantine (#254 round 5)

Additive to the frozen #252 METHODOLOGY (merged PR #253) and
METHODOLOGY-AMENDMENT-001..004. Nothing in this amendment edits frozen
#252/#253 text, arms, geometry, or the comparator/2 methodology. It records
the round-5 correction proven by the second physical A3 attempt at
dispatched head `a090c41`, and freezes the corrected law implemented on
this branch.

## A. The exact enum-law physical mismatch (the falsifying observation)

At dispatched head `a090c41`, real A3 unit 001: the pinned comparator
launched successfully, inference completed, the corrected observer-prefix
collector (AMENDMENT-004 / commit a090c41) exercised successfully — and
placement derivation then failed with

    server log does not carry exactly one Vulkan device enumeration line

because the retained `server.log` contained ZERO lines matching
`issue252_mechanism.ENUM_LINE`. The failed scratch directory was
subsequently deleted by the producer's scratch cleanup, destroying that
unit's only server.log. Historical retained #248 logs from the same frozen
host/runtime family likewise contain no `ggml_vulkan` enumeration banner
in the retained server-log stream.

Conclusion (prospective law / physical-instrument mismatch): the
source-first #252 assumption that the pin's device-enumeration banner
(:7695) is physically retained by this instrument is FALSE on the retained
stream. The exact enum-line requirement is not physically satisfiable
here and must no longer be required for A3. No replacement observable is
invented preemptively: A3's intended retained mechanism observable — the
exact stderr line

    ggml_vulkan: WARNING: Async execution disabled on certain Intel devices.

(:6727, full-line equality) — is kept as the law; if a later real A3 run
proves that line is also absent from the retained stream, the campaign
STOPS with that concrete result.

## B. Corrected A3 physical Vulkan placement identity (producer)

`_placement_from_log` no longer requires an enum line. Placement is
derived mechanically from retained facts already captured for every unit:

- frozen launch geometry carries `-ngl 1` (argv checked);
- `CUDA_VISIBLE_DEVICES=-1` (no CUDA participation);
- `VK_ICD_FILENAMES` equals the frozen NVIDIA Vulkan ICD;
- `GGML_VK_VISIBLE_DEVICES=0`;
- `gpu_uuid` is the frozen subject GPU UUID (HOST_FACTS identity
  authority);
- `vulkan_family` is populated from the frozen HOST_FACTS capability
  (`SUBJECT_ENUM_FAMILY`) and marked `vulkan_family_authority:
  "frozen-host-facts"` — an identity-authority value, never a per-unit
  log observation;
- the process argv/env is read back from `/proc` and bound into the
  producer attestation (`_check_process_attribution`, unchanged);
- pre/post #248 identity observation must match the frozen subject
  (unchanged law).

Resulting placement structure: `output_projection = Vulkan`,
`embedding = CPU`, `ngl = 1`, frozen GPU UUID,
`cuda_participation = false`. No enumeration line is fabricated; a
retained banner, when present, is still validated (family must equal the
frozen capability) and more than one banner still blocks (second
participating device).

## C. Corrected A3 mechanism validation (reducer)

`issue252_mechanism._mechanism_a3` no longer calls
`_require_subject_family` (the unavailable enum banner). For A3 only,
mechanism validation requires:

1. every retained A3 unit's server.log contains the exact async-disabled
   line, full-line equality (:6727);
2. every unit carries a valid producer-attested Vulkan placement under
   the corrected Part-B law (retained `placement.json`: Vulkan/CPU/ngl=1/
   no-CUDA/frozen UUID; optional `vulkan_family` equals the frozen
   capability);
3. frozen subject identity remains identical across units (retained
   `identity-pre.json` / `identity-post.json` equal the frozen
   HOST_FACTS).

A2 and A5 mechanism laws are UNCHANGED: their claims genuinely depend on
enum/memory observables (A2: exact enumeration line reporting family
`none`; A5: ordered staging/memory-ledger events plus the enum line) and
remain separately scoped. `_require_subject_family` stays in force for
A5; `_mechanism_a2` is untouched.

## D. Pre-publication failure quarantine (fail-closed custody)

The producer must never destroy the only diagnostic server log when a
real unit fails after launch but before atomic publication. On `run_unit`
failure after scratch creation, the scratch artifacts are preserved under
a clearly non-reducer namespace:

    <evidence-root>/producer-failure-quarantine/<namespace>/
        <scratch-name>-<UTC-stamp>/
            server.log, obs.meta.json, obs.row*.f32 (when present),
            any raw response bytes available, failure-status.json

Properties:

- the quarantine directory is never named as (and never becomes) a
  planned retained unit; no `unit.json` / `producer-attestation.json` is
  ever written into it — quarantined artifacts are diagnostic only and
  are never promoted to producer-attested physical evidence;
- the reducer continues to refuse it: `derive_terminal`'s
  unplanned-namespace check treats any directory outside the frozen arm
  namespaces as a BLOCKED condition, and no mechanism/`_arm_units` path
  reads it;
- a scratch that never reached `execute_unit` (no artifacts at all) is
  still removed by the ordinary cleanup — nothing was destroyed;
- continuation stays fail-closed: the retained
  `producer-status-<namespace>.json` record makes `next_legal_unit`
  refuse further execution on the SAME evidence root; a continuation
  requires an explicitly fresh evidence root.

## E. Ancestry

Implemented additively on PR #256 (branch `issue-254-r8i3c-producer`)
atop reviewed head `a090c417f5f206341a280a66d88f1a510defb40f`, which
remains an ancestor of the corrected head. Frozen #252/#253/#248 accepted
evidence bytes are unchanged by this amendment.
