# METHODOLOGY AMENDMENT 008 — Issue #250 post-V0n Arm-A reachability

Dated: 2026-09-28. Repository-only additive methodology amendment on
PR #251 (branch `issue-250-r8i3b-ref-runtime-boundary`), maintained on
top of the reviewed head `aa059713d83204a4dd8be2ea903aa31bddfdf3b8`
(single commit over the reviewed head; base `origin/main`
`bc71774dc68e7d7fddaf97bd794bbbc297e66ca5` unchanged). It authorizes no
dispatch, no model request, no physical execution, no later arm, and no
merge. Earlier methodology amendments remain unchanged and preserved
verbatim.

## The accepted evidence combination (consumed, never altered)

Both predecessor results are ACCEPTED PHYSICAL AUTHORITY. This
amendment changes NO state, NO digest, NO `terminal`/`a_eligible`
field, and NO historical result:

1. **V0 AMD screen** (dispatch comment `5868617068`, executed head
   `c5cc132762c51a3352014f36553eff6d0d26b112`, evidence root
   `/home/hermes/is250-campaign/evidence-v0-c5cc132/` on
   `inferswarm05`): three repeat-stable byte-identical fresh-process
   AMD/RADV rows, decision-0 SHA-256
   `2187ab8f444e726b9a34d9874499603446a23efdd7943e8330286e223938fb41`
   (993280 bytes each), all differing from BOTH retained #248 NVIDIA
   Vulkan `ngl=1` rows — state
   `CROSS_VENDOR_DISAGREEMENT_STOP_BLOCKED`, `a_eligible=False`,
   `maintainer_stop=True`. The dispatch authority digest of that
   completed comment is
   `99cb573c473d677ffa76adbc8486f494f10a51091e0257e33c84f2eadd2da2fa`.
   The historical evidence remains immutable.
2. **V0n NVIDIA current-window screen** (fresh dispatch comment
   `5880409202`, authority digest
   `4aa0aa0b216105d0c611652b100d53f4a5aed46be8f4013a6c15d1acd43dd776`,
   executed exactly at head `aa059713d83204a4dd8be2ea903aa31bddfdf3b8`,
   evidence root
   `/home/hermes/is250-campaign/evidence-v0n-nvidia-aa05971/` on
   `inferswarm01`, freeze digest
   `3fe9e74dece02e4e892daec2f6510df6a670905d6ee5a83fea61bc1f2a7e9207`):
   exactly two valid fresh-process units, first pair mismatched
   (`6c295c671a794ebd2d6b5d644900fd87eb3430c69226954db0870146822aae53`
   and
   `3d6b599d15004d7ad0b4402784b64eec369434724c9dc13e16f23531de975d6b`),
   third repeat forbidden and not executed, both rows novel relative to
   the stable AMD row and both retained #248 rows — state
   `CURRENT_NVIDIA_VARIABLE_STOP`, `valid=true`, `maintainer_stop=true`,
   `terminal=None`, `a_eligible=False`. Result record: PR #251 comment
   `5881249538`; Issue #250 record: comment `5881256387`. All 2-then-
   conditional-third laws and all identity/residency custody laws
   remain exactly as frozen by AMENDMENT-007.

## The reachability gap (defect this amendment corrects)

The historical Arm-A launch gate
(`_require_v0_fallback` in `scripts/issue250_physical.py`) opens the
CPU-only discriminator ONLY from V0 state
`AMD_VARIABLE_A_ELIGIBLE_DISPATCH_REQUIRED` (`a_eligible=True`). The
accepted V0 result is the stable cross-vendor disagreement stop
(`a_eligible=False`), so the historical gate can never open Arm A
again; V0n correctly carries `a_eligible=False` and cannot and must not
silently bypass that gate. Under the maintainer-accepted sequence —

* repeat-stable AMD Vulkan disagreement (V0), AND
* same-subject/current-window NVIDIA Vulkan fresh-process variability
  (V0n),

— there was NO mechanically defined explicit path to the
already-frozen CPU Arm-A discriminator. That is the defect. It is NOT
corrected by changing either historical result.

## The accepted interpretation (maintainer adjudication)

* The AMD V0 screen produced a repeat-stable Vulkan row.
* That stable AMD row disagreed with both retained #248 NVIDIA rows.
* A current-window rerun of the exact accepted #248 NVIDIA Arm-B
  physical subject then varied immediately across two fresh processes.
* Both current NVIDIA rows were novel relative to the AMD stable row
  and both retained #248 rows.
* Therefore V0/V0n did NOT establish a stable cross-vendor value and
  did NOT identify a vendor as numerically authoritative.
