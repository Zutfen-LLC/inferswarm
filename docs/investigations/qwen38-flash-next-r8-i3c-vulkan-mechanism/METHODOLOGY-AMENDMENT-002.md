# METHODOLOGY AMENDMENT 002 — 2026-09-30 (PR #253 correction round 4)

Scope of authority: correction round ordered by the maintainer NO-GO review
of PR #253 at reviewed head `6bc9251a87e8d6f3f0d8ba1ac51d926756dec0fd`
(three BLOCKER findings). Additive only; the frozen METHODOLOGY.md text and
AMENDMENT-001 are unchanged.

## A. Production authority API carries no fetcher or offline-mode flag

AMENDMENT-001 section A established retrieval-bound authority; round 3
enforced it with a runtime boolean (`_test_only`/`_test_only_fetch`) that
rejected caller-supplied fetchers unless explicitly overridden — leaving a
one-boolean bypass in the production-callable signature itself. Round 4
removes the seam entirely:

1. `derive_terminal(evidence_root, arms_result)` — the complete public
   signature. No `fetch` parameter, no keyword flag, no `**kwargs`.
2. `verify_capture(retained, *, repo_pr_number)` — the complete public
   signature. The re-fetch is issued internally through
   `issue252_physical.fetch_dispatch_comment` (canonical-repository HTTPS
   prefix, real transport) only.
3. Offline synthetic-fixture verification is a TEST-ONLY facility that
   patches the production fetch function object
   (`tests/test_issue252_physical.py::FixtureMixin.offline_authority_fetch`)
   — standard unittest `mock.patch`, owned by the test, unreachable through
   any shipped API. An attacker who controls reducer invocation has no
   argument to forge; production behavior is unverifiable from the
   signature, not merely discouraged by a runtime check.

## B. A5 — one-to-one ordered staging/allocation pairing (replaces the
set-membership law of AMENDMENT-001 §B bullet A5)

Source-derived at pin `b29c606e`: `ggml_vk_ensure_sync_staging_buffer`
(:8601 device overload, :8611 ctx overload) logs the exact staging line,
then (growth path only) destroys the current smaller buffer — at most ONE
host-typed deallocation of exactly the current staging size — then
allocates the new buffer, logged by `log_allocation` (:2757) as a host-typed
line of exactly the staging size under `format_size` (:2249) 2-decimal
rounding. The retained server log is parsed as an ordered event stream and
every exact `STAGING_LINE` must be paired one-to-one with its own
immediately-following host-typed `+` allocation of the exact size
(adjacent, or separated by exactly the one legal growth deallocation).
Multiplicity, ordering, position, and per-event size are all enforced;
aggregate set/multiset/total equality is not consulted. No other host-typed
allocation may exist in any retained unit; at least one device-typed
allocation must; the arithmetic running-total ledger law remains
independently enforced; the pin's informational memory-prefixed lines
(preallocate/host-malloc/free families, exact formats) are accepted as
authentic, and any near-miss memory-prefixed line fails closed.

## C. A4 — NON-TERMINAL-CAPABLE at this pin (supersedes the A4 contract of
AMENDMENT-001 §B)

Source audit conclusion: no sufficient retained observable exists at
b29c606e to bind an allocation to the `GGML_VK_PREFER_HOST_MEMORY`-gated
branch. The VK memory logger (:2746-2757) types each line only by
`eDeviceLocal` on the chosen memory type — no buffer identity, no call-site
provenance, no requested-flags record. Host-typed lines arise identically
from the sync-staging path (:8605/:8615) and pinned host allocations
(:8222), which never consult `prefer_host_memory`; on a discrete NVIDIA
subject the preference branch's fallback (`eDeviceLocal`, :3813) logs
identically to the unpreferred branch's reBAR choice (:3835). A same-site
host-vs-device differential would require a preference-off baseline
allocation ledger; the frozen accepted runs (#248/#250) predate
`GGML_VK_MEMORY_LOGGER` and retain no allocation lines. A4 therefore cannot
mechanically demonstrate the named causal intervention from retained bytes
and is marked NON_TERMINAL_CAPABLE prospectively, exactly as A1: it remains
executable as a control, deterministic A4 repeats alone can never reach
LOCALIZED or FIX_VALIDATED, and a complete retained arm set with no capable
arm localizing resolves UNRESOLVED. The mechanism claim is not broadened;
no alternative causal claim is fabricated.

## D. Enumeration-line multiplicity and one-factor subject capability

Each retained unit must carry exactly ONE device enumeration line (the
frozen one-device launch emits one; duplicates are doctored or
unrelated-context copies) — enforced both in the mechanism contracts and in
the reducer's Vulkan-participation check for corrected (fixed) runs. For
arms whose control cannot change cooperative-matrix detection (A3, A5), the
retained family must equal the frozen subject capability
(`NV_coopmat2`, HOST_FACTS / accepted #248/#250 preflight): any other
family proves a second factor moved and the run was not one-factor on the
frozen subject.
