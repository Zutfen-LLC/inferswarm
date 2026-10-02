"""Prospective per-arm mechanism-evidence contracts (CPU-only fixtures).

Includes the adversarial-review spoof cases: copied marker text, fabricated
allocation lines, mixed-unit tallies, and near-miss markers must all be
rejected by the exact-format + ledger laws.
"""
from __future__ import annotations
import json
import unittest
from pathlib import Path

from tests.test_issue252_physical import FixtureMixin, A, C
import issue252_mechanism as M

NL = chr(10)
ENUM_BASE = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | uma: 0 | fp16: 1"
             " | bf16: 0 | fp4: 0 | warp size: 32 | shared memory: 49152"
             " | int dot: 1 | matrix cores: ")
MEM = "ggml_vulkan memory: NVIDIA GeForce RTX 3060: "
ENUM_ONLY = ENUM_BASE + "NV_coopmat2" + NL
ENUM_NONE_ONLY = ENUM_BASE + "none" + NL
ENUM_NV = (ENUM_ONLY +
           MEM + "+4.00 MiB device at 0x1. Total device: 4.00 MiB, total host: 0 B" + NL)
ENUM_NONE = (ENUM_BASE + "none" + NL +
             MEM + "+4.00 MiB device at 0x1. Total device: 4.00 MiB, total host: 0 B" + NL)
ENUM_KHR = (ENUM_BASE + "KHR_coopmat" + NL +
            MEM + "+4.00 MiB device at 0x1. Total device: 4.00 MiB, total host: 0 B" + NL)
DEV_ALLOC = (MEM + "+4.00 MiB device at 0x1."
             " Total device: 4.00 MiB, total host: 0 B" + NL)
HOST_ALLOC = (MEM + "+16.00 MiB host at 0x2."
              " Total device: 4.00 MiB, total host: 16.00 MiB" + NL)
STAGING = "ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer(4194304)" + NL
ASYNC_OFF = ("ggml_vulkan: WARNING: Async execution disabled on certain Intel devices."
             + NL)
HOST_STAGING_ALLOC = (MEM + "+4.00 MiB host at 0x3."
                      " Total device: 4.00 MiB, total host: 4.00 MiB" + NL)


def _fmt(b):
    if b >= 1024 ** 2: return f"{b / 1024 ** 2:.2f} MiB"
    if b >= 1024: return f"{b / 1024:.2f} KiB"
    return f"{b} B"


def make_log(family, events):
    """Build a ledger-consistent unit log; events are ("device"|"host", bytes)
    or ("staging", bytes) which logs the staging line plus its host alloc."""
    lines = [ENUM_BASE + family]
    td = th = 0
    for kind, size in events:
        if kind == "staging":
            lines.append("ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer("
                         + str(size) + ")")
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



def write(root: Path, namespace: str, name: str, log: str) -> None:
    unit = root / namespace / name
    unit.mkdir(parents=True, exist_ok=True)
    (unit / "server.log").write_text(log, encoding="utf-8")
    # AMENDMENT-005: A3's retained placement/identity law reads these
    # per-unit files; A2/A5 validators ignore them.
    (unit / "placement.json").write_text(json.dumps({
        "output_projection": "Vulkan", "embedding": "CPU", "ngl": 1,
        "gpu_uuid": C.HOST_FACTS["gpu_uuid"],
        "vulkan_family": "NV_coopmat2",
        "vulkan_family_authority": "frozen-host-facts",
        "cuda_participation": False}, sort_keys=True))
    for phase in ("identity-pre.json", "identity-post.json"):
        (unit / phase).write_text(
            json.dumps(dict(C.HOST_FACTS), sort_keys=True))


