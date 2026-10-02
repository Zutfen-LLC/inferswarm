"""Issue #258 RED suite — the old complete-arm-set theorem is invalid.

[RED n] tests FAIL at the reviewed PR #256 head 2dce4e1a and MUST PASS at
the #258 corrected head; [PIN] tests pass at BOTH heads and freeze law.
Labels are part of the method names so the committed file records the
expected fail/pass split (round-5 house style).

The seven RED directions (one per mandated old-reducer defect):

1. A3 variable + A5 variable, with A1/A2/A4 incapable: the old reducer
   refuses the mixed 5-namespace tree ("mixed arms require independently
   retained authorities" applies against the COMPLETE named set) and
   refuses the partial A3+A5 tree; it never reaches the honest UNRESOLVED.
2. A non-terminal arm omitted: the old reducer blocks solely because a
   non-terminal arm did not run.
3. Dead A2 omitted: the old reducer blocks despite A2 being unable to
   alter the frozen subject's selected mechanism.
4. A5 variable retained but nonterminal: the old reducer depends on A5 as
   terminal-capable (its five-deterministic-rows path would even emit
   LOCALIZED_FIX_NOT_VALIDATED through A5).
5. A3 variable with no remaining terminal-capable discriminator: the new
   theorem's correct terminal is UNRESOLVED, not BLOCKED and not
   NON_LOCALIZED.
6. Future instrumentation-required arm absent: fail closed to UNRESOLVED,
   never pretend non-localization.
7. A physically executed nonterminal arm (A5, with evidence) must not gain
   terminal authority merely because it has evidence.
"""
from __future__ import annotations
import copy
import unittest
from unittest import mock

from tests.test_issue252_physical import (FixtureMixin, git, sha, A, C, D,
                                          CAP, P)
import issue252_terminal as T
import issue252_mechanism as M

NL = chr(10)
ENUM_BASE = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | uma: 0 | fp16: 1"
             " | bf16: 0 | fp4: 0 | warp size: 32 | shared memory: 49152"
             " | int dot: 1 | matrix cores: ")
MEM = "ggml_vulkan memory: NVIDIA GeForce RTX 3060: "
ASYNC_OFF = ("ggml_vulkan: WARNING: Async execution disabled on certain Intel devices."
             + NL)


def _fmt(b):
    if b >= 1024 ** 2: return f"{b / 1024 ** 2:.2f} MiB"
    if b >= 1024: return f"{b / 1024:.2f} KiB"
    return f"{b} B"


def _mklog(family, events):
    lines = [ENUM_BASE + family]
    td = th = 0
    for kind, size in events:
        if kind == "staging":
            lines.append("ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer(" + str(size) + ")")
            kind = "host"
        else:
            size = int(size)
        if kind == "device":
            td += size
        else:
            th += size
        lines.append(MEM + "+" + _fmt(size) + " " + kind + " at 0x"
                     + format(len(lines), "x") + ". Total device: " + _fmt(td)
                     + ", total host: " + _fmt(th))
    return NL.join(lines) + NL


MIB = 1024 ** 2
# A3 mechanism law: exact async-disabled line + (when present) subject enum.
LOG_A3 = ASYNC_OFF + _mklog("NV_coopmat2", [("device", 4 * MIB)])
# A2 custody-admissible stream shape (family "none" is the only retained
# state proving the gate live AND effective; on the frozen subject this is
# unreachable — that is exactly the dead-control fact).
LOG_A2 = _mklog("none", [("device", 4 * MIB)])
# A5 #257-classified observationally-capable log (control live, staging
# authentic, but nonterminal: no unique discriminator at this pin).
LOG_A5 = _mklog("NV_coopmat2", [("staging", 4 * MIB), ("device", 8 * MIB)])
ARM_LOGS = {"A1": LOG_A3, "A2": LOG_A2, "A3": LOG_A3, "A4": LOG_A3,
            "A5": LOG_A5}