* It DID establish that fresh-process variability remains present on
  the accepted NVIDIA Vulkan path under the tightly frozen current
  subject/runtime contract while the bounded AMD Vulkan screen was
  repeat-stable.
* The next already-predeclared discriminator is therefore **Arm A**:
  remove Vulkan model-layer participation while preserving the
  accepted case-3072 model/prompt/request semantics.

The Arm-A question remains strictly:

> Is nonzero Vulkan model-layer participation necessary for the
> accepted fresh-process first-row nondeterminism?

Interpretation remains:

* CPU-only variable ⇒ Vulkan participation is NOT necessary; STOP for
  maintainer review before any B execution.
* CPU-only deterministic under the predeclared five-repeat law while
  the accepted/current NVIDIA Vulkan path is variable ⇒ localize a
  necessary boundary between zero and nonzero Vulkan participation;
  STOP for maintainer review.
* Vulkan itself is NOT called the root cause absent a smaller
  demonstrated mechanism.

This amendment does NOT change comparator acceptance methodology in
any way.

## The post-V0n Arm-A reachability law (fail-closed)

A single mechanical predicate,
`validate_arm_a_bridge(evidence_root, expected_head)` in
`scripts/issue250_physical.py`, gates Arm A beside (never instead of)
the historical law. `_require_sequential_reachability` now runs the
historical `_require_v0_fallback` gate verbatim FIRST for Arm A; only
on its exact refusal class ("V0 precedes CPU fallback") may the
bridge open the condition. Any other historical refusal (invalid
custody, third-required, missing evidence, …) still blocks. Every
later arm (B/C/C1/C2/D) keeps the historical law unchanged.

The bridge record
(`arm-a-reachability-bridge.json` at
`docs/investigations/qwen38-flash-next-r8-i3b-ref-runtime-boundary/`,
schema `inferswarm.issue250.arm-a-bridge/1`, canonical digest
`2c8ea9f40809ac6c79267333bb1678442c1a7ee3e9b7188429d001a9db0e754f`)
establishes ALL of the following from retained/authenticated evidence
rather than caller assertions:

A. **Accepted AMD V0 predecessor** — the record binds the completed V0
   dispatch authority digest
   (`99cb573c…2da2fa`, mechanically reconstructible from the retained
   dispatch comment `5868617068` via the frozen
   `authority_digest` law over `comment_id`/`issue_url`/
   `author_association`/`created_at`/`head_sha`/`namespace`/`body`),
   the executed head `c5cc132…`, state
   `CROSS_VENDOR_DISAGREEMENT_STOP_BLOCKED`, three units, and the
   stable row `2187ab8f…`. A wrong V0 dispatch digest, wrong state, or
   altered stable row rejects.
B. **Accepted current NVIDIA V0n predecessor** — the record binds the
   V0n authority digest `4aa0aa0b…`, state exactly
   `CURRENT_NVIDIA_VARIABLE_STOP`, the authenticated freeze
   `3fe9e74d…`, exactly two units with the two novel rows, `terminal`
   `null`, `a_eligible=false`, mismatched first pair. The retained V0n
   population the record names is ALSO re-authenticated from bytes:
   `_verify_arm_a_bridge_v0n_population` requires exactly the two
   retained V0n units, the authenticated freeze
   (`_read_v0n_screen_freeze` at the accepted evidence head), one
   shared freeze digest + subject identity, per-row digest equality
   with the record, receipt↔row digest binding, and a genuinely
   mismatched first pair. Missing/drifted evidence rejects — a
   prose-only GitHub record with no retained evidence can never
   authorize anything.
C. **Maintainer-reviewed transition** — `maintainer_adjudicated=true`
   and `eligible_arms == ["A-vulkan-necessity"]` exactly. Eligibility
   is NOT execution authority.
D. **Execution still requires** its own namespace `d250-arm-a`, arm
   `A-vulkan-necessity` (the historical `NAMESPACE_ARM_BINDING` pair,
   unchanged), a NEW dispatch comment at the exact NEW PR head after
   this amendment, a clean head, the normal model/cost/fixture/binary
   authorities, and the normal live two-pass dispatch checks — all
   still enforced by `run_diagnostic_unit` for every Arm-A unit. No
   stale V0, V0n, historical Arm-A, AMD, or prior-pass dispatch may
   authorize Arm A; the completed AMD dispatch comment `5868617068`
   is additionally pinned as bridge-stale
   (`ARM_A_BRIDGE_STALE_DISPATCH_COMMENT_IDS`).

