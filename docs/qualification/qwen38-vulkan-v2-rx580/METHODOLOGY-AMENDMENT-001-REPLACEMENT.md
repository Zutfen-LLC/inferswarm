# METHODOLOGY AMENDMENT 001 — Replacement-card subject re-freeze (generation 2)

Date: 2026-09-24
Authority: maintainer remediation directive on PR #242 (2026-09-24),
following the accepted historical terminal
`R8I3_RX580_INFRASTRUCTURE_BLOCKED` for the generation-1 physical
candidate. This amendment does not edit the frozen 2026-09-23
methodology text; it supersedes the frozen SUBJECT of that methodology
prospectively, exactly as the directive requires.

## Original frozen subject (verbatim, METHODOLOGY.md §2, 2026-09-23)

> - Arm C (candidate): AMD Radeon RX 580 Series (RADV POLARIS10),
>   Ellesmere `[1002:67df]` rev e7 @ `0000:02:00.0` (radeon ICD, RADV
>   Mesa 25.0.7-2+deb13u1, apiVersion 1.4.305, amdgpu kernel driver,
>   8192 MiB VRAM census), same selectors.

> the candidate is additionally bound by subsystem `1da2:e353` and exact
> negotiated/max link identity x8/x16 @ 8.0 GT/s max capability

## What falsified the frozen subject

The generation-1 physical card failed fatally under the dispatched
campaign (case-1024 / arm C / ngl=8: uncorrectable PCIe AER, surprise
link down, failed retrain — platform-fault bytes retained in
`historical/campaign-v2-dispatch-b6148de/platform-fault/`), and
reproduced the identical fatal fault after cold reboot under the
accepted canonical no-hook binary at the same geometry
(`historical/oldcard-canonical-fault-repro-2026-09-24/`), excluding
comparator/2 instrumentation as the cause. The card is failed hardware.

The operator physically replaced the card in the same candidate slot.
The replacement completed the exact formerly-fatal leg cleanly
(`historical/replacement-crash-leg-diagnostic-2026-09-24/` — remediation
evidence only, not qualification).

## The exact amendment

Subject generation 2. The frozen candidate constant
`link_width` changes from `x8` to `x16` — and NOTHING else — because the
fresh retained read-only census of 2026-09-24
(`evidence/replacement-census-2026-09-24/raw/`, maintainer-authorized,
no GPU compute / model reads / dispatch machinery) mechanically proves
the replacement negotiates x16 (`sys_02:00.0_current_link_width` = 16,
`max_link_width` = 16, `max_link_speed` = 8.0 GT/s).

Every other frozen identity field was re-verified from the same fresh
bytes and is byte-identical to generation 1: vendor `1002`, device
`67df`, subsystem `1da2:e353`, revision `e7`, BDF
`00000000:02:00.0` (16-char domain-prefixed form), amdgpu kernel
driver, radeon ICD, RADV POLARIS10 deviceName
`AMD Radeon RX 580 Series (RADV POLARIS10)`, deviceUUID
`00000000-0200-0000-0000-000000000000`, apiVersion `1.4.305`, driverInfo
`Mesa 25.0.7-2+deb13u1`, VRAM 8192 MiB. These equalities are
COINCIDENTAL: the physical card was replaced, and no software-visible
field is claimed to individuate Polaris boards. The replacement is
recorded as a distinct physical subject via `SUBJECT_GENERATION = 2`
regardless of field equality.

## Why this is a subject re-freeze, not threshold tuning

The wire budget, comparator/2 semantics, placement policy, statistical
methodology, fixture ladder, model bytes, runtime pins, holdout bytes,
and every no-predictive/no-decrypt boundary are UNCHANGED. The single
changed constant is the negotiated link width of the physical subject —
hardware identity, proven from fresh retained observation bytes, exactly
the class of correction the directive authorizes. No acceptance-bearing
output exists at the new subject; nothing observed on the generation-1
card satisfies any generation-2 gate.

## Ancestry and implementation

- Historical campaign: dispatch comment 5806929798 at head
  `b6148de7897de49e961ceca2f3cc0ee2f59dc4b2` (terminal
  `R8I3_RX580_INFRASTRUCTURE_BLOCKED`), plus the canonical-binary fault
  reproduction and the replacement diagnostic — all retained immutably
  under `historical/`.
- This amendment froze in the subject-re-freeze commit on PR #242
  (constants + phase-0 provenance enforcement + negative controls),
  BEFORE any generation-2 physical execution. All dispatch comments
  predating this re-freeze head are stale by construction.
- Mechanical enforcement: `issue241_constants.
  derive_candidate_identity_from_census` /
  `verify_replacement_freeze_provenance` (Phase-0 audited);
  `census.identity_problems` rejects the generation-1 x8 observation
  (negatively controlled: `test_old_generation_x8_subject_rejected`,
  `test_historical_generation1_census_cannot_validate`).
- Negative controls added per the directive: the old x8 subject cannot
  satisfy the replacement predicate; the retained generation-1 census
  cannot validate; the replacement diagnostic carries no dispatch
  authority or campaign schema and cannot satisfy any acceptance gate.
