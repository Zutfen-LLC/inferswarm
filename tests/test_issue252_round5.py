"""Round-5 RED/PIN regressions (review of head 9a18d4a).

[RED] tests fail at the reviewed head 9a18d4a and must pass at the round-5
corrected head; [PIN] tests pass at BOTH heads and freeze retained law.
Labels are part of the method names so the committed file records the
expected fail/pass split.

BLOCKER (single): _mechanism_a5 derived the expected current staging-buffer
size by SUMMING all prior staging allocations
(_current_staging_host_total). The pinned source (b29c606e,
ggml_vk_ensure_sync_staging_buffer :8601/:8611) models the staging buffer
as an ORDERED STATE TRANSITION: growth happens only when
`sync_staging == nullptr || sync_staging->size < size` (strict <, :8602);
on growth the CURRENT buffer is destroyed (:8604, one host-typed
deallocation of exactly the CURRENT size, none when no buffer exists) and
then the new buffer of exactly the requested size is allocated (:8605).
A repeated ensure that does NOT require growth emits NOTHING (no staging
line, no deallocation, no allocation). Historical allocations are never
summed; only the single live buffer matters.

Derived state law (encoded here):
- initial active staging size = none;
- STAGING(size) starts one pending transition;
- no active buffer  -> the next memory event is the paired +host alloc of
  the exact size (the pin's destroy is a null no-op);
- active buffer and size > active (growth) -> exactly one -host
  deallocation of the CURRENT active size, then the paired +host alloc of
  the requested size (format_size :2249 rounding law);
- size <= active -> the pin emits nothing: any retained STAGING line for
  it is inauthentic and rejected (no-op emission law);
- after pairing, active = the new allocation's size; historical sizes are
  never again deallocatable.
"""
from __future__ import annotations
import unittest

from tests.test_issue252_physical import FixtureMixin
from tests.test_issue252_round4 import build_log, write, A5_NS, MIB
import issue252_mechanism as M


def _growth_events(sizes):
    """Authentic ordered growth chain  sizes[0] -> sizes[1] -> ...

    STAGING(s0), +host s0, then for each larger s: STAGING(s),
    -host(current), +host s. The pin's ensure grows only on strict
    increase; each growth destroys exactly the CURRENT buffer (:8604).
    """
    events = [("staging", sizes[0]), ("alloc", "host", sizes[0])]
    current = sizes[0]
    for s in sizes[1:]:
        events.append(("staging", s))
        events.append(("dealloc", "host", current))
        events.append(("alloc", "host", s))
        current = s
    return events