## Cross-root / cross-host predecessor authentication

The accepted physical evidence spans distinct append-only roots on two
hosts (AMD V0 on `inferswarm05`, V0n on `inferswarm01`; historical
#248 bytes on `inferswarm01`). The minimum defensible mechanism —
reusing the repository's established digest-reconstruction precedent
(AMENDMENT-006 quotes dispatch authority digests the same way) — is:

* the **authoritative physical bytes remain** on their original
  append-only roots; nothing is rewritten, copied as replacement
  authority, or re-hashed en masse (no 72.5 GiB model rehashing; model
  authority is the accepted #241 member digests consumed by the
  existing attestation machinery);
* the bridge record binds each predecessor by the digests its own
  frozen tooling produces — dispatch authority digests (reconstructible
  byte-exact from the retained GitHub comment bytes through
  `issue250_diagnostic.authority_digest`, regression-proven against
  the accepted V0n value `4aa0aa0b…` and derivable for the accepted V0
  value `99cb573c…`), the V0n screen-freeze canonical digest, and the
  full-row SHA-256 constants;
* the record itself is committed, digest-sealed
  (`canonical_digest_sha256` over all other fields), and fails closed
  on ANY single-field mutation even with the digest recomputed,
  because every binding field is independently compared to a frozen
  module constant;
* the future Arm-A producer re-authenticates the V0n half from the
  retained evidence tree it actually reads (freeze + receipts + rows
  through the frozen validators); where a CPU-only host cannot hold
  the 993280-byte physical rows, the row-digest seam
  (`_sha256_file`) is injectable for CPU-only regressions, and
  production always resolves to the real file SHA-256 — content-keyed
  translation means a mutated row still rejects;
* no inference is performed by any of this: the bridge is read-only
  evidence authentication.

## Arm-A plan remains frozen

No redesign: exact accepted case-3072 workload, exact accepted model
bytes, exact prompt bytes/token IDs, exact request semantics, CPU-only
(`-dev none`, the proven pinned-build control; zero GPU-offloaded model
layers), fresh process per unit, full decision-0 row (no winner-only
comparison), run-until-first-mismatch stop, deterministic claim only at
FIVE valid identical repeats (`DETERM_MIN_REPEATS`), minimum three
repeats never establishing the terminal by itself, no favorable-repeat
selection, no extension after mismatch. The corrected per-condition
timeout/cost authority (`scripts/issue250_timeout.py`, condition
`arm-a-cpu-only`, disposition `authorized_by_pass6_dispatch`) is
retained unchanged.

## No B–D auto-progression

Arm A is the only newly reachable physical discriminator. After a
future Arm-A result the ladder STOPS: `derive_terminal` refuses B with
the frozen reason `ARM_A_STOPS_LADDER` whenever the Arm-A population
was produced under the bridge path
(`reachability_source == "arm-a-bridge"`), and no existing tooling
permits or dispatches B after an Arm-A variable result without a new
maintainer decision. B/C/C1/C2/D redesign nothing.

## Stale / historical Arm-A execution

The historical failed Arm-A v1 attempt stays failed evidence only: it
lives under the retired generation `gen-1-v1-timeout-defect`
(read-only, refused as a write target, never a reduction input), its
timeout failure remains non-numerical evidence, it does not count as a
successful Arm-A repeat, and it cannot authorize the new campaign. Any
old Arm-A dispatch is stale after the new repository head and fails
exact-head validation; the future Arm-A execution uses a fresh
evidence generation/root per the accepted Issue #250 conventions.

## Tooling (additive only)

* `scripts/issue250_diagnostic.py`: bridge constants (schema, record
  name, stale-dispatch set, accepted evidence digests, accepted V0
  executed head);
* `scripts/issue250_physical.py`: `validate_arm_a_bridge`,
  `_verify_arm_a_bridge_v0n_population`, the row-digest seam, and the
  amended Arm-A branch of `_require_sequential_reachability`
  (historical gate first, bridge second, fail-closed);
* `scripts/issue250_terminal.py`: `ARM_A_STOPS_LADDER` + the
  blocked-reason surfacing in `derive_terminal` (never granting);
* `docs/investigations/…/arm-a-reachability-bridge.json`: the
  canonical digest-sealed record;
* `tests/test_issue250_amendment008.py`: 34 focused regressions
  (registered in `r8i-qwen-qualification`).

This amendment creates no model load, no inference request, and no
physical execution of any kind. Arm A has NOT run. No vendor
correctness or root-cause claim is authorized. Accepted #241/#248
terminal claims are untouched.