class MechanismTests(FixtureMixin, unittest.TestCase):
    def setUp(self):
        self.fixture()
        self.ns = A.ARMS["A4"]["namespace"]

    # --- A1 non-terminal-capable ------------------------------------------

    def test_a1_is_non_terminal_capable(self):
        status = M.mechanism_status(self.evidence, "A1", A.ARMS["A1"]["namespace"])
        self.assertFalse(status["capable"])
        self.assertIn("serialize", status["reason"])

    # --- A2 ----------------------------------------------------------------

    def test_a2_positive_khr_disabled(self):
        # Only family "none" proves the KHR gate was both live and
        # path-changing on this subject.
        write(self.evidence, A.ARMS["A2"]["namespace"], "u1", ENUM_NONE)
        status = M.mechanism_status(self.evidence, "A2", A.ARMS["A2"]["namespace"])
        self.assertTrue(status["capable"])

    def test_a2_dead_control_on_nv_subject(self):
        # This RTX 3060's accepted capability line shows NV_coopmat2, which
        # GGML_VK_DISABLE_COOPMAT does not gate: dead control, no mechanism.
        write(self.evidence, A.ARMS["A2"]["namespace"], "u1", ENUM_NV)
        with self.assertRaisesRegex(M.MechanismInvalid, "dead control"):
            M.mechanism_status(self.evidence, "A2", A.ARMS["A2"]["namespace"])

    def test_a2_khr_still_active_rejected(self):
        write(self.evidence, A.ARMS["A2"]["namespace"], "u1", ENUM_KHR)
        with self.assertRaisesRegex(M.MechanismInvalid, "KHR coopmat still active"):
            M.mechanism_status(self.evidence, "A2", A.ARMS["A2"]["namespace"])

    def test_a2_missing_enumeration_rejected(self):
        write(self.evidence, A.ARMS["A2"]["namespace"], "u1", "no markers" + NL)
        with self.assertRaisesRegex(M.MechanismInvalid, "enumeration"):
            M.mechanism_status(self.evidence, "A2", A.ARMS["A2"]["namespace"])

    def test_a2_spoofed_enumeration_text_rejected(self):
        # Adversarial-review case: "matrix cores:" text outside the pin's
        # exact enumeration line is not evidence.
        spoof = "operator note | matrix cores: none" + NL
        write(self.evidence, A.ARMS["A2"]["namespace"], "u1", spoof)
        with self.assertRaisesRegex(M.MechanismInvalid, "outside the exact"):
            M.mechanism_status(self.evidence, "A2", A.ARMS["A2"]["namespace"])

    def test_a2_family_differs_across_units_rejected(self):
        write(self.evidence, A.ARMS["A2"]["namespace"], "u1", ENUM_NONE)
        write(self.evidence, A.ARMS["A2"]["namespace"], "u2", ENUM_KHR)
        with self.assertRaisesRegex(M.MechanismInvalid, "across retained units"):
            M.mechanism_status(self.evidence, "A2", A.ARMS["A2"]["namespace"])

    # --- A3 ----------------------------------------------------------------

    def test_a3_positive(self):
        write(self.evidence, A.ARMS["A3"]["namespace"], "u1", ASYNC_OFF + ENUM_NV)
        status = M.mechanism_status(self.evidence, "A3", A.ARMS["A3"]["namespace"])
        self.assertTrue(status["capable"])

    def test_a3_marker_missing_rejected(self):
        write(self.evidence, A.ARMS["A3"]["namespace"], "u1", ENUM_NV)
        with self.assertRaisesRegex(M.MechanismInvalid, "async-disabled"):
            M.mechanism_status(self.evidence, "A3", A.ARMS["A3"]["namespace"])

    def test_a3_copied_marker_text_rejected(self):
        # Adversarial-review case: marker text embedded in an unrelated line
        # (not the pin's exact stderr line) must not count.
        spoof = ("NOT A VULKAN LOG: Async execution disabled on certain Intel "
                 "devices. copied here" + NL + ENUM_NV)
        write(self.evidence, A.ARMS["A3"]["namespace"], "u1", spoof)
        with self.assertRaisesRegex(M.MechanismInvalid, "non-exact"):
            M.mechanism_status(self.evidence, "A3", A.ARMS["A3"]["namespace"])

    # --- A4 (non-terminal-capable at pin b29c606e; round 4) -----------------

    def test_a4_non_terminal_capable_with_source_reason(self):
        # Round-4 source audit: no retained observable binds an allocation
        # line to the prefer_host_memory branch (logger carries no buffer
        # identity/call site; staging and pinned-host paths produce
        # host-typed lines regardless; no preference-off baseline ledger).
        write(self.evidence, self.ns, "u1", make_log("NV_coopmat2",
            [("device", 4 * 1024 ** 2), ("host", 16 * 1024 ** 2)]))
        status = M.mechanism_status(self.evidence, "A4", self.ns)
        self.assertFalse(status["capable"])
        self.assertIn("b29c606e", status["reason"])
        self.assertIn("no retained observable", status["reason"])

    def test_a4_unrelated_host_allocations_cannot_satisfy(self):
        # Adversarial case: a rich mixed host/device ledger (even one
        # containing staging-sized host lines) must not prove the
        # preference-controlled branch changed the model/weight path.
        write(self.evidence, self.ns, "u1", make_log("NV_coopmat2",
            [("staging", 4 * 1024 ** 2), ("device", 4 * 1024 ** 2),
             ("host", 16 * 1024 ** 2)]))
        self.assertFalse(
            M.mechanism_status(self.evidence, "A4", self.ns)["capable"])

    def test_a4_no_validator_registered(self):
        self.assertNotIn("A4", M.MECHANISM_VALIDATORS)
        self.assertIn("A4", M.NON_TERMINAL_CAPABLE)

    # --- A5 (#258/AMENDMENT-006: nonterminal per #257; the frozen
    # staging state-machine law is retained and directly tested as the
    # falsified prospective law) -------------------------------------------

    def test_a5_nonterminal_classification_with_257_reason(self):
        write(self.evidence, A.ARMS["A5"]["namespace"], "u1",
              make_log("NV_coopmat2",
                       [("staging", 4 * 1024 ** 2), ("device", 8 * 1024 ** 2)]))
        status = M.mechanism_status(self.evidence, "A5", A.ARMS["A5"]["namespace"])
        self.assertFalse(status["capable"])
        self.assertIn("OBSERVATIONALLY_CAPABLE_NONTERMINAL", status["reason"])

    def test_a5_withdrawn_from_capable_registry(self):
        self.assertNotIn("A5", M.MECHANISM_VALIDATORS)
        self.assertIn("A5", M.NON_TERMINAL_CAPABLE)

    def test_a5_retained_law_authentic_staging_accepted(self):
        # The retained law still validates an authentic staging stream
        # when invoked directly (custody law, not localization authority).
        log = make_log("NV_coopmat2", [("staging", 4 * 1024 ** 2), ("device", 8 * 1024 ** 2)])
        write(self.evidence, A.ARMS["A5"]["namespace"], "u1", log)
        facts = M._mechanism_a5(self.evidence, A.ARMS["A5"]["namespace"])
        self.assertIn("staging", str(facts["mechanism"]))

    def test_a5_host_allocation_beyond_staging_rejected(self):
        # A host-typed allocation that is NOT the staging buffer proves
        # host-visible memory was NOT disabled.
        log = make_log("NV_coopmat2", [("staging", 4 * 1024 ** 2), ("device", 8 * 1024 ** 2), ("host", 16 * 1024 ** 2)])
        write(self.evidence, A.ARMS["A5"]["namespace"], "u1", log)
        with self.assertRaisesRegex(M.MechanismInvalid,
                                    "outside the staging"):
            M._mechanism_a5(self.evidence, A.ARMS["A5"]["namespace"])

    def test_a5_staging_line_without_staging_allocation_rejected(self):
        # Staging line present but its matching host-typed allocation line
        # stripped — a doctored log that must fail the pairing law.
        log = make_log("NV_coopmat2", [("staging", 4 * 1024 ** 2), ("device", 8 * 1024 ** 2)])
        stripped = NL.join(l for l in log.splitlines()
                           if " host at 0x" not in l) + NL
        assert "sync_staging_buffer" in stripped and " host at" not in stripped
        write(self.evidence, A.ARMS["A5"]["namespace"], "u1", stripped)
        # Either law may fire first: the ledger (removing a line breaks the
        # printed running totals) or the staging/allocation pairing.
        with self.assertRaisesRegex(M.MechanismInvalid,
                                    "ledger|matching host-typed"):
            M._mechanism_a5(self.evidence, A.ARMS["A5"]["namespace"])

    def test_a5_staging_line_missing_rejected(self):
        write(self.evidence, A.ARMS["A5"]["namespace"], "u1", make_log("NV_coopmat2", [("device", 4 * 1024 ** 2)]))
        with self.assertRaisesRegex(M.MechanismInvalid, "sync-staging"):
            M._mechanism_a5(self.evidence, A.ARMS["A5"]["namespace"])

    def test_a5_spoofed_staging_call_text_rejected(self):
        # Adversarial-review case: staging function name inside a random
        # line is not the pin's staging log line.
        spoof = ("operator note ggml_vk_ensure_sync_staging_buffer(not a call" + NL
                 + ENUM_ONLY + DEV_ALLOC)
        write(self.evidence, A.ARMS["A5"]["namespace"], "u1", spoof)
        with self.assertRaisesRegex(M.MechanismInvalid, "sync-staging"):
            M._mechanism_a5(self.evidence, A.ARMS["A5"]["namespace"])

    # --- generic mutation discipline ---------------------------------------

    def test_missing_namespace_rejected(self):
        # A3 is still validator-backed after A4 became non-terminal-capable.
        with self.assertRaisesRegex(M.MechanismInvalid, "absent/unsafe"):
            M.mechanism_status(self.evidence, "A3", "d252-nonexistent")

    def test_unknown_arm_rejected(self):
        with self.assertRaisesRegex(M.MechanismInvalid, "no prospective"):
            M.mechanism_status(self.evidence, "A9", self.ns)

    def test_mechanism_separate_from_determinism(self):
        # Mechanism facts carry no determinism claim; a capable status is
        # independent of retained rows/counts. Uses A3 (the capable arm).
        log = ASYNC_OFF + make_log("NV_coopmat2", [("device", 4 * 1024 ** 2)])
        write(self.evidence, A.ARMS["A3"]["namespace"], "only-one-unit", log)
        status = M.mechanism_status(self.evidence, "A3", A.ARMS["A3"]["namespace"])
        self.assertTrue(status["capable"])
        self.assertNotIn("deterministic", str(status["facts"]).lower())


if __name__ == "__main__":
    unittest.main()