class MultiGrowthTests(FixtureMixin, unittest.TestCase):
    """Round-5 blocker: ordered growth-replacement state machine."""

    def setUp(self):
        self.fixture()

    def status(self):
        # #258 (AMENDMENT-006): A5 is nonterminal (#257), so the retained
        # ordered staging custody law is exercised directly.
        return {"capable": True,
                "facts": M._mechanism_a5(self.evidence, A5_NS)}

    # --- authentic multi-growth positives (RED at 9a18d4a) ---------------

    def test_red_two_successive_growth_replacements_accepted(self):
        # 1 MiB -> 4 MiB -> 8 MiB: the reviewer's authentic sequence. At the
        # reviewed head the second growth compares the -4 MiB deallocation
        # against the SUM 1+4=5 MiB and rejects the authentic log.
        log = build_log(_growth_events([MIB, 4 * MIB, 8 * MIB])
                        + [("alloc", "device", 64 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        self.assertTrue(self.status()["capable"])

    def test_red_three_successive_growth_replacements_accepted(self):
        # 1 -> 2 -> 4 -> 8 MiB: every transition is a strict increase, so
        # the pinned source permits the whole chain.
        log = build_log(_growth_events([MIB, 2 * MIB, 4 * MIB, 8 * MIB])
                        + [("alloc", "device", 64 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        self.assertTrue(self.status()["capable"])

    # --- forged multi-growth negatives (RED at 9a18d4a) ------------------

    def test_red_cumulative_sum_dealloc_rejected(self):
        # 1 -> 4 -> 8 where the second growth deallocates the SUM of
        # historical buffers (5 MiB) instead of the current buffer (4 MiB).
        # The reviewed head derives exactly that 1+4=5 sum and ACCEPTS.
        events = _growth_events([MIB, 4 * MIB])
        events += [("staging", 8 * MIB), ("dealloc", "host", 5 * MIB),
                   ("alloc", "host", 8 * MIB), ("alloc", "device", 64 * MIB)]
        write(self.evidence, A5_NS, "u1", build_log(events))
        # At the corrected head the arithmetic ledger fires first (a
        # sum-of-history deallocation always exceeds the live host bytes,
        # underflowing the running total); the staging law rejects it
        # independently. Either vocabulary proves rejection.
        with self.assertRaisesRegex(M.MechanismInvalid, "staging|ledger"):
            self.status()

    def test_red_growth_without_required_dealloc_rejected(self):
        # Growth 1 -> 4 with NO deallocation of the current 1 MiB buffer:
        # the pin destroys the smaller buffer before allocating (:8604),
        # so the retained stream cannot be authentic. The reviewed head
        # accepts the direct pairing (no destroy consulted).
        log = build_log([("staging", MIB), ("alloc", "host", MIB),
                         ("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                         ("alloc", "device", 64 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    def test_red_shrink_staging_line_rejected(self):
        # STAGING(2 MiB) while the active buffer is 4 MiB: the pin's ensure
        # is a NO-OP there (size < active, :8602) and emits nothing — the
        # retained line cannot be authentic. The reviewed head pairs it
        # directly and accepts.
        log = build_log([("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                         ("staging", 2 * MIB), ("alloc", "host", 2 * MIB),
                         ("alloc", "device", 64 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    def test_red_equal_size_restaging_rejected(self):
        # STAGING(4 MiB) while the active buffer is already 4 MiB: no-op at
        # the pin (strict < growth condition), nothing emitted.
        log = build_log([("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                         ("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                         ("alloc", "device", 64 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    # --- negatives that already reject at 9a18d4a (PIN) ------------------

    def test_pin_historical_size_dealloc_rejected(self):
        # Second growth deallocates the ORIGINAL 1 MiB buffer instead of
        # the CURRENT 4 MiB buffer: rejected at both heads (old head via
        # the sum 1+4 != 1; corrected head via the CURRENT-size law).
        events = _growth_events([MIB, 4 * MIB])
        events += [("staging", 8 * MIB), ("dealloc", "host", MIB),
                   ("alloc", "host", 8 * MIB), ("alloc", "device", 64 * MIB)]
        write(self.evidence, A5_NS, "u1", build_log(events))
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    def test_pin_duplicate_current_buffer_dealloc_rejected(self):
        # A duplicated deallocation of the already-replaced 4 MiB buffer
        # AFTER its growth transition closed (host totals stay positive, so
        # the arithmetic ledger alone cannot catch it): only the staging
        # state machine can reject. Rejected at both heads.
        events = [("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                  ("staging", 8 * MIB), ("dealloc", "host", 4 * MIB),
                  ("alloc", "host", 8 * MIB),
                  ("dealloc", "host", 4 * MIB),
                  ("alloc", "device", 64 * MIB)]
        write(self.evidence, A5_NS, "u1", build_log(events))
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    def test_pin_reordered_dealloc_after_alloc_rejected(self):
        # The pin destroys BEFORE allocating; a -4 MiB deallocation placed
        # AFTER the +8 MiB allocation is a reordered transition.
        events = [("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                  ("staging", 8 * MIB), ("alloc", "host", 8 * MIB),
                  ("dealloc", "host", 4 * MIB),
                  ("alloc", "device", 64 * MIB)]
        write(self.evidence, A5_NS, "u1", build_log(events))
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    def test_pin_unclosed_pending_transition_rejected(self):
        # A trailing STAGING line with no paired allocation is an unclosed
        # pending transition (existing law, frozen).
        log = build_log([("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                         ("alloc", "device", 64 * MIB),
                         ("staging", 8 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid, "staging"):
            self.status()

    # --- pinned no-growth emission law ------------------------------------

    def test_pin_no_growth_ensure_emits_nothing_accepted(self):
        # A repeated ensure that does NOT require growth
        # (sync_staging->size >= size, :8602) emits NO staging line, NO
        # deallocation, and NO allocation: the authentic retained trace of
        # later same-size uploads is simply more device traffic with no
        # further staging lines. Encoded explicitly per the pinned source.
        log = build_log([("staging", 4 * MIB), ("alloc", "host", 4 * MIB),
                         ("alloc", "device", 64 * MIB),
                         ("alloc", "device", 32 * MIB),
                         ("dealloc", "device", 32 * MIB)])
        write(self.evidence, A5_NS, "u1", log)
        self.assertTrue(self.status()["capable"])


if __name__ == "__main__":
    unittest.main()
