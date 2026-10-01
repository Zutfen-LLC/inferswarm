# METHODOLOGY AMENDMENT 003 — 2026-09-30 (PR #253 correction round 5)

Scope of authority: correction round ordered by the maintainer NO-GO review
of PR #253 at reviewed head `9a18d4a282830506b63cd71eb6a45ad6e6715a77`
(single BLOCKER finding). Additive only; the frozen METHODOLOGY.md,
AMENDMENT-001, and AMENDMENT-002 are unchanged.

## A5 — ordered staging-buffer state transition (supersedes the pairing
mechanics of AMENDMENT-002 §B, retaining its multiplicity/order/adjacency
laws and the ledger, enumeration, and no-unrelated-host-allocation laws)

Blocker: the round-4 implementation derived the expected current
staging-buffer size by SUMMING all prior staging allocations
(`_current_staging_host_total`). After more than one growth replacement
the prior staging allocations are already deallocated; the sum law
(1 MiB + 4 MiB = 5 MiB) rejects the authentic second-growth deallocation
of the CURRENT 4 MiB buffer and accepts a forged sum-of-history
deallocation.

Source-derived at pin `b29c606e`, `ggml_vk_ensure_sync_staging_buffer`
(:8601 device overload, :8611 ctx overload):

1. Growth condition (:8602): `sync_staging == nullptr ||
   sync_staging->size < size` — strict `<`; a repeated ensure at or below
   the active size emits NOTHING (no staging line, no deallocation, no
   allocation).
2. On growth the pin emits, in order: the exact STAGING_LINE (:8603/:8613)
   with the requested byte size; the destruction of the CURRENT buffer
   (:8604, `ggml_vk_destroy_buffer` :3848 — a host-typed deallocation of
   exactly the current buffer's size, and a null no-op when no buffer
   exists); then the new buffer's host-typed allocation (:8605, logged at
   :2757) of exactly the requested size under `format_size` (:2249)
   2-decimal rounding.

Retained-evidence law (replaces the cumulative-sum derivation; the A5
validator now models the buffer as an ordered state transition):

- initial active staging size = none;
- each exact STAGING_LINE opens exactly one pending transition;
- with no active buffer, the next memory event must be the paired +host
  allocation of the exact requested size (the pin's destroy is a null
  no-op);
- with an active buffer, the request must strictly exceed it: a staging
  line for a request at or below the active size is inauthentic (the pin
  emits nothing there), and the transition must be exactly one -host
  deallocation matching the CURRENT active size followed by the paired
  +host allocation of the requested size;
- after a successful pairing the active size becomes the new allocation's
  size;
- historical staging allocations are never summed and never again
  deallocatable: a deallocation of any historical/non-current size, a
  duplicate deallocation, a missing destroy on growth, a reordered
  transition, an unrelated host allocation, or an unclosed pending
  transition are all rejected;
- the independent arithmetic ledger law, the no-other-host-allocation
  law, the device-allocation requirement, the one-factor subject-family
  law, and the informational-line/near-miss laws of AMENDMENT-002 §B
  remain unchanged and independently enforced.

Round-4's authority-API correction (AMENDMENT-002 §A) and the A4
NON_TERMINAL_CAPABLE disposition (AMENDMENT-002 §C) are untouched. The
round-4 producer-authentication rider is accepted for this Phase-0 PR: a
separately reviewed producer and live per-unit custody mechanism must
exist before physical evidence is treated as authority; nothing in this
amendment grants physical-execution or producer authority.
