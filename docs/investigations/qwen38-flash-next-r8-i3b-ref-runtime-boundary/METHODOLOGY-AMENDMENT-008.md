# METHODOLOGY AMENDMENT 008 — Issue #250 post-V0n Arm-A reachability

Dated: 2026-09-28; CORRECTION ROUND 2 documentation revision: 2026-09-29.
Repository-only additive methodology amendment on PR #251 (branch
`issue-250-r8i3b-ref-runtime-boundary`). Round 1 was maintained on top
of the reviewed head `aa059713d83204a4dd8be2ea903aa31bddfdf3b8` (single
commit `35f427b`; base `origin/main`
`bc71774dc68e7d7fddaf97bd794bbbc297e66ca5` unchanged). CORRECTION ROUND
2 — reviewed predecessor head
`35f427bcc13e2ee56a2f566848018b6e3a08016d` — is additive on top of it:
`6a4f395` (RED suite) → `50cc60d` (correction) → `0134f67`
(retention-audit record), followed by one documentation-only correction
commit; reviewed history is preserved with no rewrite, squash, amend,
rebase, or force-push. The CURRENT mechanism of this amendment is the
CORRECTION ROUND 2 mechanism at the end of this document; where an
earlier section retains superseded round-1 wording, it is explicitly
marked HISTORICAL / SUPERSEDED BY CORRECTION ROUND 2. The amendment
authorizes no dispatch, no model request, no physical execution, no
later arm, and no merge. Earlier methodology amendments remain
unchanged and preserved verbatim.

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
the historical law. HOW Arm A opens is decided by
`arm_a_reachability_source(...)` (CORRECTION ROUND 2): from the
rederived V0 STATE it returns either `historical-v0-amd-variable` (the
historical AMD_VARIABLE law opened Arm A; every other arm keeps the
historical ladder verbatim) or `arm-a-bridge` (the top-level V0 state
is an adjudicated maintainer stop — DISAGREEMENT_STOP /
CONCORDANCE_STOP / IDENTICAL_PAIR_NEEDS_THIRD — or the top-level V0
namespace is entirely absent, a bridge-only campaign root, AND
`validate_arm_a_bridge` authenticates). An INVALID V0 state
(absent/tampered/unreadable evidence, custody failure) can NEVER open
the bridge: it re-raises the historical refusal unchanged. Only the
bridge path is described in this section; the classification below is
HISTORICAL round-1 wording retained for audit history — SUPERSEDED BY
CORRECTION ROUND 2, which replaced the refusal-class trigger with the
exact rederived-state decision above.

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
   population the record names is ALSO re-authenticated from bytes.
   HISTORICAL round-1 wording — SUPERSEDED BY CORRECTION ROUND 2
   (the bespoke `_verify_arm_a_bridge_v0n_population` checker this
   subsection named is DELETED): authentication now runs the FROZEN
   `_v0n_retained_rows` verifier (backend/identity/residency/
   dispatch/argv/env/PID/generation custody) plus the frozen
   `reduce_v0n_screen` re-derivation of `CURRENT_NVIDIA_VARIABLE_STOP`
   with both rows novel, under the byte-exact reconstructed accepted
   dispatch authority, with the fresh-process PID-custody law
   enforced. Missing/drifted evidence rejects — a prose-only GitHub
   record with no retained evidence can never authorize anything.
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
* the future Arm-A producer authenticates BOTH predecessors from the
  read-only predecessor mounts inside its own campaign evidence root
  (`predecessor-v0/`, `predecessor-v0n/`; see "Read-only cross-host
  evidence path" under CORRECTION ROUND 2 below): the FROZEN
  `_v0_retained_rows`/`_v0n_retained_rows` verifiers and
  `reduce_v0_screen`/`reduce_v0n_screen` reducers run unmodified over
  the mounted bytes and must re-derive exactly the accepted states
  (`revalidating_arm_a_predecessors`). SUPERSEDED BY CORRECTION ROUND
  2: the round-1 wording ("re-authenticates the V0n half ... through
  the frozen validators ... row-digest seam (`_sha256_file`) is
  injectable for CPU-only regressions") described an earlier inline
  design that no longer exists — the `_sha256_file` seam has no
  remaining consumers, and CPU-only regression hosts instead patch the
  frozen bridge constants to the synthetic population's real digests
  (the established fixture precedent); production row digests are
  real file SHA-256 values;
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

HISTORICAL (round 1) — SUPERSEDED BY CORRECTION ROUND 2 in the naming
of the V0n mechanism and the test suite; kept for audit history. The
round-1 wording below names `_verify_arm_a_bridge_v0n_population` and
34 focused regressions, both of which CORRECTION ROUND 2 replaced (the
bespoke checker is deleted; the CURRENT suite is
`tests/test_issue250_amendment008_round2.py`, 50 tests):

* `scripts/issue250_diagnostic.py`: bridge constants (schema, record
  name, stale-dispatch set, accepted evidence digests, accepted V0
  executed head);
* `scripts/issue250_physical.py`: `validate_arm_a_bridge`,
  `_verify_arm_a_bridge_v0n_population` (round 1 only; DELETED in
  CORRECTION ROUND 2), the row-digest seam, and the amended Arm-A
  branch of `_require_sequential_reachability`
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

## CORRECTION ROUND 2 (reviewed head 35f427b, review of PR #251) — CURRENT

The reviewed implementation opened the bridge through a historical-gate
message-prefix exception and a bespoke V0n population checker. The
correction replaces both with exact authenticated predecessor
decisions. THIS SECTION IS THE CURRENT MECHANISM OF THIS AMENDMENT;
earlier sections that conflict with it are marked HISTORICAL /
SUPERSEDED BY CORRECTION ROUND 2. In one sentence: Arm A opens ONLY via
`arm_a_reachability_source` (exact rederived-V0-state decision), gated
by `validate_arm_a_bridge` over `revalidating_arm_a_predecessors`
(frozen `_v0_retained_rows + reduce_v0_screen` and frozen
`_v0n_retained_rows + reduce_v0n_screen` on the read-only
`predecessor-v0/` + `predecessor-v0n/` mounts), with the decision
persisted as `reachability_source` in every Arm-A unit receipt and a
completed bridge-path Arm-A population reduced to the terminal
rejection `ARM_A_STOPS_LADDER` on EVERY outcome.

* **Exact predecessor decision (D1).** `arm_a_reachability_source`
  decides HOW Arm A opens from the rederived V0 STATE (never a refusal
  message prefix): `historical-v0-amd-variable` when the frozen reducer
  derives the eligible variable state, or `arm-a-bridge` when the
  top-level V0 state is an adjudicated maintainer stop
  (DISAGREEMENT_STOP / CONCORDANCE_STOP / IDENTICAL_PAIR_NEEDS_THIRD)
  — or the top-level V0 namespace is entirely absent (a bridge-only
  campaign root) — AND `validate_arm_a_bridge` authenticates. An
  INVALID V0 state (absent/tampered/unreadable evidence, custody
  failure) can never open the bridge: it re-raises the historical
  refusal unchanged.
* **Retained-byte V0 revalidation (D2).** The bridge revalidates the
  accepted V0 result through the frozen `_v0_retained_rows` verifier
  and re-derives the decision through the frozen `reduce_v0_screen`:
  exactly three units, all equal to the accepted stable row
  (`ARM_A_BRIDGE_V0_STABLE_ROW_SHA256`), equal to NEITHER retained
  #248 NVIDIA row (accepted contrast law), under the byte-exact
  reconstructed accepted dispatch authority (`99cb573c…`).
* **Frozen retained-population V0n custody (D3).** The bespoke checker
  is deleted. The V0n half authenticates through the frozen
  `_v0n_retained_rows` verifier (backend/identity/residency/dispatch/
  argv/env/PID/generation custody) plus the frozen
  `reduce_v0n_screen` re-derivation of `CURRENT_NVIDIA_VARIABLE_STOP`
  with both rows NOVEL (differing from the AMD stable row and both
  retained #248 rows), under the byte-exact reconstructed accepted
  dispatch authority (`4aa0aa0b…`), with the fresh-process PID-custody
  law enforced.
* **Read-only cross-host evidence path.** The accepted roots
  (`inferswarm05:/home/hermes/is250-campaign/evidence-v0-c5cc132/`,
  `inferswarm01:/home/hermes/is250-campaign/
  evidence-v0n-nvidia-aa05971/`) are IMMUTABLE and never read by the
  future Arm-A producer. A bridge campaign mounts self-contained
  read-only copies under its own evidence root:
  `predecessor-v0/` and `predecessor-v0n/` (symlink mounts refused).
  The frozen verifiers then run unmodified over the mounted bytes;
  every bridge constant (stable row, V0n rows, freeze digest) is
  compared against the real content digests. CPU-only regression
  hosts patch the frozen constants to the synthetic population's real
  digests (the established fixture precedent) — the verifiers
  themselves never change.
* **Provenance + terminal stop (D4).** Every Arm-A unit receipt
  persists `reachability_source` (one of the two frozen vocabulary
  values; later-arm receipts carry none). The terminal reducer
  verifies per-unit provenance, rejects mixed/absent populations, and
  consumes a completed bridge-path Arm-A population to exactly the
  post-A review decision: `derive_terminal` returns
  `ARM_A_STOPS_LADDER` for a bridge-path Arm A on EVERY outcome
  (deterministic or variable) — no Vulkan root cause is inferred, no
  B/C/C1/C2/D authority is granted.
* **Preserved gates.** Fresh exact-head dispatch, clean-head, model,
  cost, fixture, and two-pass launch gates are untouched; the bridge
  grants eligibility only, never execution authority. A mutation
  matrix (record fields, mounts, symlinks, digests, PIDs, provenance
  mixing) covers every corrected boundary.
* **Tooling delta.** `scripts/issue250_physical.py`
  (`arm_a_reachability_source`, `revalidating_arm_a_predecessors`,
  frozen-authority reconstruction, corrected
  `_require_sequential_reachability`), `scripts/issue250_terminal.py`
  (provenance verification + unconditional bridge-path stop),
  `scripts/issue250_diagnostic.py` (retained dispatch-comment
  constants), and `tests/test_issue250_amendment008_round2.py`
  (24 [RED] + 11 [PIN] + 15 mutation regressions, registered in
  `r8i-qwen-qualification`).

No physical arm was dispatched or executed; accepted evidence is
untouched; the bridge grants no execution authority.