class TheoremArmSetTests(FixtureMixin, unittest.TestCase):
    def setUp(self):
        self.fixture()
        self.arm = "A3"
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A3")})

    def verdict(self, arm=None):
        arm = arm or self.arm
        with self.offline_authority_fetch(arm):
            return T.derive_terminal(self.evidence, {})

    def _retain_variable(self, arm, log):
        self.retain(arm, 1, server_log=log)
        self.retain(arm, 2, bytes([1]) * D.ROW_BYTES, server_log=log)

    def _retain_deterministic(self, arm, log, n=5):
        for i in range(1, n + 1):
            self.retain(arm, i, server_log=log)

    def _arm_authority(self, arm):
        self.write_json(self.evidence / f"authority-{arm}.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority(arm)})

    # ---- RED 1: accepted A3/A5 physical shape ---------------------------

    def test_red1_accepted_a3_a5_variable_state_is_unresolved(self):
        # The EXACT accepted physical state: A3 variable (round-7),
        # A5 variable (round-1), A1/A2/A4 incapable and unexecuted.
        # Old reducer: BLOCKED (mixed/partial set refused); correct:
        # UNRESOLVED — no terminal-capable discriminator remains.
        self._retain_variable("A3", LOG_A3)
        self._arm_authority("A5")
        self._retain_variable("A5", LOG_A5)
        self.assertEqual(self.verdict(), C.UNRESOLVED_TERMINAL)

    def test_pin1_full_five_variable_state_unresolved_under_both_laws(self):
        # [PIN] All five namespaces variable with per-arm authorities: the OLD
        # law returned UNRESOLVED here only through the complete-named-set
        # condition; the NEW law returns UNRESOLVED because coverage is
        # provably incomplete at this pin. The corrected reducer must not
        # depend on the named-set equality for this result.
        for arm in A.ARMS:
            self._arm_authority(arm)
            self._retain_variable(arm, ARM_LOGS[arm])
        self.assertEqual(self.verdict(), C.UNRESOLVED_TERMINAL)

    # ---- RED 2/3: incapable arms not required ---------------------------

    def test_red2_a3_variable_alone_is_unresolved_without_a1(self):
        # Old reducer: BLOCKED ("non-localization needs complete frozen arm
        # set"). New theorem: A3 is the required arm set; its accepted
        # variable result + provably incomplete coverage => UNRESOLVED.
        self._retain_variable("A3", LOG_A3)
        self.assertEqual(self.verdict(), C.UNRESOLVED_TERMINAL)

    def test_red3_dead_a2_not_required_for_terminal(self):
        # Same shape with the dead control explicitly absent: the terminal
        # derivation must never consult A2 execution for closure.
        self._retain_variable("A3", LOG_A3)
        self.assertFalse((self.evidence / A.ARMS["A2"]["namespace"]).exists())
        self.assertEqual(self.verdict(), C.UNRESOLVED_TERMINAL)

    # ---- RED 4/7: A5 nonterminal ----------------------------------------

    def test_red4_a5_five_deterministic_rows_cannot_localize(self):
        # Old reducer: five identical A5 rows reach LOCALIZED_FIX_NOT_
        # VALIDATED (A5 counted terminal-capable). #257 falsified that:
        # the corrected reducer must refuse A5 localization -> UNRESOLVED.
        self.arm = "A5"
        self.write_json(self.evidence / "authority.json", {
            "repo_root": str(self.repo),
            "dispatch_capture": self.authority("A5")})
        self._retain_deterministic("A5", LOG_A5)
        self.assertEqual(self.verdict("A5"), C.UNRESOLVED_TERMINAL)

    def test_red7_executed_nonterminal_a5_grants_no_terminal_authority(self):
        # A5 physically executed (variable evidence present) beside the
        # accepted A3 variable result: its presence must not move the
        # terminal away from UNRESOLVED (no authority from evidence
        # presence). Also pins the companion fact: mechanism_status must
        # classify A5 nonterminal with the #257 reason.
        self._retain_variable("A3", LOG_A3)
        self._arm_authority("A5")
        self._retain_variable("A5", LOG_A5)
        self.assertEqual(self.verdict(), C.UNRESOLVED_TERMINAL)
        status = M.mechanism_status(self.evidence, "A5", A.ARMS["A5"]["namespace"])
        self.assertFalse(status["capable"])
        self.assertIn("OBSERVATIONALLY_CAPABLE_NONTERMINAL",
                      status["reason"])

    # ---- RED 5/6: honest terminals and fail-closed coverage -------------

    def test_red5_a3_variable_alone_chooses_unresolved_not_non_localized(self):
        # Coverage is provably incomplete at this pin (H2/H3/H5 gaps), so
        # the correct state is UNRESOLVED — a NON_LOCALIZED terminal must
        # NOT be emitted for the current pin even with every capable arm
        # variable.
        self._retain_variable("A3", LOG_A3)
        out = self.verdict()
        self.assertNotEqual(out, "R8I3C_VULKAN_MECHANISM_NON_LOCALIZED")
        self.assertEqual(out, C.UNRESOLVED_TERMINAL)

    def test_pin6_missing_instrumentation_arm_fails_closed_to_unresolved(self):
        # A future instrumented arm A6 (terminal-capable only with new
        # instrumentation) that has NOT run: the reducer must fail closed
        # to UNRESOLVED, never NON_LOCALIZED. Exercised through the
        # theorem module's coverage law (the reducer consumes it).
        import issue258_theorem as TH
        covered = TH.hypothesis_coverage()
        self.assertFalse(covered["covered"])
        self.assertTrue(any(g["hypothesis"] == "H3" for g in covered["gaps"]))


class TheoremModuleTests(unittest.TestCase):
    """[PIN at corrected head] the frozen capability law itself."""

    def test_pin_capability_matrix_matches_accepted_facts(self):
        import issue258_theorem as TH
        self.assertEqual(TH.TERMINAL_CAPABLE,
                         {"A1": False, "A2": False, "A3": True,
                          "A4": False, "A5": False})

    def test_pin_coverage_incomplete_with_h2_h3_h5_gaps(self):
        import issue258_theorem as TH
        covered = TH.hypothesis_coverage()
        self.assertFalse(covered["covered"])
        self.assertEqual({g["hypothesis"] for g in covered["gaps"]},
                         {"H2", "H3", "H5"})

    def test_pin_theorem_validates(self):
        import issue258_theorem as TH
        self.assertEqual(TH.validate_theorem(), [])

    def test_pin_nonlocalized_constant_defined(self):
        self.assertEqual(C.NON_LOCALIZED_TERMINAL,
                         "R8I3C_VULKAN_MECHANISM_NON_LOCALIZED")


class CapabilityExplicitnessTests(unittest.TestCase):
    """Terminal capability is explicit, not inferred from arm existence."""

    def test_pin_a5_validator_withdrawn_from_capable_registry(self):
        self.assertNotIn("A5", M.MECHANISM_VALIDATORS)
        self.assertIn("A5", M.NON_TERMINAL_CAPABLE)

    def test_pin_a3_validator_remains(self):
        self.assertIn("A3", M.MECHANISM_VALIDATORS)

    def test_red_reducer_consumes_theorem_capability(self):
        # The reducer's terminal derivation must consult the theorem
        # module's capability law, not a local arm-name set.
        import issue252_terminal as T252
        import inspect
        src = inspect.getsource(T252.derive_terminal)
        self.assertIn("terminal_capable", src)


if __name__ == "__main__":
    unittest.main()
